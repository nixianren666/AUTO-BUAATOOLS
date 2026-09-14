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

sys.path.insert(0, os.path.abspath('.'))
from server.app import app, accounts, AccountState, config
import uvicorn


class TestUIInteractions(unittest.TestCase):
    def test_ui_interactions(self):
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        if not os.path.exists(edge_path):
            self.skipTest("Edge browser not found for UI interaction test")

        orig_accounts = dict(accounts)
        orig_disclaimer = config.get("disclaimer_accepted", False)
        config["disclaimer_accepted"] = False
        accounts.clear()

        # Find free ports
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

        # Wait for server to be ready
        for _ in range(30):
            try:
                with socket.socket() as check_sock:
                    if check_sock.connect_ex(("127.0.0.1", test_port)) == 0:
                        break
            except Exception:
                pass
            time.sleep(0.1)

        user_data_dir = os.path.join(os.environ.get("TEMP", r"C:\Users\cjt16\AppData\Local\Temp"), f"edge_debug_profile_ui_{test_port}")
        shutil.rmtree(user_data_dir, ignore_errors=True)

        cmd = [
            edge_path,
            "--headless=new",
            "--disable-gpu",
            "--disable-cache",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            f"http://127.0.0.1:{test_port}/"
        ]
        proc = subprocess.Popen(cmd)

        try:
            # Wait for CDP endpoint
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
                time.sleep(0.4)
                raw = ws_sock.recv(65536)
                for part in raw.split(b'{"id":'):
                    if part.startswith(str(curr_id).encode()):
                        res_str = b'{"id":' + part.split(b"\x81")[0]
                        try:
                            res_json = json.loads(res_str.decode("utf-8", errors="ignore"))
                            return res_json.get("result", {}).get("result", {}).get("value")
                        except Exception:
                            pass
                return None

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

            # 3. 验证导航切换（常规课堂 -> 博雅套件 -> 终端监控）
            eval_js("switchMainView('boya')")
            view_boya_active = eval_js("!document.getElementById('viewBoya').classList.contains('hidden') && document.getElementById('viewRegular').classList.contains('hidden')")
            self.assertTrue(view_boya_active, "必须成功切换至博雅视图！")

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
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            server.should_exit = True
            server_thread.join(timeout=2)
            accounts.clear()
            accounts.update(orig_accounts)
            config["disclaimer_accepted"] = orig_disclaimer
            shutil.rmtree(user_data_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
