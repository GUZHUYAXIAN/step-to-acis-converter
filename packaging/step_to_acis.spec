# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


project_root = Path(SPECPATH).resolve().parent
source_root = project_root / "src"
version_file = project_root / "packaging" / "windows_version_info.txt"

a = Analysis(
    [str(project_root / "portable_launcher.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[
        (str(project_root / "spaceclaim" / "probe_v22.py"), "resources"),
        (str(project_root / "spaceclaim" / "worker_v22.py"), "resources"),
    ],
    hiddenimports=[],
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
    name="STEP转ACIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=str(version_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="STEP转ACIS便携版",
)
