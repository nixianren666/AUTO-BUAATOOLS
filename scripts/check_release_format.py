"""Run before publishing: stable tag, runtime and desktop metadata must agree."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.version import VERSION
from core.updates import release_version, version_tuple


def validate(tag=None):
    parts = version_tuple(VERSION)
    if tag is not None and release_version(tag) != VERSION:
        raise ValueError("Release tag must match runtime VERSION")
    checks = {
        "installer/setup.iss": [f'#define MyAppVersion "{VERSION}"', f'OutputBaseFilename=BUAA-Signin-Setup-v{VERSION}'],
        "installer/version_info.txt": [f"filevers=({','.join(map(str, parts))},0)", f"prodvers=({','.join(map(str, parts))},0)", f"'FileVersion','{VERSION}'", f"'ProductVersion','{VERSION}'"],
        "BUAA-Signin-mac.spec": [f"'CFBundleShortVersionString': '{VERSION}'", f"'CFBundleVersion': '{VERSION}'"],
        "server/static/index.html": [f'Origin v{VERSION}', f'app.js?v={VERSION}', f'updates.js?v={VERSION}'],
        "run.py": ['description=f"AUTO-BUAA 课程独立签到助手 Pro v{VERSION}"', 'print(f"  版本:     v{VERSION}")', 'else f"BUAA 课程独立签到助手 v{VERSION} (后台运行中)"'],
    }
    for name, values in checks.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        if not all(value in text for value in values):
            raise ValueError(f"Version metadata mismatch: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Actual stable GitHub Release tag, vX.Y.Z")
    args = parser.parse_args()
    validate(args.tag)
    print(f"Release format valid: v{VERSION}")
