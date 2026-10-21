# Linux x86_64 with Qt6 desktop and headless support.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
a = Analysis(['run.py'], pathex=[], binaries=[],
    datas=[('server/static','server/static'),('tray_icon.png','.'),('THIRD_PARTY_NOTICES.md','.')]+collect_data_files('tzdata'),
    hiddenimports=['webview.platforms.qt','PyQt6.QtWebEngineCore','PyQt6.QtWebEngineWidgets','pystray._xorg']+collect_submodules('keyring.backends'),
    hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,a.binaries,a.datas,[],name='BUAA-Signin',console=True,strip=False,upx=False)
