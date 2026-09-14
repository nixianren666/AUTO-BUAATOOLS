"""
BUAA 课程独立签到助手 v1.2.2 - 原生独立应用入口
- 原生独立桌面窗口 (pywebview / Edge Chromium WebView2)
- Windows 任务栏系统托盘常驻 (pystray)
- 窗口右上角关闭拦截并最小化至托盘
- 单实例守护：重复打开桌面图标自动唤醒并恢复既有窗口
- 托盘右键极简菜单：仅包含"退出应用"，彻底终止所有服务
- 开机自启静默入托 (--autostart)
"""

import atexit
import io
import os
import socket
import sys
import threading
import time
from typing import Any, Optional, Union, List, Dict
import webbrowser

# 针对 Windows GUI / PyInstaller --windowed 无控制台模式，防止 uvicorn / isatty 报错
class SafeStream(io.StringIO):
    def isatty(self):
        return False
    def write(self, s):
        pass
    def flush(self):
        pass

if sys.stdout is None or not hasattr(sys.stdout, "isatty"):
    sys.stdout = SafeStream()
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
    sys.stderr = SafeStream()
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import uvicorn

# 延迟/按需安全导入 pystray（杜绝在无 GUI / Docker / Linux 服务器环境下因缺少 Xlib/gi 导致启动即崩）
try:
    import pystray
except Exception:
    pystray = None

from PIL import Image, ImageDraw

APP_TITLE = "BUAA 课程签到 Pro v1.2.5"
DEFAULT_PORT = 18346

window = None
tray_icon = None
is_exiting = False
_single_instance_mutex = None
_open_lock_files = []


def acquire_single_instance(port_or_name: Any = DEFAULT_PORT) -> bool:
    """
    确保全系统绝对单实例运行：
    1. Windows 采用 Win32 Named Mutex (内核级互斥体)
    2. Unix (macOS / Linux) 采用专属文件锁 (fcntl.flock)
    3. 备用检查采用本地专用互斥端口占用检测
    若已有实例在运行，则恢复并置顶已有主窗口，并返回 False（应立即退出）
    """
    global _single_instance_mutex, _open_lock_files

    already_running = False

    if isinstance(port_or_name, int):
        port = port_or_name
        mutex_tag = f"PORT_{port}"
    elif isinstance(port_or_name, str) and port_or_name.isdigit():
        port = int(port_or_name)
        mutex_tag = f"PORT_{port}"
    else:
        port = DEFAULT_PORT
        mutex_tag = str(port_or_name).replace("\\", "_")

    if sys.platform == "win32":
        try:
            import ctypes
            MUTEX_NAME = f"Global\\BUAA_SIGNIN_PRO_SINGLE_INSTANCE_v122_{mutex_tag}" if mutex_tag != f"PORT_{DEFAULT_PORT}" else "Global\\BUAA_SIGNIN_PRO_SINGLE_INSTANCE_v122"
            h_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
            last_err = ctypes.windll.kernel32.GetLastError()
            if last_err == 183:  # ERROR_ALREADY_EXISTS
                already_running = True
                if h_mutex:
                    ctypes.windll.kernel32.CloseHandle(h_mutex)
            else:
                _single_instance_mutex = h_mutex
        except Exception:
            pass
    else:
        try:
            import fcntl
            import pathlib
            lock_name = f".buaa_signin_v122_{mutex_tag}.lock" if mutex_tag != f"PORT_{DEFAULT_PORT}" else ".buaa_signin_v122.lock"
            lock_path = pathlib.Path.home() / lock_name
            f = open(lock_path, "a+")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _open_lock_files.append(f)
        except (IOError, OSError):
            already_running = True
        except Exception:
            pass

    # 备用检查：测试本地端口是否已被前一个实例占用（仅针对有效网络端口）
    if not already_running and isinstance(port, int) and port > 0:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_sock:
                test_sock.settimeout(0.3)
                if test_sock.connect_ex(("127.0.0.1", port)) == 0:
                    already_running = True
        except Exception:
            pass

    if already_running:
        # 激活并前台化既有窗口
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

        # 发送本地 HTTP 唤醒信标（显式禁用系统代理，直连 127.0.0.1）
        check_and_wake_existing(port)
        return False

    return True


def release_single_instance(lock: Any = None) -> None:
    """释放单实例互斥锁与文件句柄"""
    global _single_instance_mutex, _open_lock_files
    if sys.platform == "win32":
        if _single_instance_mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(_single_instance_mutex)
            except Exception:
                pass
            _single_instance_mutex = None
    for f in _open_lock_files:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()
        except Exception:
            pass
    _open_lock_files = []
    if lock is not None:
        if hasattr(lock, "fileno"):
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()
            except Exception:
                pass
        elif sys.platform == "win32" and isinstance(lock, int):
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(lock)
            except Exception:
                pass


# 注册退出时的互斥锁自动清理
atexit.register(release_single_instance)


def check_and_wake_existing(port: int = DEFAULT_PORT) -> bool:
    """向已在运行的后台实例发送前台唤醒信标（直连本地回环，绕过任何系统代理）"""
    try:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/window/show",
            data=b"{}",
            headers={"Content-Type": "application/json", "User-Agent": "BUAA-Signin-Launcher"},
            method="POST",
        )
        with opener.open(req, timeout=0.8) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass
    return False


def wait_for_server(port: int = DEFAULT_PORT, timeout: float = 3.5) -> bool:
    """等待本地 FastAPI 后台服务端口就绪"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return True
        except Exception:
            pass
        time.sleep(0.08)
    return False


def create_tray_image(size: int = 64) -> Image.Image:
    """生成北航航天蓝专属精致托盘图标"""
    img = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆形外框与发光天蓝轮廓
    draw.ellipse((2, 2, size - 3, size - 3), fill=(10, 88, 202), outline=(56, 189, 248), width=3)
    # 航天箭矢与罗盘徽标
    points = [
        (size // 2, int(size * 0.20)),
        (int(size * 0.78), int(size * 0.76)),
        (size // 2, int(size * 0.60)),
        (int(size * 0.22), int(size * 0.76)),
    ]
    draw.polygon(points, fill=(255, 255, 255))
    return img


def get_tray_image() -> Image.Image:
    """优先获取打包携带的 tray_icon.png，若不存在则回退至动态生成"""
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
    icon_file = os.path.join(base_dir, "tray_icon.png")
    if os.path.isfile(icon_file):
        try:
            return Image.open(icon_file)
        except Exception:
            pass
    return create_tray_image(64)


def restore_window():
    """将应用窗口恢复显示并激活置顶"""
    global window
    if window:
        try:
            window.show()
            window.restore()
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, APP_TITLE)
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE = 9
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass


def exit_all():
    """彻底终止所有后台服务并退出程序"""
    global is_exiting, tray_icon, window
    if is_exiting:
        return
    is_exiting = True
    try:
        if tray_icon:
            tray_icon.stop()
    except Exception:
        pass
    try:
        if window:
            window.destroy()
    except Exception:
        pass
    # 彻底退出进程
    os._exit(0)


if pystray is not None:
    class CustomTrayIcon(pystray.Icon):
        """自定义托盘图标，重写左键单击/双击事件直接呼出主窗口"""
        def __call__(self):
            restore_window()
else:
    class CustomTrayIcon:
        """无 GUI / 缺少托盘后端时的 Dummy Tray 占位类"""
        def __init__(self, *args, **kwargs):
            pass
        def run_detached(self):
            pass
        def stop(self):
            pass


def setup_tray() -> Optional[Any]:
    """
    初始化系统托盘：
    - Windows: 支持左键单击唤醒与右键菜单
    - macOS: 绑定 NSMenu 拦截时显式提供【显示主界面】(加粗默认项) 与【退出应用】，杜绝隐藏后无法唤醒的死锁
    - Headless / 缺失 GUI 驱动: 优雅降级返回 None / Dummy，绝不崩塌
    """
    global pystray
    if pystray is None:
        try:
            import pystray as _pystray
            pystray = _pystray
        except Exception as e:
            return None

    try:
        tray_img = get_tray_image()
        tray_menu = pystray.Menu(
            pystray.MenuItem("显示主界面", lambda icon, item: restore_window(), default=True),
            pystray.MenuItem("退出应用", lambda icon, item: exit_all()),
        )
        icon = CustomTrayIcon(
            name="BUAA-Signin",
            icon=tray_img,
            title="BUAA 课程独立签到助手 v1.2.2 (后台运行中)",
            menu=tray_menu,
        )
        icon.run_detached()
        return icon
    except Exception as te:
        print(f"系统托盘创建跳过: {te}")
        return None


def on_window_closing():
    """拦截窗口右上角 X 点击，取消彻底关闭，平滑隐藏至右下角系统托盘"""
    global window, is_exiting
    if is_exiting:
        return True  # 允许销毁
    if window:
        try:
            window.hide()
        except Exception:
            pass
    return False  # 取消关闭事件


def run_server(port: int):
    """在后台独立线程运行 uvicorn 服务器"""
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from server.app import app, set_window_controller
    set_window_controller(show_cb=restore_window, exit_cb=exit_all)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.run()


def parse_arguments():
    import argparse
    parser = argparse.ArgumentParser(description="AUTO-BUAA 课程独立签到助手 Pro v1.2.2")
    parser.add_argument("--headless", action="store_true", help="无头模式：纯 Web 服务运行（适合 Linux 服务器、Docker 容器与后台驻留）")
    parser.add_argument("--host", type=str, default=None, help="监听主机地址（桌面模式默认 127.0.0.1，无头模式默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口号（默认 {DEFAULT_PORT}）")
    parser.add_argument("--autostart", action="store_true", help="开机自启静默启动模式")
    parser.add_argument("--minimized", action="store_true", help="最小化启动模式")
    return parser.parse_args()


def main():
    global window, tray_icon

    args = parse_arguments()

    # 自动识别环境：判定是否进入 Headless 纯 Web 服务模式
    is_linux = sys.platform.startswith("linux")
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    is_docker = os.path.exists("/.dockerenv") or bool(os.environ.get("DOCKER_CONTAINER"))
    env_headless = os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")

    is_headless = args.headless or env_headless or is_docker or (is_linux and not has_display)
    port = args.port

    # 1. 核心单实例互斥检查（提升至所有服务与窗口启动前执行，确保全平台与无头服务器/Docker 防多开）
    if not acquire_single_instance(port):
        if is_headless:
            print(f"[提示] BUAA 课程签到助手后台服务已在运行中 (监听端口: {port})，无需重复启动。")
        else:
            print("BUAA 课程签到助手实例已在运行中，已成功唤醒主窗口。")
        sys.exit(0)

    # 2. 如果是无头服务模式（Linux 服务器 / Docker / 终端守护），直接启动主线程 Web 服务
    if is_headless:
        host = args.host or "0.0.0.0"
        print("=" * 66)
        print("  [*] AUTO-BUAA 课程独立签到助手 Pro (Linux / Headless Web 服务模式)")
        print("=" * 66)
        print(f"  版本:     v1.2.2")
        print(f"  监听地址: http://{host}:{port}")
        print(f"  本地访问: http://127.0.0.1:{port}")
        print(f"  网络访问: http://<你的服务器IP>:{port}")
        print("=" * 66)
        print("  [提示] 按 Ctrl+C 可安全终止服务\n")

        sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
        from server.app import app
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
        )
        return

    # 3. 桌面模式：判断是否为开机自启模式
    start_hidden = args.autostart or args.minimized

    # 4. 启动后台 FastAPI 服务线程
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()

    # 等待服务端口就绪
    wait_for_server(port, timeout=3.5)

    # 5. 创建桌面任务栏系统托盘（包含“显示主界面”与“退出应用”，彻底消除 macOS 死锁与无头报错）
    tray_icon = setup_tray()

    # 6. 启动原生桌面窗体 (pywebview)
    try:
        import webview
        url = f"http://127.0.0.1:{port}"
        window = webview.create_window(
            title=APP_TITLE,
            url=url,
            width=1280,
            height=840,
            min_size=(960, 620),
            hidden=start_hidden,
            confirm_close=False,
        )
        window.events.closing += on_window_closing

        # 启动主 GUI 事件循环（阻塞直到应用退出）
        webview.start()
    except Exception as e:
        # 回退模式（如无图形渲染驱动）：使用默认浏览器打开
        if not start_hidden:
            webbrowser.open(f"http://127.0.0.1:{port}")
        while not is_exiting:
            time.sleep(1)

    # 退出清理
    exit_all()


if __name__ == "__main__":
    main()
