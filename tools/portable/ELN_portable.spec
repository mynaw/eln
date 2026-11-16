# -*- mode: python ; coding: utf-8 -*-
"""发布用打包脚本：路径全部相对本文件，换机器也能直接构建。

    python -m PyInstaller tools/portable/ELN_portable.spec --noconfirm --clean ^
        --distpath _release/dist --workpath _release/build

产物：_release/dist/ELN/ （免安装目录版，双击 ELN.exe 运行）
"""
import os

from PyInstaller.utils.hooks import (collect_all, collect_data_files,
                                     collect_dynamic_libs, collect_submodules)

ROOT = os.path.dirname(os.path.dirname(SPECPATH))          # 仓库根目录


def p(*parts):
    return os.path.join(ROOT, *parts)


datas = [
    (p("assets"), "assets"),
    (p("MANUAL.md"), "."),
    (p("README.md"), "."),
    (p("LICENSE"), "."),
    (p("THIRD-PARTY-NOTICES.md"), "."),
]
# Ketcher 是可选增强：只有构建过 dist 才打进去，没有也能正常运行
_ketcher_dist = p("vendor", "ketcher-app", "dist")
if os.path.isdir(_ketcher_dist):
    datas.append((_ketcher_dist, os.path.join("vendor", "ketcher-app", "dist")))

binaries = []
hiddenimports = [
    "win32crypt", "win32clipboard", "win32api", "win32con",
    "markdown", "pygments", "tkinterweb",
    "engine", "groups", "hybrid", "ext", "structure", "caslookup", "polarity",
    "auth", "store", "chem", "paths", "stoich", "recexport", "fpdf", "docx",
    "ketcherwin", "keyfix",
]
datas += collect_data_files("rdkit")
binaries += collect_dynamic_libs("rdkit")
hiddenimports += collect_submodules("pygments")
_ti = collect_all("tkinterweb")
datas += _ti[0]
binaries += _ti[1]
hiddenimports += _ti[2]

a = Analysis(
    [p("gui.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython",
              "matplotlib", "qtpy", "qtconsole", "nbconvert"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ELN",
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
    icon=[p("assets", "app.ico")],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ELN",
)
