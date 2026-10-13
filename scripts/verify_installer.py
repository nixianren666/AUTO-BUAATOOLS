"""Windows installation/upgrading/uninstallation in a private temporary directory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--installer",required=True);parser.add_argument("--expected-executable",required=True);parser.add_argument("--report-dir",required=True)
    args=parser.parse_args()
    setup=Path(args.installer).resolve();expected=Path(args.expected_executable).resolve()
    with tempfile.TemporaryDirectory(prefix="buaa-installer-acceptance-") as directory:
        target=Path(directory)/"Application";target.mkdir()
        config=target/"config.json";config.write_text('{"accounts":[],"fixture_preserve":true}')
        unrelated=target/"unrelated-user-file.txt";unrelated.write_text("synthetic preserve marker")
        argv=[str(setup),"/BUAA-ACCEPTANCE=1","/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/CURRENTUSER","/NOICONS","/TASKS=","/DIR="+str(target)]
        subprocess.run(argv,check=True,timeout=120)
        installed=target/"BUAA-Signin.exe"
        assert digest(installed)==digest(expected),"Installer contains another build"
        assert json.loads(config.read_text())["fixture_preserve"]
        # Re-install must also preserve preexisting data.
        subprocess.run(argv,check=True,timeout=120)
        assert config.exists() and unrelated.exists()
        subprocess.run([sys.executable,str(Path(__file__).with_name("verify_compiled.py")),"--executable",str(installed),"--report-dir",str(Path(args.report_dir)/"installed"),"--native"],check=True,timeout=240)
        subprocess.run([str(target/"unins000.exe"),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"],check=True,timeout=120)
        assert config.exists() and unrelated.exists(),"Uninstall removed user data"
        assert not installed.exists(),"Installed executable survived uninstall"
    result={"passed":True,"installation":"fresh-and-upgrade","payload_matches_portable":True,"compiled_installed_app_verified":True,"uninstall_preserves_user_files":True}
    output=Path(args.report_dir);output.mkdir(parents=True,exist_ok=True)
    (output/"installer-summary.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result))

if __name__=="__main__":main()
