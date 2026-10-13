"""Standard browser driver acceptance; no hand-written CDP framing or fake fallback."""
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

import uvicorn
from server import app as backend
from core import boya_client

class TestUIInteractions(unittest.TestCase):
    def test_ui_interactions(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        node = os.environ.get("BUAA_NODE_EXECUTABLE") or shutil.which("node")
        if not node:
            self.fail("Real UI acceptance needs Node.js and Playwright")
        browser = os.environ.get("BUAA_TEST_BROWSER", "")
        if not browser:
            for candidate in [r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome") or ""]:
                if candidate and pathlib.Path(candidate).is_file():
                    browser = candidate
                    break
        modules = os.environ.get("BUAA_NODE_MODULES") or str(root/"node_modules")
        bundled = pathlib.Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
        if not pathlib.Path(modules).is_dir() and bundled.is_dir():
            modules = str(bundled)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1",0))
            port = listener.getsockname()[1]
        original_accounts = dict(backend.accounts)
        original_active = backend.active_username
        original_crypto = boya_client.BykcCrypto
        original_config = dict(backend.config)
        backend.accounts.clear()
        backend.active_username = None
        server = uvicorn.Server(uvicorn.Config(backend.app,host="127.0.0.1",port=port,log_level="warning"))
        with tempfile.TemporaryDirectory(prefix="buaa-browser-test-") as directory, patch.dict(os.environ,{"BUAA_SMOKE_PROFILE":"1"}):
            report = pathlib.Path(directory)/"browser.json"
            thread = threading.Thread(target=server.run,daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started: break
                    time.sleep(0.05)
                self.assertTrue(server.started,"Isolated API must start")
                env = dict(os.environ)
                env["NODE_PATH"] = modules
                result = subprocess.run([node,str(root/"scripts/ui_acceptance.cjs"),f"http://127.0.0.1:{port}/",browser,str(report)],env=env,capture_output=True,text=True,timeout=90)
                if report.exists():
                    import json
                    evidence = json.loads(report.read_text(encoding="utf-8"))
                    output_dir = os.environ.get("BUAA_TEST_REPORT_DIR")
                    if output_dir:
                        pathlib.Path(output_dir).mkdir(parents=True,exist_ok=True)
                        shutil.copy2(report,pathlib.Path(output_dir)/"browser-summary.json")
                    self.assertTrue(evidence["passed"],str(evidence))
                self.assertEqual(result.returncode,0,result.stderr[-2000:])
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                for account in list(backend.accounts.values()):
                    if account.username.startswith("fixture-account-"):
                        account.boya_client.close()
                backend.accounts.clear()
                backend.accounts.update(original_accounts)
                backend.active_username = original_active
                backend.config.clear()
                backend.config.update(original_config)
                boya_client.BykcCrypto = original_crypto

if __name__ == "__main__":
    unittest.main()
