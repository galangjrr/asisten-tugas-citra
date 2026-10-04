# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

ROOT_DIR = os.path.abspath(os.path.join(SPECPATH, '..')) if os.path.basename(SPECPATH).lower() == 'build' else os.path.abspath(SPECPATH)

hiddenimports = []
hiddenimports += collect_submodules('api')
hiddenimports += collect_submodules('agents')
hiddenimports += collect_submodules('exporters')
hiddenimports += collect_submodules('tools')

icon_file = os.path.join(ROOT_DIR, 'assets', 'icon.ico')
if not os.path.exists(icon_file):
    icon_file = os.path.join(ROOT_DIR, 'app.ico')

datas = [
    (os.path.join(ROOT_DIR, 'static'), 'static'),
    (os.path.join(ROOT_DIR, 'data'), 'data'),
    (os.path.join(ROOT_DIR, 'assets'), 'assets'),
    (os.path.join(ROOT_DIR, 'saved_modules'), 'saved_modules'),
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'run_app.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='AsistenTugasCitra',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
