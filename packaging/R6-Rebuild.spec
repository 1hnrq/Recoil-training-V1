# Explicit onedir allowlist: never bundle .local, evidence, tools or tests.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
frontend_files = ['index.html', 'app.js', 'model.js', 'bridge-client.js',
                  'preview-transport.js', 'styles.css', 'operator-icons.css']
datas = [(str(root / 'frontend' / name), 'frontend') for name in frontend_files]
datas += [(str(root / 'frontend/assets/operators'), 'frontend/assets/operators'),
          (str(root / 'assets/branding/r6-rebuild.ico'), 'assets/branding'),
          (str(root / 'data/profiles.json'), 'data'),
          (str(root / 'packaging/LEIA-ME.txt'), '.')]
for distribution in ('pywebview', 'pythonnet', 'clr_loader', 'cffi', 'pycparser',
                     'proxy_tools', 'bottle', 'typing_extensions'):
    datas += copy_metadata(distribution)
a = Analysis([str(root / 'packaging/entrypoint.py')], pathex=[str(root / 'src')],
             binaries=[], datas=datas,
             hiddenimports=['webview.platforms.winforms', 'webview.platforms.edgechromium'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3',
                       'gi', 'kivy', 'tkinter', 'pytest', 'unittest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='R6-Rebuild',
          icon=str(root / 'assets/branding/r6-rebuild.ico'),
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='R6-Rebuild')
