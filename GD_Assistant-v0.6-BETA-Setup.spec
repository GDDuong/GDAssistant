# -*- mode: python ; coding: utf-8 -*-
# Onedir build: the folder this produces (dist\GD_Assistant) is what the
# Inno Setup script (installer\GD_Assistant-v0.6-BETA.iss) packages into the
# offline installer. Keeps the installed exe name version-stable.
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['pyttsx3.drivers', 'pyttsx3.drivers.sapi5']
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('edge_tts')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # lxml: bs4's optional builder (html.parser is what we use)
    # hf_xet: huggingface_hub's optional xet backend (falls back to plain HTTP)
    # PIL._avif: Pillow's optional AVIF plugin (init() skips it if absent)
    excludes=['lxml', 'hf_xet', 'PIL._avif'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GD_Assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
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
    upx=True,
    upx_exclude=[],
    name='GD_Assistant',
)
