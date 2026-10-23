# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('server/static', 'server/static'), ('tray_icon.png', '.'), ('app_icon.icns', '.'), ('THIRD_PARTY_NOTICES.md', '.')] + collect_data_files('tzdata'),
    hiddenimports=[
        'cryptography',
        'httpx',
        'pydantic',
        'fastapi',
        'uvicorn',
        'core.boya_crypto',
        'core.boya_client',
        'core.boya_scheduler',
        'core.autostart',
        'qrcode',
        'qrcode.image.pil',
        'pystray',
        'pystray._darwin',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'webview',
        'webview.platforms.cocoa',
        'AppKit',
        'WebKit',
        'Foundation',
        'objc',
    ] + collect_submodules('keyring.backends'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Python and locally linked cryptography may resolve different OpenSSL 3 files
# with the same basename. Bundle the pair cryptography actually links to.
from pathlib import Path
from PyInstaller.depend.bindepend import get_imports
import cryptography.hazmat.bindings._rust as rust_bindings
import subprocess
openssl = {}
for name, resolved in get_imports(rust_bindings.__file__):
    if Path(name).name in ('libssl.3.dylib', 'libcrypto.3.dylib'):
        if not resolved:
            raise RuntimeError('Cannot resolve cryptography OpenSSL dependency: ' + name)
        openssl[Path(name).name] = resolved
if 'libssl.3.dylib' in openssl:
    for name, resolved in get_imports(openssl['libssl.3.dylib']):
        if Path(name).name == 'libcrypto.3.dylib' and resolved:
            openssl['libcrypto.3.dylib'] = resolved
    required = subprocess.check_output(['nm','-u',rust_bindings.__file__],text=True)
    provided = subprocess.check_output(['nm','-gU',openssl['libssl.3.dylib']],text=True)
    if '_SSL_get0_group_name' in required and '_SSL_get0_group_name' not in provided:
        raise RuntimeError('Resolved OpenSSL does not export cryptography required symbol')
    a.binaries = [(dest, openssl.get(Path(dest).name, source), kind) for dest,source,kind in a.binaries]
    print('Pinned linked OpenSSL pair:', sorted(openssl))
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BUAA-Signin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BUAA-Signin',
)

app = BUNDLE(
    coll,
    name='BUAA-Signin.app',
    icon='app_icon.icns',
    bundle_identifier='com.buaa.signin',
    info_plist={
        'CFBundleDisplayName': 'BUAA 课程独立签到助手',
        'CFBundleName': 'BUAA-Signin',
        'CFBundleShortVersionString': '1.4.13',
        'CFBundleVersion': '1.4.13',
        'NSHighResolutionCapable': 'True',
        'LSUIElement': '0',
    },
)
