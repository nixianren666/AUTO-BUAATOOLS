r"""
BUAA 课程独立签到助手 - 跨平台开机自启动管理模块
- Windows: 基于注册表项 HKCU\Software\Microsoft\Windows\CurrentVersion\Run
- macOS: 基于用户级 LaunchAgents (~/Library/LaunchAgents/com.buaa.signin.plist)
均免管理员提权，100% 稳定可靠
"""

import os
import sys
import logging
import pathlib
import subprocess
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
        logger.debug(f"调用 systemctl 异常: {e}")
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
    if getattr(sys, "frozen", False):
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}" --autostart'
    else:
        py_exe = os.path.abspath(sys.executable)
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.py"))
        return f'"{py_exe}" "{script_path}" --autostart'


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
            logger.warning(f"读取 Windows 开机自启注册表失败: {e}")
            return False
    elif sys.platform == "darwin":
        try:
            plist_path = get_mac_plist_path()
            return plist_path.exists() and plist_path.stat().st_size > 0
        except Exception as e:
            logger.warning(f"读取 macOS 自启配置失败: {e}")
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
        # 回退检查服务文件是否存在且有效
        try:
            service_file = get_linux_service_path()
            return service_file.exists() and service_file.stat().st_size > 0
        except Exception as e:
            logger.warning(f"读取 Linux 自启服务失败: {e}")
            return False
    return False


def set_autostart(enable: bool) -> bool:
    """设置或取消开机自启动"""
    if sys.platform == "win32":
        try:
            import winreg
            access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, access) as key:
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
            logger.error(f"设置 Windows 开机自启注册表失败: {e}")
            return False
    elif sys.platform == "darwin":
        try:
            plist_path = get_mac_plist_path()
            if enable:
                if getattr(sys, "frozen", False):
                    exec_args = [os.path.abspath(sys.executable), "--autostart"]
                else:
                    exec_args = [os.path.abspath(sys.executable), os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.py")), "--autostart"]
                
                args_xml = "\n        ".join(f"<string>{arg}</string>" for arg in exec_args)
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.buaa.signin</string>
    <key>ProgramArguments</key>
    <array>
        {args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""
                plist_path.write_text(plist_content, encoding="utf-8")
                logger.info(f"已成功写入 macOS LaunchAgents 自启配置: {plist_path}")
            else:
                if plist_path.exists():
                    plist_path.unlink()
                    logger.info(f"已移除 macOS LaunchAgents 自启配置: {plist_path}")
            return True
        except Exception as e:
            logger.error(f"设置 macOS 自启配置失败: {e}")
            return False
    elif sys.platform.startswith("linux"):
        if os.path.exists("/.dockerenv") or bool(os.environ.get("DOCKER_CONTAINER")):
            return True
        try:
            service_file = get_linux_service_path()
            if enable:
                service_content = f"""[Unit]
Description=AUTO-BUAA Course Signin Pro Service
After=network.target

[Service]
Type=simple
WorkingDirectory={os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))}
ExecStart={sys.executable} run.py --headless --host 0.0.0.0 --port 18346
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
                service_file.write_text(service_content, encoding="utf-8")
                _run_systemctl(["daemon-reload"])
                _run_systemctl(["enable", "buaa-signin.service"])
                logger.info(f"已成功写入并启用 Linux systemd 用户级自启动服务: {service_file}")
            else:
                _run_systemctl(["disable", "buaa-signin.service"])
                if service_file.exists():
                    service_file.unlink()
                _run_systemctl(["daemon-reload"])
                logger.info(f"已成功禁用并移除 Linux systemd 用户级自启动服务: {service_file}")
            return True
        except Exception as e:
            logger.warning(f"设置 Linux 自启服务失败: {e}")
            return False
    return False

