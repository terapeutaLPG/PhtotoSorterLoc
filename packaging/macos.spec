# Build on macOS: .venv/bin/python -m PyInstaller packaging/macos.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []
for package in ("customtkinter", "pillow_heif", "reverse_geocoder"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [str(root / "photo_sorter.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhotoSorter",
    console=False,
    argv_emulation=False,
)
collection = COLLECT(exe, a.binaries, a.datas, name="PhotoSorter")
app = BUNDLE(
    collection,
    name="PhotoSorter.app",
    bundle_identifier="pl.terapeutalpg.photosorter",
    info_plist={
        "CFBundleDisplayName": "Photo Sorter",
        "CFBundleShortVersionString": "2.0.0",
        "NSHighResolutionCapable": True,
        "NSDocumentsFolderUsageDescription": "Photo Sorter odczytuje i kopiuje zdjęcia z wybranych folderów.",
        "NSDownloadsFolderUsageDescription": "Photo Sorter odczytuje i kopiuje zdjęcia z wybranych folderów.",
        "NSDesktopFolderUsageDescription": "Photo Sorter odczytuje i kopiuje zdjęcia z wybranych folderów.",
        "NSRemovableVolumesUsageDescription": "Photo Sorter odczytuje i kopiuje zdjęcia na wybranych dyskach zewnętrznych.",
        "NSNetworkVolumesUsageDescription": "Photo Sorter odczytuje i kopiuje zdjęcia na wybranych dyskach sieciowych.",
    },
)
