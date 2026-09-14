# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    'pyttsx3.drivers',
    'pyttsx3.drivers.sapi5',
]

for pkg in ['faster_whisper', 'sounddevice', 'edge_tts', 'ctranslate2', 'onnxruntime']:
    try:
        tmp_datas, tmp_binaries, tmp_hiddenimports = collect_all(pkg)
        datas.extend(tmp_datas)
        binaries.extend(tmp_binaries)
        hiddenimports.extend(tmp_hiddenimports)
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
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
    name='GD Assistant',
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
)