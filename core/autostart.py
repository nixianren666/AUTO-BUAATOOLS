r"""
BUAA 课程独立签到助手 - Windows 开机自启动管理模块
基于 Windows 官方标准用户级注册表项 (HKCU\Software\Microsoft\Windows\CurrentVersion\Run)
无须管理员 UAC 提权，100% 稳定可靠
"""

import os
import sys
import logging

logger = logging.getLogger("buaa.autostart")

REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_KEY = "BUAA-Signin"


def get_executable_command() -> str:
    """获取启动命令，编译环境下为 exe 绝对路径，源码环境下为 python + run.py"""
    if getattr(sys, "frozen", False):
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}" --autostart'
    else:
        # 开发测试环境
        py_exe = os.path.abspath(sys.executable)
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "run.py"))
        return f'"{py_exe}" "{script_path}" --autostart'


def get_autostart_status() -> bool:
    """查询 Windows 注册表中是否已配置开机自启动"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REG_APP_KEY)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"读取开机自启注册表失败: {e}")
        return False


def set_autostart(enable: bool) -> bool:
    """设置或取消 Windows 开机自启动"""
    if sys.platform != "win32":
        return False
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
        logger.error(f"设置开机自启注册表失败: {e}")
        return False
