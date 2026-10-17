r"""
BUAA 课程独立签到助手 - 跨平台开机自启动管理模块
- Windows: 基于注册表项 HKCU\Software\Microsoft\Windows\CurrentVersion\Run
- macOS: 基于用户级 LaunchAgents (~/Library/LaunchAgents/com.buaa.signin.plist)
用户级自启动；以系统服务状态和命令返回结果为准
"""

import os
import sys
import logging
import pathlib
import subprocess
import plistlib
import json
from typing import List, Optional

logger = logging.getLogger("buaa.autostart")


def _run_systemctl(args: List[str]) -> bool:
    """在 Linux 下安全执行 systemctl --user 命令并记录日志"""
    try:
        res = subprocess.run(
            ["systemctl", "--user"] + args,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return True
        else:
            logger.debug(f"systemctl --user {' '.join(args)} 返回码非0: {res.stderr.strip() if res.stderr else res.stdout.strip()}")
            return False
    except Exception as e:
        logger.debug(f"调用 systemctl 异常: {type(e).__name__}")
        return False

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_KEY = "BUAA-Signin"
MAC_PLIST_NAME = "com.buaa.signin.plist"


def get_mac_plist_path() -> pathlib.Path:
    """获取 macOS 专属 LaunchAgents 配置文件路径"""
    agents_dir = pathlib.Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / MAC_PLIST_NAME


def get_linux_service_path() -> pathlib.Path:
    """获取 Linux 专属 systemd user service 路径"""
    service_dir = pathlib.Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    return service_dir / "buaa-signin.service"


def get_executable_command() -> str:
    """获取启动命令，编译环境下为二进制绝对路径，源码环境下为 python + run.py"""
    from core.profile import resolve_config_path
    args = [os.path.abspath(sys.executable)]
    if not getattr(sys, "frozen", False):
        args.append(str(pathlib.Path(__file__).resolve().parent.parent / "run.py"))
    args += ["--autostart", "--config", str(resolve_config_path())]
    return subprocess.list2cmdline(args)


def get_autostart_status() -> bool:
    """查询当前系统是否已配置开机自启动"""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, REG_APP_KEY)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"读取 Windows 开机自启注册表失败: {type(e).__name__}")
            return False
    elif sys.platform == "darwin":
        try:
            plist_path = get_mac_plist_path()
            result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.buaa.signin"], capture_output=True, timeout=5)
            return result.returncode == 0 and plist_path.exists()
        except Exception as e:
            logger.warning(f"读取 macOS 自启配置失败: {type(e).__name__}")
            return False
    elif sys.platform.startswith("linux"):
        if os.path.exists("/.dockerenv") or bool(os.environ.get("DOCKER_CONTAINER")):
            return False
        # 优先通过 systemctl --user 判定服务是否真正启用
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-enabled", "buaa-signin.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and "enabled" in res.stdout.strip().lower():
                return True
        except Exception:
            pass
        return False
    return False


def set_autostart(enable: bool, headless: bool = False) -> bool:
    """设置或取消开机自启动"""
    if sys.platform == "win32":
        try:
            import winreg
            access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            # Fresh Windows profiles need not have a Run key yet. Disabling an
            # absent entry is already complete and must not create that key.
            if enable:
                key_handle = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, access)
            else:
                try:
                    key_handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, access)
                except FileNotFoundError:
                    return True
            with key_handle as key:
                if enable:
                    cmd = get_executable_command()
                    winreg.SetValueEx(key, REG_APP_KEY, 0, winreg.REG_SZ, cmd)
                    logger.info(f"已成功写入 Windows 开机自启注册表: {cmd}")
                else:
                    try:
                        winreg.DeleteValue(key, REG_APP_KEY)
                        logger.info("已成功移除 Windows 开机自启注册表")
                    except FileNotFoundError:
                        pass
            return True
        except Exception as e:
            logger.error(f"设置 Windows 开机自启注册表失败: {type(e).__name__}")
            return False
    elif sys.platform == "darwin":
        try:
            plist_path = get_mac_plist_path()
            label = f"gui/{os.getuid()}/com.buaa.signin"
            if enable:
                if getattr(sys, "frozen", False):
                    args = [os.path.abspath(sys.executable), "--autostart"]
                else:
                    args = [os.path.abspath(sys.executable), str(pathlib.Path(__file__).resolve().parent.parent/"run.py"), "--autostart"]
                if headless:
                    args += ["--headless", "--host", "127.0.0.1"]
                payload = {"Label": "com.buaa.signin", "ProgramArguments": args, "RunAtLoad": True, "ProcessType": "Background" if headless else "Interactive"}
                from core.profile import resolve_config_path
                payload["EnvironmentVariables"] = {"BUAA_CONFIG_FILE":str(resolve_config_path())}
                plist_path.write_bytes(plistlib.dumps(payload))
                os.chmod(plist_path, 0o600)
                already = subprocess.run(["launchctl", "print", label], capture_output=True, timeout=5).returncode == 0
                if already:
                    stopped = subprocess.run(["launchctl", "bootout", label], capture_output=True, timeout=5)
                    if stopped.returncode != 0:
                        return False
                result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], capture_output=True, timeout=5)
                return result.returncode == 0 and get_autostart_status()
            loaded = subprocess.run(["launchctl", "print", label], capture_output=True, timeout=5).returncode == 0
            if loaded and subprocess.run(["launchctl", "bootout", label], capture_output=True, timeout=5).returncode != 0:
                return False
            if plist_path.exists():
                plist_path.unlink()
            return not get_autostart_status()
        except Exception as exc:
            logger.warning("macOS 自启动操作失败: %s", type(exc).__name__)
            return False
    elif sys.platform.startswith("linux"):
        if os.path.exists("/.dockerenv") or bool(os.environ.get("DOCKER_CONTAINER")):
            return False
        try:
            service_file = get_linux_service_path()
            def quote(value):
                text = str(value)
                if "\n" in text or "\r" in text:
                    raise ValueError("无效启动路径")
                return json.dumps(text.replace("%", "%%"), ensure_ascii=False)
            if enable:
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command.append(str(pathlib.Path(__file__).resolve().parent.parent/"run.py"))
                command += ["--autostart"]
                if headless:
                    command += ["--headless", "--host", "127.0.0.1"]
                # Headless machines are detected by the launcher; desktop users keep a GUI.
                from core.profile import resolve_config_path
                content = "[Unit]\nDescription=AUTO-BUAA user service\nAfter=network.target\n\n[Service]\nType=simple\nEnvironment="+quote("BUAA_CONFIG_FILE="+str(resolve_config_path()))+"\nExecStart=" + " ".join(quote(arg) for arg in command) + "\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
                service_file.write_text(content, encoding="utf-8")
                os.chmod(service_file, 0o600)
                return bool(_run_systemctl(["daemon-reload"]) and _run_systemctl(["enable", "buaa-signin.service"]) and get_autostart_status())
            if not _run_systemctl(["disable", "buaa-signin.service"]):
                return False
            if service_file.exists():
                service_file.unlink()
            return bool(_run_systemctl(["daemon-reload"]) and not get_autostart_status())
        except Exception as exc:
            logger.warning("Linux 自启动操作失败: %s", type(exc).__name__)
            return False
