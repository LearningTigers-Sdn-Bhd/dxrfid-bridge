# PyInstaller spec — DXRFID Bridge single-file Windows build.
#
# Build (on Windows, from the dxrfid-bridge folder):
#     build\build-exe.bat
# or manually:
#     pyinstaller build\dxrfid-bridge.spec --distpath dist --workpath build\work
#
# Output: dist\dxrfid-bridge.exe — double-click starts the console and opens
# the browser. Data (config, later SQLite) lives in
# %LOCALAPPDATA%\DXRFIDBridge — never next to the exe.
#
# The console is stdlib-only, so there are no hidden imports to chase; the
# only bundled data are the UI file and the vendor Release DLL for the USB
# encoder (extracted to sys._MEIPASS at runtime, where bridge/encoder.py
# looks first).

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # dxrfid-bridge/
APP = os.path.join(ROOT, "app")

datas = [
    (os.path.join(APP, "ui", "index.html"), "ui"),
]
dll = os.path.join(ROOT, "vendor", "ECRFID.dll")
if os.path.exists(dll):
    datas.append((dll, "."))

a = Analysis(
    [os.path.join(APP, "server.py")],
    pathex=[APP],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pip", "setuptools"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dxrfid-bridge",
    debug=False,
    strip=False,
    upx=False,               # keep AV false-positive rate down
    console=True,            # console window shows the URL; closing it stops the bridge
    icon=None,               # TODO: drop an .ico into build/ and reference it here
    contents_directory=".",  # one-file: data extracted into the temp dir root
)
