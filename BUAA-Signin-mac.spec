# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('server/static', 'server/static'), ('tray_icon.png', '.')],
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
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
    icon=None,
    bundle_identifier='com.buaa.signin',
    info_plist={
        'CFBundleDisplayName': 'BUAA 课程独立签到助手',
        'CFBundleName': 'BUAA-Signin',
        'CFBundleShortVersionString': '1.2.2',
        'CFBundleVersion': '1.2.2',
        'NSHighResolutionCapable': 'True',
        'LSUIElement': '0',
    },
)
