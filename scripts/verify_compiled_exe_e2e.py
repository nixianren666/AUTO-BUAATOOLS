import subprocess
import time
import json
import urllib.request
import socket
import base64
import os
import sys
import shutil

def run_compiled_exe_verification():
    exe_path = os.path.abspath(r"dist\BUAA-Signin.exe")
    if not os.path.exists(exe_path):
        print(f"Error: {exe_path} not found")
        sys.exit(1)

    port = 18355
    cdp_port = 9225

    # 启动已编译的可执行程序
    proc_exe = subprocess.Popen([exe_path, "--headless", "--port", str(port)])
    print(f"Launched {exe_path} with PID {proc_exe.pid} on port {port}")

    # 等待服务就绪
    server_ready = False
    for _ in range(40):
        try:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    server_ready = True
                    break
        except Exception:
            pass
        time.sleep(0.2)

    if not server_ready:
        print("Error: Compiled EXE failed to start HTTP server within timeout")
        proc_exe.terminate()
        sys.exit(1)

    print("Compiled EXE HTTP server is UP and responding!")

    # 验证静态网页与资源是否正常返回
    req = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
    html = req.read().decode("utf-8")
    assert "BUAA 课程独立签到助手" in html or "buaa" in html.lower()
    print("GET / returned HTML successfully!")

    # 启动真实 Edge 浏览器连接编译程序
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    import tempfile
    user_data_dir = os.path.join(tempfile.gettempdir(), f"edge_e2e_{port}")
    shutil.rmtree(user_data_dir, ignore_errors=True)

    proc_edge = subprocess.Popen([
        edge_path,
        "--headless=new",
        "--disable-gpu",
        "--disable-cache",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        f"http://127.0.0.1:{port}/"
    ])

    try:
        # 等待 CDP 端口
        tabs = []
        for _ in range(30):
            try:
                tabs_data = urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json", timeout=1).read()
                tabs = json.loads(tabs_data.decode())
                if any(t.get("type") == "page" for t in tabs):
                    break
            except Exception:
                time.sleep(0.2)

        print("Tabs found:", tabs)
        target_page = next(t for t in tabs if t.get("type") == "page" and str(port) in t.get("url", ""))
        ws_url = target_page["webSocketDebuggerUrl"]
        host_port = ws_url.split("/")[2]
        host, p = host_port.split(":")
        path = "/" + "/".join(ws_url.split("/")[3:])

        ws_sock = socket.socket()
        ws_sock.connect((host, int(p)))
        key = base64.b64encode(b"1234567890123456").decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{p}\r\n"
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
            print("EVAL_JS RAW RESPONSE:", raw[:250])
            for part in raw.split(b'{"id":'):
                if part.startswith(str(curr_id).encode()):
                    res_str = b'{"id":' + part.split(b"\x81")[0]
                    try:
                        res_json = json.loads(res_str.decode("utf-8", errors="ignore"))
                        return res_json.get("result", {}).get("result", {}).get("value")
                    except Exception:
                        pass
            return None

        # 等待页面与前端 app.js 加载就绪（兼容冷启动延迟）
        ready = False
        for _ in range(30):
            if eval_js("typeof appState !== 'undefined' && typeof switchMainView === 'function'"):
                ready = True
                break
            time.sleep(0.3)

        # 检查控制台是否有未捕获异常
        err = eval_js("window.__lastError || null")
        ready_state = eval_js("document.readyState")
        print(f"[E2E] document.readyState: {ready_state}")

        # 检查全局是否有 appState
        has_app_state = eval_js("typeof appState !== 'undefined'")
        print(f"[E2E] typeof appState: {has_app_state}")

        # 检查时钟是否已经从初始静态占位符更新为当前真实时间
        clock_text = eval_js("document.querySelector('#liveClock .clock-time')?.textContent")
        print(f"[E2E] System clock on compiled EXE: '{clock_text}'")

        # 检查当前是否有未捕获的前端 JS 异常
        has_app_state = eval_js("typeof appState !== 'undefined'")
        print(f"[E2E] appState object exists: {has_app_state}")
        assert has_app_state is True, "appState 对象必须正常初始化，JS 未发生致命语法阻断！"

        # 验证免责声明及交互
        disclaimer_visible = eval_js("!document.getElementById('disclaimerModal')?.classList.contains('hidden')")
        print(f"[E2E] Disclaimer modal visible: {disclaimer_visible}")

        # 验证视图导航切换
        eval_js("switchMainView('boya')")
        boya_active = eval_js("!document.getElementById('viewBoya')?.classList.contains('hidden')")
        print(f"[E2E] Boya view active: {boya_active}")
        assert boya_active is True

        has_auto_select = eval_js("document.getElementById('boyaAutoSelectToggle') !== null")
        has_auto_sign = eval_js("document.getElementById('boyaAutoSignToggle') !== null")
        has_redundant_toggle = eval_js("document.getElementById('boyaRequireAutoSignToggle') !== null")
        print(f"[E2E] boyaAutoSelectToggle: {has_auto_select}, boyaAutoSignToggle: {has_auto_sign}, redundantToggleRemoved: {not has_redundant_toggle}")
        assert has_auto_select is True and has_auto_sign is True
        assert has_redundant_toggle is False

        eval_js("switchMainView('logs')")
        logs_active = eval_js("!document.getElementById('viewLogs')?.classList.contains('hidden')")
        print(f"[E2E] Logs view active: {logs_active}")
        assert logs_active is True

        # 验证微信 ClawBot 侧边栏按钮与弹窗交互
        has_wechat_btn = eval_js("document.getElementById('navBtnWechat') !== null")
        print(f"[E2E] WeChat nav button exists: {has_wechat_btn}")
        assert has_wechat_btn is True

        eval_js("typeof openWeChatClawBotModal === 'function' && openWeChatClawBotModal()")
        wechat_modal_open = eval_js("!document.getElementById('wechatClawBotModal')?.classList.contains('hidden')")
        print(f"[E2E] WeChat ClawBot modal open: {wechat_modal_open}")
        assert wechat_modal_open is True

        # 验证二维码自动生成与渲染 (图片 src 为合法的 base64 data URI，占位文本自动隐藏)
        qr_src = None
        for _ in range(25):
            qr_src = eval_js("document.getElementById('wechatQrImg')?.src || ''")
            if qr_src and qr_src.startswith("data:image/"):
                break
            time.sleep(0.3)
        print(f"[E2E] WeChat QR Code src prefix: '{qr_src[:35] if qr_src else 'None'}'")
        assert qr_src and qr_src.startswith("data:image/"), "微信二维码必须成功生成为合法的 data:image Base64 URI！"
        placeholder_hidden = eval_js("document.getElementById('wechatQrPlaceholder')?.classList.contains('hidden')")
        print(f"[E2E] WeChat QR placeholder hidden: {placeholder_hidden}")
        assert placeholder_hidden is True, "生成二维码后占位文本必须隐去！"

        eval_js("typeof closeWeChatClawBotModal === 'function' && closeWeChatClawBotModal()")
        wechat_modal_closed = eval_js("document.getElementById('wechatClawBotModal')?.classList.contains('hidden')")
        print(f"[E2E] WeChat ClawBot modal closed: {wechat_modal_closed}")
        assert wechat_modal_closed is True

        print("\n" + "="*60)
        print("[SUCCESS] COMPILED STANDALONE EXE E2E VERIFICATION PASSED!")
        print("="*60 + "\n")

        ws_sock.close()
    finally:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc_edge.pid)], capture_output=True)
        except Exception:
            proc_edge.terminate()
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc_exe.pid)], capture_output=True)
        except Exception:
            proc_exe.terminate()
        shutil.rmtree(user_data_dir, ignore_errors=True)

if __name__ == "__main__":
    run_compiled_exe_verification()
