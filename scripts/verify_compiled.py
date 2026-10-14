"""Exercise the built process and its browser, exclusively with synthetic profiles."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx

def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        return probe.getsockname()[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--executable",required=True)
    parser.add_argument("--report-dir",required=True)
    parser.add_argument("--native",action="store_true")
    args=parser.parse_args()
    exe=Path(args.executable).resolve(); output=Path(args.report_dir).resolve()
    assert exe.is_file(),"Built executable required"
    output.mkdir(parents=True,exist_ok=True)
    port=free_port(); base=f"http://127.0.0.1:{port}"
    env=dict(os.environ)
    for key in ("BUAA_ADMIN_PASSWORD","BUAA_ALLOWED_HOSTS","BUAA_CONFIG_FILE","BUAA_SMOKE_PROFILE"):
        env.pop(key,None)
    checks=[]
    with tempfile.TemporaryDirectory(prefix="buaa-compiled-acceptance-") as directory:
        with open(Path(directory)/"process-output.txt","w",encoding="utf-8") as log:
            proc=subprocess.Popen([str(exe),"--headless","--smoke-profile","--port",str(port)],cwd=directory,env=env,stdout=log,stderr=log)
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as client:
                try:
                    deadline=time.monotonic()+90
                    while time.monotonic()<deadline:
                        if proc.poll() is not None: raise RuntimeError("Built process exited before readiness")
                        try:
                            health=client.get("/api/health").json()
                            if health.get("version")=="1.2.7":break
                        except (httpx.HTTPError,ValueError):pass
                        time.sleep(0.2)
                    else: raise RuntimeError("Built process readiness timeout")
                    assert health["application"]=="AUTO-BUAATOOLS"
                    checks.append("compiled-version-and-application-identity")
                    assert client.get("/api/accounts").status_code==401
                    csrf=client.get("/api/session").json()["csrf"]
                    assert client.post("/api/boya/select",json={"course_id":2003}).status_code==403
                    client.headers["X-BUAA-CSRF"]=csrf
                    accounts=client.get("/api/accounts").json()["accounts"]
                    assert {a["username"] for a in accounts}=={"fixture-account-1","fixture-account-2"}
                    assert not any(a["auto_checkin"] or a["boya_auto_select"] or a["boya_auto_sign"] for a in accounts)
                    checks.append("private-synthetic-profile-and-management-boundary")
                    node=os.environ.get("BUAA_NODE_EXECUTABLE") or shutil.which("node")
                    assert node,"Node.js required for compiled browser tests"
                    root=Path(__file__).resolve().parent.parent
                    browser=os.environ.get("BUAA_TEST_BROWSER","")
                    if not browser and sys.platform=="win32":
                        browser=r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
                    browser_env=dict(env)
                    if os.environ.get("BUAA_NODE_MODULES"):
                        browser_env["NODE_PATH"]=os.environ["BUAA_NODE_MODULES"]
                    result=subprocess.run([node,str(root/"scripts/ui_acceptance.cjs"),base+"/",browser,str(output/"compiled-browser.json")],env=browser_env,capture_output=True,text=True,timeout=100)
                    assert result.returncode==0,result.stderr[-2000:]
                    browser_result=json.loads((output/"compiled-browser.json").read_text(encoding="utf-8"))
                    assert browser_result["passed"]
                    checks.extend(browser_result["checks"])
                finally:
                    try:client.post("/api/exit",json={})
                    except httpx.HTTPError:pass
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.terminate();proc.wait(timeout=10)
                    log.flush()
                    shutil.copy2(Path(directory)/"process-output.txt",output/"compiled-process-output.txt")
    assert proc.returncode==0,"Built process did not exit cleanly"
    if args.native:
        native=output/"compiled-native.json"
        native_env=dict(env)
        if sys.platform=="linux" and os.environ.get("GITHUB_ACTIONS")=="true":
            native_env["QT_DEBUG_PLUGINS"]="1"
        with open(output/"compiled-native-output.txt","w",encoding="utf-8") as native_log:
            result=subprocess.run([str(exe),"--smoke-test","--smoke-report",str(native),"--port",str(free_port())],env=native_env,stdout=native_log,stderr=native_log,timeout=100)
        assert result.returncode==0 and native.exists(),"Compiled native window must complete"
        state=json.loads(native.read_text(encoding="utf-8"))
        assert state["passed"] and state["native_gui"]
        expected_native={"native-boya-sign","native-boya-signout-without-invented-assessment","native-account-switch","native-regular-sign"}
        assert set(state.get("checks",[]))==expected_native,"Native engine must exercise all required interactions"
        checks.extend(state["checks"])
        checks.append("compiled-native-desktop-window")
    summary={"passed":True,"version":"1.2.7","platform":sys.platform,"checks":checks,"real_school_writes":0}
    (output/"compiled-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__":main()
