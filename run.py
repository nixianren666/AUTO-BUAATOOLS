# -*- coding: utf-8 -*-
"""
BUAA 课程独立签到助手 v1.4.8 - 原生独立应用入口
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

from core.version import VERSION
APP_TITLE = "BUAA 课程签到 Pro v" + VERSION
DEFAULT_PORT = 18346

window = None
tray_icon = None
is_exiting = False
_exit_started = False
_single_instance_mutex = None
_open_lock_files = []


def _instance_identity(port_or_name):
    import hashlib
    from core.profile import resolve_config_path
    profile = resolve_config_path().resolve()
    identity = os.path.normcase(str(profile))
    if isinstance(port_or_name, str) and not port_or_name.isdigit():
        identity += ":" + port_or_name
    digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
    return profile, digest

def acquire_single_instance(port_or_name=DEFAULT_PORT):
    """Fail closed; one configuration has one instance regardless of port."""
    global _single_instance_mutex, _open_lock_files
    import json
    import pathlib
    if isinstance(port_or_name, bool):
        raise ValueError("无效监听端口")
    port = port_or_name if isinstance(port_or_name, int) else int(port_or_name) if str(port_or_name).isdigit() else DEFAULT_PORT
    if not 1 <= port <= 65535:
        raise ValueError("监听端口必须在1至65535之间")
    profile, digest = _instance_identity(port_or_name)
    profile.parent.mkdir(parents=True, exist_ok=True)
    metadata = profile.parent/(".instance-"+digest+".json")
    already = False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateMutexW(None, False, "Global\\BUAA_SIGNIN_"+digest)
        if not handle:
            raise OSError("无法创建系统互斥锁；已停止启动，避免重复守护")
        if ctypes.get_last_error() == 183:
            kernel.CloseHandle(handle)
            already = True
        else:
            _single_instance_mutex = handle
    else:
        import fcntl
        lock_path = profile.parent/(".instance-"+digest+".lock")
        handle = open(lock_path, "a+")
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            already = True
        except BaseException:
            handle.close()
            raise
        else:
            _open_lock_files.append(handle)
    if already:
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            existing_port = int(record["port"])
            if 1 <= existing_port <= 65535:
                check_and_wake_existing(existing_port)
        except Exception:
            pass
        return False
    # A foreign listener must not be mistaken for our application or silently bypassed.
    with socket.socket() as probe:
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            release_single_instance()
            raise RuntimeError("监听端口已被其他实例/服务占用，请先关闭原服务或选择其他端口")
    try:
        metadata.write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
        os.chmod(metadata, 0o600)
    except BaseException:
        release_single_instance()
        raise
    return True

def release_single_instance(lock=None):
    global _single_instance_mutex, _open_lock_files
    if _single_instance_mutex:
        import ctypes
        from ctypes import wintypes
        close = ctypes.WinDLL("kernel32").CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        close(_single_instance_mutex)
        _single_instance_mutex = None
    for handle in _open_lock_files:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    _open_lock_files = []


# 注册退出时的互斥锁自动清理
atexit.register(release_single_instance)


def check_and_wake_existing(port=DEFAULT_PORT):
    """Verify application identity, establish a local session, then wake the window."""
    try:
        import httpx
        with httpx.Client(trust_env=False, timeout=1) as client:
            base = f"http://127.0.0.1:{port}"
            health = client.get(base+"/api/health").json()
            if health.get("application") != "AUTO-BUAATOOLS":
                return False
            session = client.get(base+"/api/session")
            if session.status_code != 200:
                return False
            response = client.post(base+"/api/window/show", json={}, headers={"X-BUAA-CSRF":session.json()["csrf"]})
            return response.status_code == 200
    except Exception:
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
    global is_exiting, _exit_started, tray_icon, window
    if _exit_started:
        return
    _exit_started = True
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


def setup_tray(run_now: bool = True) -> Optional[Any]:
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
        if sys.platform.startswith("linux") and pystray.Icon.__module__.endswith("_xorg"):
            from Xlib import X, display
            connection = display.Display()
            try:
                atom = connection.intern_atom(f"_NET_SYSTEM_TRAY_S{connection.get_default_screen()}")
                if connection.get_selection_owner(atom) == X.NONE:
                    print("系统未提供托盘宿主，桌面窗口保持可见")
                    return None
            finally:
                connection.close()
        tray_img = get_tray_image()
        tray_menu = pystray.Menu(
            pystray.MenuItem("显示主界面", lambda icon, item: restore_window(), default=True),
            pystray.MenuItem("退出应用", lambda icon, item: exit_all()),
        )
        icon = CustomTrayIcon(
            name="BUAA-Signin",
            icon=tray_img,
            title=f"AUTO-BUAA v{VERSION}" if sys.platform.startswith("linux") else "BUAA 课程独立签到助手 v1.4.8 (后台运行中)",
            menu=tray_menu,
        )
        if run_now:
            icon.run_detached()
        return icon
    except Exception as te:
        print(f"系统托盘创建跳过: {type(te).__name__}")
        return None


def on_window_closing():
    """拦截窗口右上角 X 点击，取消彻底关闭，平滑隐藏至右下角系统托盘"""
    global window, is_exiting
    if is_exiting:
        return True  # 允许销毁
    if window:
        try:
            if tray_icon is None:
                window.minimize()
            else:
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
    parser = argparse.ArgumentParser(description="AUTO-BUAA 课程独立签到助手 Pro v1.4.8")
    parser.add_argument("--headless", action="store_true", help="无头模式：纯 Web 服务运行（适合 Linux 服务器、Docker 容器与后台驻留）")
    parser.add_argument("--host", type=str, default=None, help="监听主机地址（桌面模式默认 127.0.0.1，无头模式默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口号（默认 {DEFAULT_PORT}）")
    parser.add_argument("--autostart", action="store_true", help="开机自启静默启动模式")
    parser.add_argument("--minimized", action="store_true", help="最小化启动模式")
    parser.add_argument("--config", type=str, default=None, help="独立配置路径；同一配置只运行一个实例")
    parser.add_argument("--smoke-profile", action="store_true", help="内部验收：独立配置及合成学校接口")
    parser.add_argument("--smoke-test", action="store_true", help="内部验收：原生窗口运行检查后退出")
    parser.add_argument("--smoke-report", type=str, default=None)
    return parser.parse_args()


def main():
    global window, tray_icon

    args = parse_arguments()
    if args.config:
        import pathlib
        os.environ["BUAA_CONFIG_FILE"] = str(pathlib.Path(args.config).expanduser().resolve())
    smoke_directory = None
    if args.smoke_profile or args.smoke_test:
        import tempfile
        import pathlib
        smoke_directory = tempfile.TemporaryDirectory(prefix="buaa-native-smoke-")
        profile = pathlib.Path(smoke_directory.name) / "config.json"
        profile.write_text("{}", encoding="utf-8")
        os.environ["BUAA_CONFIG_FILE"] = str(profile)
        os.environ["TESTING"] = "1"
        os.environ["BUAA_SMOKE_PROFILE"] = "1"

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
        host = args.host or "127.0.0.1"
        if host not in ("127.0.0.1", "localhost", "::1") and (not os.environ.get("BUAA_ADMIN_PASSWORD") or not os.environ.get("BUAA_ALLOWED_HOSTS")):
            raise RuntimeError("远程监听必须设置应用管理密码和 BUAA_ALLOWED_HOSTS")
        print("=" * 66)
        print("  [*] AUTO-BUAA 课程独立签到助手 Pro (Linux / Headless Web 服务模式)")
        print("=" * 66)
        print(f"  版本:     v1.4.8")
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
    if not wait_for_server(port, timeout=30):
        release_single_instance()
        raise RuntimeError("本地后台启动失败，未创建空白窗口")

    # 5. 创建桌面任务栏系统托盘（包含“显示主界面”与“退出应用”，彻底消除 macOS 死锁与无头报错）
    tray_icon = setup_tray()
    if tray_icon is None:
        start_hidden = False

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
            background_color="#000000",  # Match the startup stage before the web document paints.
        )
        window.events.closing += on_window_closing
        from core.render_lifecycle import install_render_lifecycle
        install_render_lifecycle(window)

        # 启动主 GUI 事件循环（阻塞直到应用退出）
        if args.smoke_test:
            def native_smoke():
                global is_exiting
                import json
                import pathlib
                report = {"version": VERSION, "native_gui": True, "passed": False, "tray_available": tray_icon is not None}
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        try:
                            state = window.evaluate_js("({ready:typeof appState==='object' && appState.accounts.length===2, title:document.title, bodyWidth:document.body.scrollWidth, viewport:window.innerWidth})")
                            if state and state.get("ready"):
                                report.update({"passed": VERSION in state.get("title", "") and state["bodyWidth"] <= state["viewport"]+2, "state": state})
                                break
                        except Exception:
                            pass
                        time.sleep(0.25)
                    if not report["passed"]:
                        raise TimeoutError("Native initialization did not complete")
                    report["checks"]=[]
                    def wait_native(expression):
                        while time.monotonic() < deadline:
                            if window.evaluate_js(expression):
                                return
                            time.sleep(0.1)
                        raise TimeoutError("Native interaction did not complete")
                    window.evaluate_js("document.getElementById('navBtnBoya').click()")
                    wait_native("appState.boyaSelected.length===2")
                    window.evaluate_js("document.getElementById('tabBoyaSelected').click()")
                    wait_native("!!document.querySelector('[data-action=sign][data-id=\"2001\"]')")
                    window.evaluate_js("document.querySelector('[data-action=sign][data-id=\"2001\"]').click()")
                    wait_native("appState.boyaSelected.some(c=>c.courseId===2001 && c.signed_in)")
                    report["checks"].append("native-boya-sign")
                    window.evaluate_js("document.querySelector('[data-action=signout][data-id=\"2001\"]').click()")
                    wait_native("appState.boyaSelected.some(c=>c.courseId===2001 && c.signed_out && !c.final_passed)")
                    report["checks"].append("native-boya-signout-without-invented-assessment")
                    window.evaluate_js("document.getElementById('navBtnAccounts').click()")
                    wait_native("!!document.querySelector('[data-action=switchAccount][data-id=\"fixture-account-2\"]')")
                    window.evaluate_js("document.querySelector('[data-action=switchAccount][data-id=\"fixture-account-2\"]').click()")
                    wait_native("appState.activeUsername==='fixture-account-2' && appState.classes.some(c=>c.courseSchedId==='1002')")
                    report["checks"].append("native-account-switch")
                    window.evaluate_js("document.getElementById('navBtnRegular').click()")
                    wait_native("!!document.querySelector('[data-action=regularSign][data-id=\"1002\"]')")
                    window.evaluate_js("document.querySelector('[data-action=regularSign][data-id=\"1002\"]').click()")
                    wait_native("appState.classes.some(c=>c.courseSchedId==='1002' && c.signStatus===1)")
                    report["checks"].append("native-regular-sign")
                    # Native rendering regression runs only inside the synthetic self-test.
                    if sys.platform == "win32":
                        window.on_top = True
                        wait_native("!document.documentElement.classList.contains('startup-running') && window.BUAARenderLifecycle?.visible")
                        report["render_environment"] = window.evaluate_js("({reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,reducedTransparency:matchMedia('(prefers-reduced-transparency: reduce)').matches,motionDisabled:document.getElementById('ambientMotionToggle').disabled,initialFrames:Number(document.getElementById('ambientParticlesCanvas').dataset.frames||0)})")
                        # Exercise explicit animation opt-in in the isolated profile;
                        # hosted desktops may default to system reduced motion.
                        window.evaluate_js("{const control=document.getElementById('ambientMotionToggle');if(!control.checked&&!control.disabled)control.click();}")
                        def fluid_frames():
                            return window.evaluate_js("Number(document.getElementById('ambientParticlesCanvas').dataset.frames || 0)")
                        start_frames = fluid_frames()
                        wait_native(f"Number(document.getElementById('ambientParticlesCanvas').dataset.frames||0)>{start_frames}")
                        report["checks"].append("native-render-visible")
                        for mode in ("minimized", "tray"):
                            (window.minimize if mode == "minimized" else window.hide)()
                            wait_native("window.BUAARenderLifecycle?.visible === false")
                            stopped_frames = fluid_frames()
                            time.sleep(1)
                            assert fluid_frames() == stopped_frames, "Invisible canvas must stop"
                            report["checks"].append(f"native-{mode}-no-render")
                            window.show()
                            window.restore()
                            wait_native("window.BUAARenderLifecycle?.visible === true")
                            resumed_frames = fluid_frames()
                            wait_native(f"Number(document.getElementById('ambientParticlesCanvas').dataset.frames||0)>{resumed_frames}")
                            report["checks"].append(f"native-{mode}-resume")
                except Exception as exc:
                    report.update({"passed":False,"error_type":type(exc).__name__,"error_message":str(exc)[:240]})
                finally:
                    if args.smoke_report:
                        pathlib.Path(args.smoke_report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    is_exiting = True
                    window.destroy()
                    if not report["passed"]:
                        os._exit(1)
            webview.start(native_smoke)
        else:
            webview.start()
    except Exception as e:
        if args.smoke_test:
            if args.smoke_report:
                import json
                import pathlib
                pathlib.Path(args.smoke_report).write_text(json.dumps({"version": VERSION, "native_gui": False, "passed": False, "error_type": type(e).__name__}), encoding="utf-8")
            raise
        # 回退模式（如无图形渲染驱动）：使用默认浏览器打开
        if not start_hidden:
            webbrowser.open(f"http://127.0.0.1:{port}")
        while not is_exiting:
            time.sleep(1)

    # 退出清理
    exit_all()


if __name__ == "__main__":
    main()
