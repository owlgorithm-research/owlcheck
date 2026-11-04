# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for OwlCheck. From the repo root:
#   pyinstaller packaging/owlcheck.spec --noconfirm
#
# Output in dist/:
#   Windows  OwlCheck/OwlCheck.exe  (onedir: starts faster than onefile, which unpacks
#                                    to Temp on every launch, and antivirus flags it far less)
#   macOS    OwlCheck.app
#   Linux    OwlCheck               (single file)
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (ROOT / "owlcheck.py").read_text(encoding="utf-8"), re.M).group(1)

if sys.platform == "win32":
    ICON = ROOT / "app" / "assets" / "icon.ico"
elif sys.platform == "darwin":
    ICON = ROOT / "app" / "assets" / "icon.icns"
else:
    ICON = ROOT / "app" / "assets" / "icon.png"


def windows_version_info():
    """The Properties > Details tab of OwlCheck.exe."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:4])
    nums = nums + (0,) * (4 - len(nums))
    fields = {
        "CompanyName": "Owlgorithm Research",
        "FileDescription": "OwlCheck",
        "FileVersion": VERSION,
        "InternalName": "OwlCheck",
        "LegalCopyright": "© 2026 PΛTTRN",
        "OriginalFilename": "OwlCheck.exe",
        "ProductName": "OwlCheck",
        "ProductVersion": VERSION,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in fields.items()])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )


a = Analysis(
    [str(ROOT / "app" / "app.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app" / "ui"), "app/ui"),
        (str(ROOT / "app" / "assets"), "app/assets"),
    ],
    hiddenimports=["owlcheck"],
    excludes=["tkinter", "unittest", "pydoc"] + (["gi"] if sys.platform.startswith("linux") else []),
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OwlCheck",
              console=False, icon=str(ICON), upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="OwlCheck", upx=False)
    app = BUNDLE(
        coll,
        name="OwlCheck.app",
        icon=str(ICON),
        bundle_identifier="io.github.owlgorithm-research.owlcheck",
        info_plist={
            "CFBundleName": "OwlCheck",
            "CFBundleDisplayName": "OwlCheck",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "© 2026 PΛTTRN",
        },
    )
elif sys.platform == "win32":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OwlCheck",
              console=False, icon=str(ICON), upx=False, version=windows_version_info())
    coll = COLLECT(exe, a.binaries, a.datas, name="OwlCheck", upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="OwlCheck",
              console=False, icon=str(ICON), upx=False)
