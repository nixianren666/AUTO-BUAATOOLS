"""Real first-run UI against a fresh empty profile, source or packaged app."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import httpx


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable');p.add_argument('--report-dir',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parent.parent;output=Path(args.report_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='buaa-setup-') as directory:
        profile=Path(directory);(profile/'config.json').write_text('{}')
        env=dict(os.environ,TESTING='1',PYTHONUNBUFFERED='1',BUAA_CONFIG_FILE=str(profile/'config.json'),BUAA_VAULT_DIR=str(profile/'vault'))
        for key in ('BUAA_ADMIN_PASSWORD','BUAA_SMOKE_PROFILE','BUAA_RUNTIME_MODE'):env.pop(key,None)
        env['NODE_PATH']=os.environ.get('BUAA_NODE_MODULES') or os.environ.get('NODE_PATH','')
        command=[str(Path(args.executable).resolve())] if args.executable else [sys.executable,str(root/'run.py')]
        with (output/'setup-process-private.txt').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(command+['--headless','--config',str(profile/'config.json'),'--port',str(port)],env=env,cwd=profile,stdout=log,stderr=log)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=5) as client:
                try:
                    for i in range(200):
                        if proc.poll() is not None:raise RuntimeError('First-run fixture exited')
                        try:
                            if client.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('First-run fixture readiness timeout')
                    env['BUAA_ACCEPTANCE_SETUP']=(profile/'.management-setup-token').read_text().strip()
                    browser=os.environ.get('BUAA_TEST_BROWSER','')
                    if not browser and sys.platform=='win32':browser='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
                    result=subprocess.run([shutil.which('node'),str(root/'scripts/management_setup_acceptance.cjs'),str(client.base_url).rstrip('/')+'/',browser,str(output/'setup-browser.json')],env=env,capture_output=True,text=True,timeout=120)
                    assert result.returncode==0,result.stderr[-1500:]
                    raw=(profile/'.management-private.json').read_text()
                    assert 'synthetic-reset-password' not in raw
                finally:
                    try:
                        r=client.post('/api/session',json={'password':'synthetic-reset-password'})
                        if r.status_code==200:client.post('/api/exit',headers={'X-BUAA-CSRF':r.json()['csrf']})
                    except httpx.HTTPError:pass
                    try:proc.wait(timeout=12)
                    except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10)
    # Disposable initialization proof is never part of distributable evidence.
    log_path=output/'setup-process-private.txt'
    log_path.write_text(re.sub(r'(#setup=)[^\s]+',r'\1[redacted]',log_path.read_text(encoding='utf-8')),encoding='utf-8')
    print(json.dumps({'passed':True,'compiled':bool(args.executable),'school_writes':0}))


if __name__=='__main__':main()
