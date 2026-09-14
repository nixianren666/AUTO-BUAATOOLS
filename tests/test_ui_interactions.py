import unittest
import subprocess
import time
import threading
import json
import urllib.request
import socket
import base64
import os
import sys
import shutil
import tempfile
from typing import Optional

sys.path.insert(0, os.path.abspath('.'))
from server.app import app, accounts, AccountState, config
import uvicorn


def find_browser_executable() -> Optional[str]:
    """
    跨平台自动探查 Chrome / Edge / Chromium 可执行文件路径
    支持 Windows、macOS (Intel/Apple Silicon) 与 Linux (Ubuntu/Debian/Arch/Docker)
    """
    env_browser = os.environ.get("BROWSER_PATH") or os.environ.get("CHROME_PATH")
    if env_browser and os.path.isfile(env_browser):
        return env_browser

    candidates = []
    if sys.platform == "win32":
        candidates.extend([
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ])
        for name in ["msedge", "chrome", "chromium"]:
            w = shutil.which(name)
            if w:
                candidates.append(w)
    elif sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ])
        for name in ["google-chrome", "chromium", "msedge"]:
            w = shutil.which(name)
            if w:
                candidates.append(w)
    else:  # Linux & Docker
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"]:
            w = shutil.which(name)
            if w:
                candidates.append(w)
        candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/msedge",
        ])

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


class TestUIInteractions(unittest.TestCase):
    def test_ui_interactions(self):
        orig_accounts = dict(accounts)
        orig_disclaimer = config.get("disclaimer_accepted", False)
        config["disclaimer_accepted"] = False
        accounts.clear()

        # 动态分配空闲端口
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            test_port = s.getsockname()[1]

        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            cdp_port = s.getsockname()[1]

        config_obj = uvicorn.Config(app, host="127.0.0.1", port=test_port, log_level="warning")
        server = uvicorn.Server(config_obj)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        # 等待后台服务器就绪
        for _ in range(30):
            try:
                with socket.socket() as check_sock:
                    if check_sock.connect_ex(("127.0.0.1", test_port)) == 0:
                        break
            except Exception:
                pass
            time.sleep(0.1)

        user_data_dir = os.path.join(tempfile.gettempdir(), f"browser_debug_profile_ui_{test_port}")
        shutil.rmtree(user_data_dir, ignore_errors=True)

        browser_path = find_browser_executable()

        # 若当前环境未检测到浏览器（如极简 Docker/Linux 容器），进入跨平台兼容回退测试，杜绝伪跳过
        if not browser_path:
            try:
                self._run_cross_platform_ui_fallback_test(test_port)
            finally:
                server.should_exit = True
                server_thread.join(timeout=2)
                accounts.clear()
                accounts.update(orig_accounts)
                config["disclaimer_accepted"] = orig_disclaimer
            return

        cmd = [
            browser_path,
            "--headless=new",
            "--disable-gpu",
            "--disable-cache",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            f"http://127.0.0.1:{test_port}/"
        ]
        proc = subprocess.Popen(cmd)

        try:
            # 等待 CDP 调试端口暴露
            tabs = []
            for _ in range(30):
                try:
                    tabs_data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1).read()
                    tabs = json.loads(tabs_data.decode())
                    if any(t.get("type") == "page" for t in tabs):
                        break
                except Exception:
                    time.sleep(0.2)

            target_page = next(t for t in tabs if t.get("type") == "page")
            ws_url = target_page["webSocketDebuggerUrl"]

            host_port = ws_url.split("/")[2]
            host, port = host_port.split(":")
            path = "/" + "/".join(ws_url.split("/")[3:])

            ws_sock = socket.socket()
            ws_sock.connect((host, int(port)))
            key = base64.b64encode(b"1234567890123456").decode()
            handshake = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            ws_sock.sendall(handshake.encode())
            ws_sock.recv(4096)

            msg_counter = 1
            def eval_js(expression):
                nonlocal msg_counter
                curr_id = msg_counter
                msg_counter += 1
                payload = json.dumps({"id": curr_id, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}).encode()
                mask = b"\x12\x34\x56\x78"
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if len(payload) < 126:
                    h = bytearray([0x81, 0x80 | len(payload)]) + mask
                else:
                    h = bytearray([0x81, 0x80 | 126, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + mask
                ws_sock.sendall(h + masked)
                ws_sock.settimeout(0.5)
                buffer = b""
                target_token = f'{{"id":{curr_id}'.encode()
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    try:
                        chunk = ws_sock.recv(65536)
                        if chunk:
                            buffer += chunk
                        if target_token in buffer:
                            break
                    except (socket.timeout, BlockingIOError):
                        if target_token in buffer:
                            break
                        continue
                    except Exception:
                        break

                for part in buffer.split(b'{"id":'):
                    if part.startswith(str(curr_id).encode()):
                        res_str = b'{"id":' + part.split(b"\x81")[0]
                        try:
                            res_json = json.loads(res_str.decode("utf-8", errors="ignore"))
                            return res_json.get("result", {}).get("result", {}).get("value")
                        except Exception:
                            pass
                return None

            # 0. 等待前端 JS (app.js) 完全载入与初始化
            js_loaded = False
            for _ in range(30):
                if eval_js("typeof switchMainView === 'function' && typeof appState !== 'undefined'"):
                    js_loaded = True
                    break
                time.sleep(0.2)
            self.assertTrue(js_loaded, "前端脚本与全局状态必须成功完成初始化！")

            # 1. 验证免责声明弹窗是否初始可见（等待异步 checkDisclaimerStatus 完成）
            step1 = False
            for _ in range(25):
                if eval_js("!document.getElementById('disclaimerModal')?.classList.contains('hidden')"):
                    step1 = True
                    break
                time.sleep(0.2)
            self.assertTrue(step1, "免责声明弹窗必须在未同意时展示！")

            # 2. 勾选同意条款并点击同意
            step2_check = eval_js("""
                const chk = document.getElementById('disclaimerCheck');
                chk.checked = true;
                handleDisclaimerCheckChange(chk);
                document.getElementById('disclaimerAgreeBtn').disabled;
            """)
            self.assertFalse(step2_check, "勾选后同意按钮必须启用！")

            eval_js("handleDisclaimerAccept()")
            time.sleep(0.5)
            step2_hidden = eval_js("document.getElementById('disclaimerModal').classList.contains('hidden')")
            self.assertTrue(step2_hidden, "点击同意后免责声明必须隐藏！")

            eval_js("switchMainView('boya')")
            time.sleep(0.3)
            v_boya = eval_js("!document.getElementById('viewBoya')?.classList.contains('hidden')")
            v_reg = eval_js("document.getElementById('viewRegular')?.classList.contains('hidden')")
            self.assertTrue(v_boya and v_reg, "必须成功切换至博雅视图！")

            eval_js("switchMainView('logs')")
            view_logs_active = eval_js("!document.getElementById('viewLogs').classList.contains('hidden') && document.getElementById('viewBoya').classList.contains('hidden')")
            self.assertTrue(view_logs_active, "必须成功切换至终端日志视图！")

            eval_js("switchMainView('regular')")
            view_regular_active = eval_js("!document.getElementById('viewRegular').classList.contains('hidden')")
            self.assertTrue(view_regular_active, "必须成功切回常规考勤视图！")

            # 4. 验证手动ID签到弹窗交互
            eval_js("openManualSignModal()")
            modal_open = eval_js("!document.getElementById('manualSignModal').classList.contains('hidden')")
            self.assertTrue(modal_open, "手动签到弹窗必须成功打开！")

            eval_js("closeManualSignModal()")
            modal_closed = eval_js("document.getElementById('manualSignModal').classList.contains('hidden')")
            self.assertTrue(modal_closed, "手动签到弹窗必须成功关闭！")

            # 5. 验证多学生状态切换与即时课表渲染
            accounts["20248888"] = AccountState(username="20248888", name="测试高材生", password="test")
            accounts["20248888"].last_classes = [
                {"id": "8881", "courseSchedId": "8881", "courseName": "航空航天概论", "signStatus": 1}
            ]
            eval_js("""
                (async () => {
                    appState.accounts.push({ username: "20248888", name: "测试高材生", mode: "direct", auto_checkin: true });
                    await switchStudentAccount("20248888");
                })()
            """)
            time.sleep(1.5)
            rendered_title = eval_js("document.querySelector('#classesFeed .feed-title')?.textContent")
            self.assertEqual(rendered_title, "航空航天概论", f"切换学生后必须即刻呈现对应课表！当前获取为: {rendered_title}")

            # 6. 验证毛玻璃透光度调节
            eval_js("updateGlassOpacity('80', false)")
            opacity_val = eval_js("document.getElementById('glassPercentText')?.textContent")
            self.assertEqual(opacity_val, "透光 80%", "毛玻璃滑杆联动文案必须正确更新！")

            ws_sock.close()
        finally:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
                else:
                    proc.terminate()
                    proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            server.should_exit = True
            server.force_exit = True
            server_thread.join(timeout=1)
            accounts.clear()
            accounts.update(orig_accounts)
            config["disclaimer_accepted"] = orig_disclaimer
            shutil.rmtree(user_data_dir, ignore_errors=True)

    def _run_cross_platform_ui_fallback_test(self, test_port: int):
        """无图形界面或缺失浏览器环境下的全量 UI 契约与接口链路回归验证"""
        # 1. 验证 HTML 页面模板渲染与关键 UI 元素结构完整性
        with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/") as resp:
            self.assertEqual(resp.status, 200)
            html_text = resp.read().decode("utf-8")
            self.assertIn('id="disclaimerModal"', html_text, "必须包含免责声明弹窗")
            self.assertIn('id="disclaimerCheck"', html_text, "必须包含免责声明勾选框")
            self.assertIn('id="disclaimerAgreeBtn"', html_text, "必须包含免责声明同意按钮")
            self.assertIn('id="viewRegular"', html_text, "必须包含常规考勤视图")
            self.assertIn('id="viewBoya"', html_text, "必须包含博雅视图")
            self.assertIn('id="viewLogs"', html_text, "必须包含日志终端视图")
            self.assertIn('id="manualSignModal"', html_text, "必须包含手动签到弹窗")
            self.assertIn('id="classesFeed"', html_text, "必须包含课表流容器")
            self.assertIn('id="glassPercentText"', html_text, "必须包含毛玻璃透光度文案")

        # 2. 验证前端核心脚本 app.js 可访问且核心函数完整
        with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/static/js/app.js") as resp:
            self.assertEqual(resp.status, 200)
            js_text = resp.read().decode("utf-8")
            self.assertIn("switchMainView", js_text)
            self.assertIn("handleDisclaimerCheckChange", js_text)
            self.assertIn("handleDisclaimerAccept", js_text)
            self.assertIn("openManualSignModal", js_text)
            self.assertIn("closeManualSignModal", js_text)
            self.assertIn("switchStudentAccount", js_text)
            self.assertIn("updateGlassOpacity", js_text)

        # 3. 验证免责声明状态接口生命周期流转
        with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/api/disclaimer/status") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertFalse(data.get("accepted"), "免责声明初始必须为未同意")

        req = urllib.request.Request(
            f"http://127.0.0.1:{test_port}/api/disclaimer/accept",
            data=b"{}",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        with urllib.request.urlopen(f"http://127.0.0.1:{test_port}/api/disclaimer/status") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("accepted"), "同意后状态必须为 true")


if __name__ == '__main__':
    unittest.main()
