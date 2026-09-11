import subprocess
import time
import urllib.request
import json
import os
import sys
import pathlib

print("=== Starting macOS Smoke Test for BUAA-Signin ===")

# 1. Verify autostart functionality
from core.autostart import set_autostart, get_autostart_status
assert set_autostart(True), "set_autostart True failed"
assert get_autostart_status(), "get_autostart_status failed"
assert set_autostart(False), "set_autostart False failed"
assert not get_autostart_status(), "autostart should be disabled"
print("1. macOS LaunchAgents autostart verified successfully!")

# 2. Locate built .app bundle executable
app_path = pathlib.Path("dist/BUAA-Signin.app/Contents/MacOS/BUAA-Signin")
if not app_path.exists():
    print(f"Error: Executable not found at {app_path}")
    sys.exit(1)

print(f"2. Found executable: {app_path}")

# Ensure executable bit
os.chmod(app_path, 0o755)

# 3. Launch with --autostart (headless background mode)
proc = subprocess.Popen([str(app_path.resolve()), "--autostart"])
print(f"3. Launched process with PID: {proc.pid}")

try:
    # 4. Wait for /api/health
    ready = False
    start_t = time.time()
    while time.time() - start_t < 15:
        try:
            with urllib.request.urlopen("http://127.0.0.1:18346/api/health", timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    print(f"4. /api/health returned: {data}")
                    assert data.get("status") == "ok"
                    assert data.get("version") == "1.2.0"
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)

    if not ready:
        print("Error: Server failed to start within 15 seconds")
        sys.exit(1)

    # 5. Check courses API
    with urllib.request.urlopen("http://127.0.0.1:18346/api/boya/courses", timeout=2.0) as resp:
        cdata = json.loads(resp.read().decode())
        courses = cdata.get("courses", [])
        print(f"5. Boya courses returned: {len(courses)} courses")
        assert len(courses) > 0, "Course pool must not be empty"

    print("=== All macOS checks PASSED! Cleanly exiting... ===")
finally:
    try:
        req = urllib.request.Request("http://127.0.0.1:18346/api/exit", data=b"{}", method="POST")
        urllib.request.urlopen(req, timeout=2.0)
    except Exception:
        pass

    time.sleep(1.0)
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=3)
    print("Process exited cleanly.")
