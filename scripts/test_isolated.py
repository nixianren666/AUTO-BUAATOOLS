"""Run the complete suite without user configuration, school traffic or OS writes."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import traceback
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--embedded-executable', type=Path)
    parser.add_argument('--pattern', default='test_*.py')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    if not os.environ.get("BUAA_NODE_MODULES") and (project/"node_modules").is_dir():
        os.environ["BUAA_NODE_MODULES"] = str(project/"node_modules")
    report_dir = Path(os.environ.get("BUAA_TEST_REPORT_DIR") or tempfile.mkdtemp(prefix="buaa-test-reports-")).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="buaa-test-source-") as directory:
        source = Path(directory)
        for name in ("core", "server", "tests", "scripts", "installer", "systemd", ".github"):
            if (project/name).is_dir():
                shutil.copytree(project/name, source/name, ignore=shutil.ignore_patterns("__pycache__", "test_td_issuer.py"))
        for pattern in ("*.spec", "app_icon.*", "tray_icon.png", "Dockerfile", "docker-compose.yml", "run.py", "requirements*.txt", "README.md", "THIRD_PARTY_NOTICES.md"):
            for file in project.glob(pattern):
                if file.is_file():
                    shutil.copy2(file, source/file.name)
        config = source/"config.json"
        config.write_text("{}", encoding="utf-8")
        os.environ.update({"TESTING": "1", "BUAA_CONFIG_FILE": str(config), "BUAA_VAULT_DIR": str(source/"private-vault"), "NO_PROXY": "*", "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"})
        os.environ.pop("BUAA_ADMIN_PASSWORD", None)
        os.environ.pop("BUAA_SMOKE_PROFILE", None)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(key, None)
        blocked = []
        def audit(event, args):
            if event == "socket.connect":
                address = args[1]
                if isinstance(address, tuple) and str(address[0]) not in ("127.0.0.1", "localhost", "::1"):
                    blocked.append([{"file":Path(frame.filename).name,"line":frame.lineno,"function":frame.name} for frame in traceback.extract_stack()[-45:]])
                    raise PermissionError("School/third-party traffic forbidden in isolated tests")
            if event in ("winreg.SetValue", "winreg.DeleteValue", "winreg.DeleteKey"):
                raise PermissionError("Registry mutations forbidden in isolated tests")
        sys.addaudithook(audit)
        os.chdir(source)
        sys.path.insert(0, str(source))
        sys.dont_write_bytecode = True
        embedded_modules = []
        if args.embedded_executable:
            # Execute the exact packaged Python code, with disposable data and
            # the same external-traffic guard as the source contracts.
            import importlib.abc
            import importlib.util
            from PyInstaller.archive.readers import CArchiveReader
            archive = CArchiveReader(str(args.embedded_executable.resolve()))
            pyz = archive.open_embedded_archive('PYZ.pyz')
            class EmbeddedApplication(importlib.abc.MetaPathFinder, importlib.abc.Loader):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname.split('.')[0] not in ('core', 'server'):
                        return None
                    if fullname not in pyz.toc:
                        raise ImportError('Application module absent from executable: '+fullname)
                    package = pyz.toc[fullname][0] == 1
                    return importlib.util.spec_from_loader(fullname, self, is_package=package)
                def create_module(self, spec):
                    return None
                def exec_module(self, module):
                    file = source.joinpath(*module.__name__.split('.'))
                    if module.__spec__.submodule_search_locations is not None:
                        module.__path__ = [str(file)]
                        file = file/'__init__.py'
                    else:
                        file = file.with_suffix('.py')
                    module.__file__ = str(file)
                    embedded_modules.append(module.__name__)
                    exec(pyz.extract(module.__name__), module.__dict__)
            sys.meta_path.insert(0, EmbeddedApplication())
        stream = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            suite = unittest.defaultTestLoader.discover("tests", pattern=args.pattern)
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        (report_dir/"test-output.txt").write_text(stream.getvalue(), encoding="utf-8")
        summary = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped), "passed": result.wasSuccessful() and not result.skipped, "elapsed_seconds": round(time.monotonic()-started,2), "blocked_non_loopback_attempts": len(blocked), "failure_names": [str(t) for t,_ in result.failures], "error_names": [str(t) for t,_ in result.errors]}
        (report_dir/"test-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.embedded_executable:
            import hashlib
            (report_dir/'embedded-code.json').write_text(json.dumps({'executable_sha256':hashlib.sha256(args.embedded_executable.read_bytes()).hexdigest(), 'modules':sorted(embedded_modules), 'tests_executed_from_packaged_application':True},indent=2),encoding='utf-8')
        (report_dir/"blocked-network-callers.json").write_text(json.dumps(blocked,indent=2),encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
        os.chdir(project)
        return 0 if summary["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
