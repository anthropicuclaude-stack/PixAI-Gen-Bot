# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
datas = [('prompts.json', '.'), ('model_presets.json', '.'), ('ss.js', '.'), ('crawler.py', '.'), ('gui.py', '.'), ('setup_wizard.py', '.')]
datas += collect_data_files('playwright_stealth')

block_cipher = None

# 모든 필요한 파일을 하나의 분석에 포함
a = Analysis(
    ['bootstrap.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'crawler',
        'gui',
        'setup_wizard',
        'playwright',
        'playwright.async_api',
        'playwright_stealth',
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.messagebox',
        'tkinter.simpledialog',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'asyncio',
        'threading',
        'json',
        'subprocess',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PixAI-Gen-Bot',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 프로그램이므로 콘솔 숨김 (디버그 시 True로 변경)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='favicon.png'
)