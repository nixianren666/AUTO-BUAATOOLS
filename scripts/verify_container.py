"""Real Docker browser/volume checks, only on disposable Linux CI runners."""
import argparse,json,os,shutil,socket,subprocess,sys,time,tempfile
from pathlib import Path
import httpx

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or not sys.platform.startswith('linux'):
        raise RuntimeError('Container acceptance only runs on disposable Linux CI')
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',required=True);args=parser.parse_args()
    output=Path(args.report_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    suffix=str(os.getpid());image='buaa-acceptance:'+suffix;container='buaa-acceptance-'+suffix;volume=container+'-data';network=container+'-net'
    def docker(*a,**kw):
        r=subprocess.run(['docker',*a],capture_output=True,text=True,timeout=kw.pop('timeout',90),**kw)
        if r.returncode:
            (output/'docker-error.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
            raise RuntimeError('Docker operation failed: '+(r.stdout+r.stderr)[-3000:])
        return (r.stdout+r.stderr if a and a[0]=='logs' else r.stdout).strip()
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    checks=[];logs=[]
    audit=output/'audit';audit.mkdir(exist_ok=True)
    (audit/'sitecustomize.py').write_text("""import sys
def guard(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and str(args[1][0]) not in ('127.0.0.1','localhost','::1'):
  print('BUAA_ACCEPTANCE_BLOCKED_NETWORK',file=sys.stderr,flush=True)
  raise PermissionError('Container acceptance forbids external connections')
sys.addaudithook(guard)
""",encoding='utf-8')
    try:
        docker('build','-t',image,'.',timeout=420);docker('volume','create',volume)
        # Match the documented deployment's published bridge port. --internal
        # changes host routing; prohibit application egress with a CI-only hook
        # instead, retaining real browser/password/cookie traffic through Docker.
        common=['run','-d','--name',container,'--cap-drop','ALL','--security-opt','no-new-privileges',
                '-p',f'127.0.0.1:{port}:18346','-v',volume+':/data','-v',str(audit)+':/audit:ro','-e','PYTHONPATH=/audit:/app','-e','BUAA_ADMIN_PASSWORD=synthetic-remote-admin','-e','BUAA_ALLOWED_HOSTS=127.0.0.1,localhost','-e','PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring']
        def start(smoke):
            docker(*common,image,'python','run.py','--headless','--host','0.0.0.0','--port','18346',*(['--smoke-profile'] if smoke else []))
            for i in range(150):
                if docker('inspect','--format','{{.State.Running}}',container)!='true':
                    raise RuntimeError('Docker process exited: '+docker('logs',container)[-3000:])
                try:
                    with httpx.Client(trust_env=False,timeout=2) as c:
                        if c.get(f'http://127.0.0.1:{port}/api/health').status_code==200:return
                except httpx.HTTPError:pass
                time.sleep(.2)
            raise RuntimeError('Docker readiness failed: '+docker('logs',container)[-3000:])
        start(True)
        env=dict(os.environ,BUAA_ACCEPTANCE_ADMIN='synthetic-remote-admin',NODE_PATH=os.environ.get('BUAA_NODE_MODULES',''))
        r=subprocess.run([shutil.which('node'),'scripts/remote_acceptance.cjs',f'http://127.0.0.1:{port}/',os.environ.get('BUAA_TEST_BROWSER',''),str(output/'docker-browser.json')],env=env,capture_output=True,text=True,timeout=240)
        assert r.returncode==0,r.stderr[-1500:];checks.append('docker-real-password-browser-ten-contracts')
        script="""from pathlib import Path
import json
from core.vault import encrypt
from core.td_license import container_installation_id
from server.app import COMMITMENT_VERSION
p=Path('/data');assert len(container_installation_id())==64
(p/'synthetic-vault-check').write_text(encrypt('synthetic-volume-secret'))
(p/'config.json').write_text(json.dumps({'disclaimer_accepted':True,'disclaimer_commitment_version':COMMITMENT_VERSION}))
(p/'config.json.td-private').mkdir(exist_ok=True)
(p/'config.json.td-private/synthetic-budget').write_text('no-real-account')
"""
        docker('exec',container,'python','-c',script)
        logs.append(docker('logs',container));docker('stop','--time','15',container);docker('rm',container)
        start(False)
        script="""from pathlib import Path
from core.vault import decrypt
from core.td_license import container_installation_id
p=Path('/data');assert len(container_installation_id())==64
assert decrypt((p/'synthetic-vault-check').read_text())=='synthetic-volume-secret'
assert (p/'config.json.td-private/synthetic-budget').read_text()=='no-real-account'
assert (p/'.td-device-id').stat().st_mode&0o777==0o600
"""
        docker('exec',container,'python','-c',script)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=5) as c:
            csrf=c.post('/api/session',json={'password':'synthetic-remote-admin'}).json()['csrf']
            assert c.get('/api/system/disclaimer').json()['accepted'] is True
            assert c.get('/api/accounts').json()['accounts']==[]
            assert c.post('/api/system/autostart',json={'enabled':True},headers={'X-BUAA-CSRF':csrf}).status_code==409
            first=c.get('/').text;second=c.get('/').text
            assert 'data-startup-enabled="true"' in first and 'data-startup-enabled="false"' in second
        logs.append(docker('logs',container));assert not any('BUAA_ACCEPTANCE_BLOCKED_NETWORK' in log for log in logs)
        checks+=['container-recreation-preserves-config-private-vault-td-data','new-process-first-document-once','host-autostart-write-denied','non-root-no-capabilities-zero-external-connect-attempts']
        result={'passed':True,'checks':checks,'real_school_writes':0,'blocked_non_loopback_attempts':0,'external_network':'CI-only Python audit forbids external app connections; browser blocks third-party resources','host_rebooted':False}
        (output/'container-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:
        result=subprocess.run(['docker','logs',container],capture_output=True,text=True,timeout=20)
        (output/'container-process.txt').write_text('\n'.join(logs)+result.stdout+result.stderr,encoding='utf-8')
        for a in [('rm','-f',container),('volume','rm',volume),('network','rm',network),('image','rm',image)]:
            subprocess.run(['docker',*a],capture_output=True,timeout=60)

if __name__=='__main__':main()
