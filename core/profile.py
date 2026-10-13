"""Configuration identity shared by the launcher and server."""
import os
import pathlib
import sys

def resolve_config_path() -> pathlib.Path:
    """
    智能解析配置文件路径：
    1. 便携版模式优先读取 exe 所在同级目录的 config.json；
    2. 若同级目录不可写（如标准安装在 Program Files），则切换到用户 APPDATA 目录；
    3. 若 APPDATA 中尚无配置，且桌面或工作区有旧配置，自动平滑继承。
    """
    if os.environ.get("BUAA_CONFIG_FILE"):
        return pathlib.Path(os.environ["BUAA_CONFIG_FILE"]).expanduser().resolve()
    if getattr(sys, "frozen", False):
        exe_dir = pathlib.Path(sys.executable).parent
        portable_cfg = exe_dir / "config.json"
        if portable_cfg.exists():
            return portable_cfg

        if sys.platform == "darwin":
            mac_support_dir = pathlib.Path.home() / "Library" / "Application Support" / "BUAA-Signin"
            mac_support_dir.mkdir(parents=True, exist_ok=True)
            mac_cfg = mac_support_dir / "config.json"
            if mac_cfg.exists():
                return mac_cfg
            # 也可检查 .app 同级目录的便携式配置
            app_bundle_dir = exe_dir.parent.parent.parent
            if (app_bundle_dir / "config.json").exists():
                return app_bundle_dir / "config.json"
            return mac_cfg

        if sys.platform.startswith("linux"):
            cwd_cfg = pathlib.Path.cwd() / "config.json"
            if cwd_cfg.exists():
                return cwd_cfg
            linux_cfg_dir = pathlib.Path.home() / ".config" / "buaa-signin"
            linux_cfg_dir.mkdir(parents=True, exist_ok=True)
            return linux_cfg_dir / "config.json"

        appdata = os.environ.get("APPDATA")
        if appdata:
            appdata_dir = pathlib.Path(appdata) / "BUAA-Signin"
            appdata_dir.mkdir(parents=True, exist_ok=True)
            appdata_cfg = appdata_dir / "config.json"
            if appdata_cfg.exists():
                return appdata_cfg

        # 测试 exe_dir 是否可写
        try:
            test_file = exe_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            return portable_cfg
        except Exception:
            if appdata:
                appdata_dir = pathlib.Path(appdata) / "BUAA-Signin"
                appdata_dir.mkdir(parents=True, exist_ok=True)
                return appdata_dir / "config.json"
            return portable_cfg
    else:
        base_dir = pathlib.Path(__file__).parent.parent
        return base_dir / "config.json"
