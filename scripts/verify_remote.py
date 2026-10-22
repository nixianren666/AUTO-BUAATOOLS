"""Password/headless/browser regression with a disposable synthetic process."""
import argparse,json,os,socket,subprocess,sys,tempfile,time,shutil
from pathlib import Path
import httpx

def main():
    p=argparse.ArgumentParser();p.add_argument('--executable');p.add_argument('--report-dir',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parent.parent;output=Path(args.report_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='buaa-remote-acceptance-') as directory:
        private=Path(directory)
        env=dict(os.environ,BUAA_ADMIN_PASSWORD='synthetic-remote-admin',BUAA_ACCEPTANCE_ADMIN='synthetic-remote-admin',PYTHON_KEYRING_BACKEND='keyring.backends.fail.Keyring',BUAA_VAULT_DIR=str(private/'vault'))
        env.pop('BUAA_CONFIG_FILE',None)
        env['NODE_PATH']=os.environ.get('BUAA_NODE_MODULES') or os.environ.get('NODE_PATH','')
        command=[str(Path(args.executable).resolve())] if args.executable else [sys.executable,str(root/'run.py')]
        with (output/'remote-process.txt').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(command+['--headless','--smoke-profile','--port',str(port)],cwd=private,env=env,stdout=log,stderr=log)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=5) as c:
                try:
                    for i in range(200):
                        if proc.poll() is not None:raise RuntimeError('Remote fixture exited')
                        try:
                            if c.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.2)
                    else:raise RuntimeError('Remote fixture readiness timeout')
                    browser=os.environ.get('BUAA_TEST_BROWSER','')
                    if not browser and sys.platform=='win32':browser='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
                    r=subprocess.run([shutil.which('node'),str(root/'scripts/remote_acceptance.cjs'),str(c.base_url),browser,str(output/'remote-browser.json')],env=env,capture_output=True,text=True,timeout=240)
                    assert r.returncode==0,r.stderr[-2000:]
                    assert json.loads((output/'remote-browser.json').read_text(encoding='utf-8'))['passed']
                finally:
                    # Browser tests deliberately log out; establish an independent
                    # local fixture session to shut down only our child process.
                    try:
                        q=c.post('/api/session',json={'password':'synthetic-remote-admin'})
                        if q.status_code==429:
                            # Extra phone login shares the real per-IP budget.
                            # Respect its Retry-After; never relax production limits.
                            delay=int(q.headers.get('Retry-After','61'))
                            assert 1<=delay<=61,'Unexpected management retry interval'
                            time.sleep(delay)
                            q=c.post('/api/session',json={'password':'synthetic-remote-admin'})
                        if q.status_code==200:c.post('/api/exit',headers={'X-BUAA-CSRF':q.json()['csrf']})
                    except httpx.HTTPError:pass
                    try:proc.wait(timeout=12)
                    except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=10)
        assert proc.returncode==0,'Remote fixture did not exit cleanly'
    print(json.dumps({'passed':True,'compiled':bool(args.executable),'checks':13,'real_school_writes':0}))

if __name__=='__main__':main()
