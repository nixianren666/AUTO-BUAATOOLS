"""Inspect archives and decompressed PyInstaller/PYZ members without printing secrets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile
import zipfile

PATTERNS = {
    "github_token": rb'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b',
    "private_key_body": rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}-----END (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',
    "jwt": rb'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b',
}

def main():
    import sys
    parser=argparse.ArgumentParser()
    parser.add_argument("paths",nargs="+");parser.add_argument("--report",required=True)
    parser.add_argument("--secrets-stdin",action="store_true")
    args=parser.parse_args()
    values=json.loads(sys.stdin.read()) if args.secrets_stdin else []
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError("Secret list required")
    seeds=[data for value in values if len(value)>=2 for data in (value.encode(),value.encode('utf-16le'))]
    findings=[];counts={"files":0,"archive_members":0,"carchive_members":0,"pyz_members":0,"bytes":0};assets=[]
    def scan(data,label):
        counts['bytes']+=len(data)
        kinds=[name for name,pattern in PATTERNS.items() if re.search(pattern,data)]
        if any(seed in data for seed in seeds):kinds.append("known_private_value")
        if kinds:findings.append({"member":label,"kinds":kinds})
    def inspect(data,label,depth=0):
        scan(data,label)
        name=Path(label.rsplit('!',1)[-1]).name
        if name.lower() in {'td_issuer.py','td_issuer.spec','test_td_issuer.py','td-license-generator.exe','signing-key.dpapi','issued.sqlite'} or name.lower().startswith('td_issuer.'):
            findings.append({'member':label,'kinds':['maintainer_only_distribution_file']})
        if name in ('config.json','.vault-key','operations.sqlite','.td-device-id') or name.endswith(('.log','.sqlite')):
            findings.append({"member":label,"kinds":["private_runtime_file"]})
        if depth>5:raise RuntimeError("Archive nesting limit exceeded")
        if data.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():continue
                    counts['archive_members']+=1
                    inspect(archive.read(entry),label+'!'+entry.filename,depth+1)
        if name=='BUAA-Signin' or (name.endswith('.exe') and ('portable' in name or name in ('BUAA-Signin.exe','TD-License-Generator.exe'))):
            from PyInstaller.archive.readers import CArchiveReader
            with tempfile.TemporaryDirectory(prefix='buaa-payload-scan-') as directory:
                temporary=Path(directory)/'payload';temporary.write_bytes(data)
                reader=CArchiveReader(str(temporary))
                for member,entry in reader.toc.items():
                    counts['carchive_members']+=1
                    inspect(reader.extract(member),label+'!'+member,depth+1)
                    if entry[-1]=='z':
                        pyz=reader.open_embedded_archive(member)
                        for module in pyz.toc:
                            if module=='tools.td_issuer' or module.endswith('.td_issuer'):
                                findings.append({'member':label+'!'+module,'kinds':['maintainer_only_distribution_module']})
                            raw=pyz.extract(module,raw=True)
                            if raw is not None:
                                counts['pyz_members']+=1;scan(raw,label+'!'+member+'!'+module)
    def file(path):
        data=path.read_bytes();counts['files']+=1
        assets.append({"name":path.name,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
        if path.name.endswith('.tar.gz'):
            scan(data,path.name)
            with tarfile.open(path,'r:gz') as archive:
                for entry in archive:
                    if entry.isfile():
                        counts['archive_members']+=1;inspect(archive.extractfile(entry).read(),path.name+'!'+entry.name)
        elif path.suffix=='.dmg':
            raise RuntimeError("DMG must be mounted and its application tree verified on macOS; scan the matching ZIP payload here")
        else:inspect(data,path.name)
    for value in args.paths:
        path=Path(value).resolve()
        if path.is_dir():
            for child in sorted(path.rglob('*')):
                if child.is_file():file(child)
        else:file(path)
    result={"passed":not findings,"findings":findings,"counts":counts,"assets":assets,"known_values_supplied":len(values),"limitations":["No OCR of image content","Setup compressed payload requires installer acceptance and matching portable hash","DMG requires native mount and tree comparison; matching ZIP inspected separately"]}
    Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({"passed":result['passed'],"findings":len(findings),"counts":counts}))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
