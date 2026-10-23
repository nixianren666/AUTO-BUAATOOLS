"""Actual user service test, restricted to disposable GitHub native runners."""
import argparse
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core import autostart
from core.version import VERSION

def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform not in ("linux","darwin","win32"):
        raise RuntimeError("Native service acceptance is restricted to disposable CI runners")
    parser=argparse.ArgumentParser();parser.add_argument("--executable",required=True);parser.add_argument("--report-dir",required=True)
    args=parser.parse_args();exe=str(Path(args.executable).resolve())
    path=autostart.get_linux_service_path() if sys.platform=="linux" else autostart.get_mac_plist_path() if sys.platform=="darwin" else None
    if (path is not None and path.exists()) or autostart.get_autostart_status():raise RuntimeError("Refusing to overwrite an existing user service")
    with tempfile.TemporaryDirectory(prefix="buaa-native-service-") as directory:
        config=Path(directory)/"config.json";config.write_text("{}")
        with patch.dict(os.environ,{"BUAA_CONFIG_FILE":str(config)}),patch.object(sys,"executable",exe),patch.object(sys,"frozen",True,create=True):
            process=None
            try:
                assert autostart.set_autostart(True,headless=True)
                assert autostart.get_autostart_status()
                if sys.platform=="linux":subprocess.run(["systemctl","--user","start","buaa-signin.service"],check=True)
                elif sys.platform=="win32":
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,autostart.REG_RUN_PATH) as key:
                        command,_=winreg.QueryValueEx(key,autostart.REG_APP_KEY)
                    assert command==autostart.get_executable_command()
                    # Run the actual saved command; no sign-in credentials are configured.
                    process=subprocess.Popen(command)
                with httpx.Client(base_url="http://127.0.0.1:18346",trust_env=False,timeout=2) as client:
                    deadline=time.monotonic()+60
                    while time.monotonic()<deadline:
                        try:
                            data=client.get("/api/health").json()
                            if data.get("version")==VERSION:break
                        except (httpx.HTTPError,ValueError):pass
                        time.sleep(0.2)
                    else:raise RuntimeError("Native service did not start its compiled executable")
                    session=client.get("/api/session")
                    if sys.platform in ("linux", "darwin"):
                        # A fresh headless service must now require its owner's
                        # private initialization proof. Test that real flow,
                        # rather than assuming the former anonymous bootstrap.
                        assert session.status_code==401 and session.json()["setup_required"] is True
                        assert client.get("/api/accounts").status_code==401
                        proof=(config.parent/".management-setup-token").read_text().strip()
                        fixture_password=secrets.token_urlsafe(24)
                        setup=client.post("/api/management/setup",json={"password":fixture_password,"proof":proof})
                        setup.raise_for_status()
                        assert len(setup.json()["recovery_code"])>=40
                        stored=(config.parent/".management-private.json").read_text()
                        assert fixture_password not in stored and setup.json()["recovery_code"] not in stored
                        csrf=setup.json()["csrf"]
                        client.delete("/api/session",headers={"X-BUAA-CSRF":csrf}).raise_for_status()
                        assert client.get("/api/accounts").status_code==401
                        session=client.post("/api/session",json={"password":fixture_password})
                    session.raise_for_status()
                    client.headers["X-BUAA-CSRF"]=session.json()["csrf"]
                    assert client.get("/api/accounts").json()["accounts"]==[]
                    if sys.platform=="win32":
                        client.post("/api/exit",json={}).raise_for_status()
                        assert process.wait(timeout=20)==0
            finally:
                if process is not None and process.poll() is None:
                    process.terminate();process.wait(timeout=10)
                if sys.platform=="linux":subprocess.run(["systemctl","--user","stop","buaa-signin.service"],check=True)
                assert autostart.set_autostart(False)
                assert not autostart.get_autostart_status() and (path is None or not path.exists())
    result={"passed":True,"platform":sys.platform,"compiled_service_started":True,"enabled_status_verified":True,"service_removed":True,"real_school_writes":0,"reboot_tested":False,"first_headless_setup_tested":sys.platform in ("linux","darwin")}
    output=Path(args.report_dir);output.mkdir(parents=True,exist_ok=True)
    (output/"native-service-summary.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result))

if __name__=="__main__":main()
