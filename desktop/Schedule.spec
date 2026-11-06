from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / 'frontend' / 'dist'), 'frontend/dist')]
binaries = []
hidden = collect_submodules('app') + collect_submodules('uvicorn')
for package in ('webview', 'ortools', 'pythonnet', 'clr_loader'):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hidden += package_hidden

a = Analysis([str(root / 'desktop' / 'main.py')],
    pathex=[str(root / 'backend')], binaries=binaries, datas=datas,
    hiddenimports=hidden, excludes=['pytest', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Schedule',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Schedule')
