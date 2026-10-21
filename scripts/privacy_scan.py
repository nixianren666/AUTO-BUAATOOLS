"""Scan public checkout and every reachable Git object. Never print secret values."""
import argparse
import hashlib
import json
import marshal
import os
from pathlib import Path
import re
import subprocess
import sys

PATTERNS={
 "github_token":rb'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b',
 "private_key":rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----',
 "jwt":rb'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b',
}

def forbidden_distribution_path(name):
    leaf=Path(name).name.lower()
    return leaf in {"td_issuer.py", "td_issuer.spec", "test_td_issuer.py", "td-license-generator.exe", "signing-key.dpapi", "issued.sqlite"} or leaf.startswith("td_issuer.")

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--repo",required=True);parser.add_argument("--report",required=True);parser.add_argument("--git",default="git");parser.add_argument("--secrets-stdin",action="store_true")
    args=parser.parse_args();root=Path(args.repo).resolve()
    values=json.loads(sys.stdin.read()) if args.secrets_stdin else []
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError("Secret input must be a list of strings")
    seeds=[encoded for value in values if len(value)>=2 for encoded in (value.encode(),value.encode('utf-16le'))]
    findings=[];counts={"git_objects":0,"working_files":0,"embedded_members":0,"bytes":0}
    def scan(data,label):
        counts["bytes"]+=len(data)
        kinds=[kind for kind,pattern in PATTERNS.items() if re.search(pattern,data)]
        if any(seed in data for seed in seeds):kinds.append("known_private_value")
        if kinds:findings.append({"object":label,"kinds":kinds})
    def git(*argv):return subprocess.run([args.git,*argv],cwd=root,check=True,capture_output=True).stdout
    objects=git("rev-list","--objects","--all").decode().splitlines()
    forbidden_objects=[line.split(' ',1)[1] for line in objects if ' ' in line and forbidden_distribution_path(line.split(' ',1)[1])]
    proc=subprocess.Popen([args.git,"cat-file","--batch"],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for line in objects:
            oid=line.split(' ',1)[0]
            proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
            header=proc.stdout.readline().decode().strip().split()
            if len(header)!=3:raise RuntimeError("Git object cannot be read")
            size=int(header[2]);data=proc.stdout.read(size)
            if len(data)!=size or proc.stdout.read(1)!=b'\n':raise RuntimeError("Git object truncated")
            counts["git_objects"]+=1;scan(data,"git:"+oid)
    finally:
        proc.stdin.close();proc.wait(timeout=10)
    files=git("ls-files","--cached","--others","--exclude-standard","-z").decode().split('\0')
    forbidden=list(forbidden_objects)
    for name in sorted(set(files)):
        if not name:continue
        path=root/name
        if not path.is_file():continue
        if name=="config.json" or name.endswith((".sqlite",".log")) or '.vault-key' in name or '__pycache__' in name or forbidden_distribution_path(name):
            forbidden.append(name)
        counts["working_files"]+=1;scan(path.read_bytes(),"working:"+name)
    result={"passed":not findings and not forbidden,"head_commit":git("rev-parse","HEAD").decode().strip(),"findings":findings,"forbidden_public_files":forbidden,"counts":counts,"known_values_supplied":len(values),"limitations":["No OCR of historical images","Compiled/archive inspection is a separate gate","Only objects reachable from local Git refs; deleted/unreachable server objects excluded"]}
    Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"passed":result['passed'],"findings":len(findings),"forbidden_files":len(forbidden),"counts":counts}))
    return 0 if result['passed'] else 1

if __name__=="__main__":raise SystemExit(main())
