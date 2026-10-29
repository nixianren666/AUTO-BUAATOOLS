"""Fresh native build, post-build tests and provenance; never publishes a Release."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import plistlib

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core.version import VERSION

def call(*args):
    subprocess.run(list(args),cwd=ROOT,check=True)

def main():
    dist=ROOT/"dist"
    if dist.exists() and any(dist.iterdir()):
        raise RuntimeError("构建目录必须为空，避免混入旧版本产物；请使用独立构建目录")
    output=ROOT/"release-assets";output.mkdir(exist_ok=True)
    if any(output.iterdir()):raise RuntimeError("产物目录必须为空")
    system=sys.platform;arch=platform.machine().lower()
    suffix={"win32":"Windows-x64","darwin":"macOS-"+arch,"linux":"Linux-"+arch}[system]
    spec={"win32":"BUAA-Signin.spec","darwin":"BUAA-Signin-mac.spec","linux":"BUAA-Signin-linux.spec"}[system]
    call(sys.executable,"-m","PyInstaller","--noconfirm","--clean",spec)
    executable=dist/("BUAA-Signin.exe" if system=="win32" else "BUAA-Signin.app/Contents/MacOS/BUAA-Signin" if system=="darwin" else "BUAA-Signin")
    if system=="darwin":
        call("codesign","--force","--deep","-s","-",str(dist/"BUAA-Signin.app"))
        call("codesign","--verify","--deep","--strict",str(dist/"BUAA-Signin.app"))
    call(sys.executable,"scripts/verify_compiled.py","--executable",str(executable),"--report-dir",str(ROOT/"acceptance"),"--native")
    embedded_env = dict(os.environ, BUAA_TEST_REPORT_DIR=str(ROOT/'acceptance/network-embedded'))
    subprocess.run([sys.executable, 'scripts/test_isolated.py', '--embedded-executable', str(executable), '--pattern', 'test_network_session_separation.py'], cwd=ROOT, env=embedded_env, check=True)
    subprocess.run([sys.executable, 'scripts/test_isolated.py', '--embedded-executable', str(executable), '--pattern', 'test_td.py'], cwd=ROOT, env=dict(os.environ, BUAA_TEST_REPORT_DIR=str(ROOT/'acceptance/td-embedded')), check=True)
    call(sys.executable,"scripts/verify_remote.py","--executable",str(executable),"--report-dir",str(ROOT/"acceptance/remote-compiled"))
    call(sys.executable,"scripts/verify_management_setup.py","--executable",str(executable),"--report-dir",str(ROOT/"acceptance/setup-compiled"))
    for contract in ('test_management_recovery.py','test_wechat_notifications.py','test_wechat_api.py','test_wechat_storage.py','test_course_reminders.py','test_wechat_longevity.py','test_account_switch_failure.py'):
        subprocess.run([sys.executable,'scripts/test_isolated.py','--embedded-executable',str(executable),'--pattern',contract],
            cwd=ROOT,env=dict(os.environ,BUAA_TEST_REPORT_DIR=str(ROOT/'acceptance'/contract.removesuffix('.py'))),check=True)
    if os.environ.get("GITHUB_ACTIONS")=="true":
        call(sys.executable,"scripts/verify_native_service.py","--executable",str(executable),"--report-dir",str(ROOT/"acceptance"))
    if system=="win32":
        shutil.copy2(executable,output/f"BUAA-Signin-v{VERSION}-portable.exe")
        compiler=os.environ.get("BUAA_ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if not Path(compiler).is_file():raise RuntimeError("Inno Setup compiler required")
        call(compiler,"installer/setup.iss")
        setup=ROOT/"dist_installer"/f"BUAA-Signin-Setup-v{VERSION}.exe"
        # Validate installed executable and safe uninstall in a temporary location.
        call(sys.executable,"scripts/verify_installer.py","--installer",str(setup),"--expected-executable",str(executable),"--report-dir",str(ROOT/"acceptance"))
        shutil.copy2(setup,output/setup.name)
    elif system=="darwin":
        staging=dist/"dmg-root";staging.mkdir()
        shutil.copytree(dist/"BUAA-Signin.app",staging/"BUAA-Signin.app",symlinks=True)
        (staging/"Applications").symlink_to("/Applications")
        call("hdiutil","create","-volname",f"BUAA-Signin {VERSION}","-srcfolder",str(staging),"-ov","-format","UDZO",str(output/f"BUAA-Signin-v{VERSION}-{suffix}.dmg"))
        call("ditto","-c","-k","--sequesterRsrc","--keepParent",str(dist/"BUAA-Signin.app"),str(output/f"BUAA-Signin-v{VERSION}-{suffix}.zip"))
        dmg=output/f"BUAA-Signin-v{VERSION}-{suffix}.dmg"
        call("hdiutil","verify",str(dmg))
        def tree_hashes(directory):
            return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}
        with tempfile.TemporaryDirectory(prefix="buaa-dmg-acceptance-") as directory:
            mount=Path(directory)/"volume";mount.mkdir()
            subprocess.run(["hdiutil","attach","-readonly","-nobrowse","-mountpoint",str(mount),str(dmg)],check=True,capture_output=True)
            try:
                packaged=mount/"BUAA-Signin.app"
                assert tree_hashes(packaged)==tree_hashes(dist/"BUAA-Signin.app"),"DMG contains another application payload"
                assert plistlib.loads((packaged/"Contents/Info.plist").read_bytes())["CFBundleVersion"]==VERSION
                call("codesign","--verify","--deep","--strict",str(packaged))
            finally:call("hdiutil","detach",str(mount))
        (ROOT/"acceptance/dmg-summary.json").write_text(json.dumps({"passed":True,"version":VERSION,"dmg_integrity_verified":True,"mounted_payload_matches_tested_application":True}),encoding="utf-8")
    else:
        with tarfile.open(output/f"BUAA-Signin-v{VERSION}-{suffix}.tar.gz","w:gz") as archive:
            archive.add(executable,arcname="BUAA-Signin")
            archive.add(ROOT/"README.md",arcname="README.md")
    commit=os.environ.get("GITHUB_SHA") or os.environ.get("BUAA_BUILD_COMMIT","development-unpublished")
    assets=[{"name":file.name,"size":file.stat().st_size,"sha256":hashlib.sha256(file.read_bytes()).hexdigest()} for file in sorted(output.iterdir()) if file.is_file()]
    manifest={"version":VERSION,"commit":commit,"run_id":os.environ.get("GITHUB_RUN_ID"),"platform":system,"architecture":arch,"python":platform.python_version(),"dependencies":sorted({d.metadata['Name']+"=="+d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}),"post_build_verified":True,"assets":assets}
    (output/f"manifest-{suffix}.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":main()
