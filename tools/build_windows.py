"""Build only inside this project, never installs, overwrites or publishes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    destination, report = args.dist_dir.resolve(), args.report_dir.resolve()
    if os.name != 'nt' or Path(sys.prefix).resolve() != ROOT / '.venv':
        parser.error('Use somente o Python da .venv deste projeto no Windows.')
    if any(ROOT not in path.parents for path in (destination, report)):
        parser.error('Saída e relatório devem estar dentro do projeto.')
    if (destination / 'R6-Rebuild').exists() or report.exists():
        parser.error('Use destinos NOVOS; builds e relatórios existentes não são sobrescritos.')
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    report.mkdir(parents=True)
    work = ROOT / 'build' / ('phase5-' + uuid.uuid4().hex[:12])
    command = [sys.executable, '-m', 'PyInstaller', str(ROOT / 'packaging/R6-Rebuild.spec'),
               '--distpath', str(destination), '--workpath', str(work)]
    with (report / 'build.log').open('x', encoding='utf-8') as log:
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError(f'Build falhou; detalhes em {report / "build.log"}.')
    bundle = destination / 'R6-Rebuild'
    shutil.copyfile(ROOT / 'packaging/LEIA-ME.txt', bundle / 'LEIA-ME.txt')
    import pefile
    with pefile.PE(str(bundle / 'R6-Rebuild.exe')) as pe:
        architecture, subsystem = pe.FILE_HEADER.Machine, pe.OPTIONAL_HEADER.Subsystem
    if architecture != 0x8664 or subsystem != 2:
        raise RuntimeError('Build não é Windows x64 GUI.')
    from check_brand_icon import verify_pe
    branding = verify_pe(bundle / 'R6-Rebuild.exe', ROOT / 'assets/branding/r6-rebuild.ico')
    subprocess.run([sys.executable, str(ROOT / 'tools/verify_public_bundle.py'),
                    '--bundle', str(bundle), '--analysis', str(work / 'R6-Rebuild/Analysis-00.toc')], check=True)
    files = list(p for p in bundle.rglob('*') if p.is_file())
    forbidden = [p for p in files if p.name in ('settings.json', 'settings.last-valid.json')
                 or any(part in ('.local', '.venv', '.research', 'tests') for part in p.relative_to(bundle).parts)]
    if forbidden:
        raise RuntimeError('Build contém arquivos pessoais/de desenvolvimento não permitidos.')
    for relative in ['data/profiles.json', 'frontend/styles.css', 'frontend/operator-icons.css',
                     'frontend/assets/operators/LICENSE.txt', 'assets/branding/r6-rebuild.ico']:
        if (bundle / '_internal' / relative).read_bytes() != (ROOT / relative).read_bytes():
            raise RuntimeError(f'Recurso divergente: {relative}')
    icons = list((bundle / '_internal/frontend/assets/operators').glob('*.svg'))
    if len(icons) != 75:
        raise RuntimeError('Distribuição não contém exatamente 75 logos.')
    for path in icons:
        if path.read_bytes() != (ROOT / 'frontend/assets/operators' / path.name).read_bytes():
            raise RuntimeError('Logo divergente: ' + path.name)
    manifest = {'at_utc': datetime.now(timezone.utc).isoformat(), 'command': command,
                'exe': str(bundle / 'R6-Rebuild.exe'), 'architecture': 'AMD64',
                'subsystem': 'Windows GUI (no console)', 'files': len(files),
                'bytes': sum(p.stat().st_size for p in files), 'logos': len(icons), 'branding': branding,
                'sha256': {p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    with (report / 'build.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in manifest.items() if k != 'sha256'}, indent=2))


if __name__ == '__main__':
    main()
