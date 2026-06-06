# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller 打包配置
生成单个 exe 文件，包含所有依赖
用法：pyinstaller main.spec
"""

a = Analysis(
    [r'main.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        (r'logo.ico', '.'),
    ],
    hiddenimports=[
        'paddle',
        'paddleocr',
        'paddleocr.ppocr',
        'openai',
        'httpx',
        'pyautogui',
        'pywin32',
        'Pillow',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'numpy',
        'keyboard',
        'queue',
        'logging',
        'json',
        're',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'tensorflow',
        'matplotlib',
        'scipy',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='水课快答',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[r'logo.ico'],
)
