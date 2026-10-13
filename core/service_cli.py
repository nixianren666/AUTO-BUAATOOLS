"""Manage the same user service as the GUI; no system/root unit or public bind."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from core.autostart import set_autostart, get_autostart_status
from core.version import VERSION

def command(action):
    if sys.platform.startswith("linux"):
        verb = {"start":"start", "stop":"stop", "restart":"restart", "status":"status"}[action]
        return ["systemctl", "--user", verb, "buaa-signin.service"]
    if sys.platform == "darwin":
        label = f"gui/{os.getuid()}/com.buaa.signin"
        if action == "status":
            return ["launchctl", "print", label]
        if action == "stop":
            return ["launchctl", "kill", "SIGTERM", label]
        return ["launchctl", "kickstart", "-k", label]
    raise RuntimeError("此命令仅用于 Linux/macOS 用户服务")

def main():
    parser=argparse.ArgumentParser(description="AUTO-BUAA v"+VERSION+" 用户服务（127.0.0.1）")
    parser.add_argument("action",choices=["install","start","stop","restart","status","uninstall","update","logs"])
    args=parser.parse_args()
    if hasattr(os,"geteuid") and os.geteuid()==0:
        raise RuntimeError("请以实际使用账号运行，不要 sudo/root 安装用户服务")
    if args.action == "install":
        if not set_autostart(True,headless=True):
            raise RuntimeError("系统未确认用户自启动服务已启用")
        if sys.platform.startswith("linux"):
            subprocess.run(command("start"),check=True)
    elif args.action == "uninstall":
        if sys.platform.startswith("linux"):
            subprocess.run(command("stop"),check=True)
        if not set_autostart(False):
            raise RuntimeError("服务移除失败，配置仍保留")
    elif args.action == "update":
        # Fetch and switch only the fixed, approved bugfix release; never pull main.
        root=Path(__file__).resolve().parent.parent
        def git(*argv):
            return subprocess.run(["git",*argv],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
        if git("status","--porcelain","--untracked-files=no"):
            raise RuntimeError("源码有本地修改，更新已停止，避免覆盖用户改动")
        remote=git("remote","get-url","origin").removesuffix(".git").rstrip("/")
        if remote not in ("https://github.com/nixianren666/AUTO-BUAATOOLS","git@github.com:nixianren666/AUTO-BUAATOOLS"):
            raise RuntimeError("更新来源不是本项目官方仓库")
        tag="v"+VERSION
        old=git("rev-parse","HEAD")
        git("fetch","origin","tag",tag)
        target=git("rev-parse",tag+"^{commit}")
        if old==target:
            print("已经是指定版本 "+tag);return
        subprocess.run(command("stop"),check=True)
        try:
            git("checkout","--detach",target)
            subprocess.run([sys.executable,"-m","pip","install","-r",str(root/"requirements.txt")],check=True)
            subprocess.run(command("start"),check=True)
        except BaseException:
            git("checkout","--detach",old)
            subprocess.run(command("start"),check=True)
            raise
    elif args.action == "logs":
        if sys.platform.startswith("linux"):
            subprocess.run(["journalctl","--user","-u","buaa-signin.service","-f","-n","50"],check=True)
        else:
            print("本地运行日志请查看软件界面的分账号日志；服务状态使用 status。")
    else:
        subprocess.run(command(args.action),check=True)

if __name__=="__main__":
    main()
