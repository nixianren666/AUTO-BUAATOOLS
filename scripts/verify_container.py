"""Real Docker browser/volume checks, only on disposable Linux CI runners."""
import argparse,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
import httpx

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or not sys.platform.startswith('linux'):
        raise RuntimeError('Container acceptance only runs on disposable Linux CI')
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',required=True);args=parser.parse_args()
    output=Path(args.report_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    suffix=str(os.getpid());image='buaa-acceptance:'+suffix;container='buaa-acceptance-'+suffix;volume=container+'-data';network=container+'-net'
    def docker(*a,**kw):return subprocess.run(['docker',*a],check=True,capture_output=True,text=True,timeout=kw.pop('timeout',90),**kw).stdout.strip()
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    checks=[]
    try:
        docker('build','-t',image,'.',timeout=420);docker('volume','create',volume);docker('network','create','--internal',network)
        common=['run','-d','--name',container,'--network',network,'--cap-drop','ALL','--security-opt','no-new-privileges',
                '-p',f'127.0.0.1:{port}:18346','-v',volume+':/data','-e','BUAA_ADMIN_PASSWORD=synthetic-remote-admin','-e','BUAA_ALLOWED_HOSTS=127.0.0.1,localhost','-e','PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring']
        def start(smoke):
            docker(*common,image,'python','run.py','--headless','--host','0.0.0.0','--port','18346',*(['--smoke-profile'] if smoke else []))
            for i in range(150):
                try:
                    with httpx.Client(trust_env=False,timeout=2) as c:
                        if c.get(f'http://127.0.0.1:{port}/api/health').status_code==200:return
                except httpx.HTTPError:pass
                time.sleep(.2)
            raise RuntimeError('Docker readiness failed')
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
        docker('stop','--time','15',container);docker('rm',container)
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
        checks+=['container-recreation-preserves-config-private-vault-td-data','new-process-first-document-once','host-autostart-write-denied','non-root-no-capabilities-internal-network']
        result={'passed':True,'checks':checks,'real_school_writes':0,'external_network':'internal Docker network, no external routes','host_rebooted':False}
        (output/'container-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:
        for a in [('rm','-f',container),('volume','rm',volume),('network','rm',network),('image','rm',image)]:
            subprocess.run(['docker',*a],capture_output=True,timeout=60)

if __name__=='__main__':main()
