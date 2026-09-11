"""
BUAA 课程独立签到助手 v1.2.0 - 原生独立应用入口
- 原生独立桌面窗口 (pywebview / Edge Chromium WebView2)
- Windows 任务栏系统托盘常驻 (pystray)
- 窗口右上角关闭拦截并最小化至托盘
- 单实例守护：重复打开桌面图标自动唤醒并恢复既有窗口
- 托盘右键极简菜单：仅包含"退出应用"，彻底终止所有服务
- 开机自启静默入托 (--autostart)
"""

import io
import os
import socket
import sys
import threading
import time
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
if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
    sys.stderr = SafeStream()

import uvicorn
import pystray
from PIL import Image, ImageDraw

APP_TITLE = "BUAA 课程签到 Pro v1.2.0"
DEFAULT_PORT = 18346

window = None
tray_icon = None
is_exiting = False


def check_and_wake_existing(port: int = DEFAULT_PORT) -> bool:
    """向已在运行的后台实例发送前台唤醒信标"""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/window/show",
            data=b"{}",
            headers={"Content-Type": "application/json", "User-Agent": "BUAA-Signin-Launcher"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.8) as resp:
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


class CustomTrayIcon(pystray.Icon):
    """自定义托盘图标，重写左键单击/双击事件直接呼出主窗口"""
    def __call__(self):
        restore_window()


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


def main():
    global window, tray_icon

    # 1. 单实例互斥检查：如果已有实例在运行，直接唤醒前台窗口并极速退出本进程
    if check_and_wake_existing(DEFAULT_PORT):
        print("BUAA 课程签到助手实例已在运行中，已成功唤醒主窗口。")
        sys.exit(0)

    # 2. 判断是否为开机自启模式
    start_hidden = "--autostart" in sys.argv or "--minimized" in sys.argv

    # 3. 启动后台 FastAPI 服务线程
    server_thread = threading.Thread(target=run_server, args=(DEFAULT_PORT,), daemon=True)
    server_thread.start()

    # 等待服务端口就绪
    wait_for_server(DEFAULT_PORT, timeout=3.5)

    # 4. 创建 Windows 任务栏系统托盘
    # 严格按照需求：右键菜单仅保留一个按钮——“退出应用”
    tray_img = get_tray_image()
    tray_menu = pystray.Menu(
        pystray.MenuItem("退出应用", lambda icon, item: exit_all())
    )
    tray_icon = CustomTrayIcon(
        name="BUAA-Signin",
        icon=tray_img,
        title="BUAA 课程独立签到助手 v1.2.0 (后台运行中)",
        menu=tray_menu,
    )
    tray_icon.run_detached()

    # 5. 启动原生桌面窗体 (pywebview)
    try:
        import webview
        url = f"http://127.0.0.1:{DEFAULT_PORT}"
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
            webbrowser.open(f"http://127.0.0.1:{DEFAULT_PORT}")
        while not is_exiting:
            time.sleep(1)

    # 退出清理
    exit_all()


if __name__ == "__main__":
    main()
