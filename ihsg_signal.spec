# PyInstaller spec — membuat folder "PANDU" berisi "PANDU.exe"
#   pyinstaller --noconfirm ihsg_signal.spec
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [("config.yaml", "."), ("data/tickers_seed.csv", "data")]
binaries, hiddenimports = [], ["main", "yaml"]
for pkg in ("curl_cffi", "cloudscraper", "yfinance"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("certifi")

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "IPython", "notebook", "pytest", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PANDU",
    console=False,          # aplikasi berjendela (tanpa layar hitam)
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PANDU")
