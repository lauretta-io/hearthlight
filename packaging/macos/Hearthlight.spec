# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


spec_dir = Path(SPECPATH)
repo_root = spec_dir.parents[1]
generated_icon = spec_dir / "generated" / "Hearthlight.icns"

block_cipher = None

a = Analysis(
    [str(repo_root / "hearthlight" / "macos_app.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=["tkinter", "tkinter.ttk"],
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
    [],
    exclude_binaries=True,
    name="Hearthlight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Hearthlight",
)

app = BUNDLE(
    coll,
    name="Hearthlight.app",
    icon=str(generated_icon) if generated_icon.exists() else None,
    bundle_identifier="io.lauretta.hearthlight",
    info_plist={
        "CFBundleName": "Hearthlight",
        "CFBundleDisplayName": "Hearthlight",
        "CFBundleShortVersionString": "0.8.0",
        "CFBundleVersion": "0.8.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Lauretta IO",
    },
)
