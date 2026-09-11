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

logger = logging.getLogger("buaa.autostart")

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_KEY = "BUAA-Signin"
MAC_PLIST_NAME = "com.buaa.signin.plist"


def get_mac_plist_path() -> pathlib.Path:
    """获取 macOS 专属 LaunchAgents 配置文件路径"""
    agents_dir = pathlib.Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / MAC_PLIST_NAME


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
    return False

