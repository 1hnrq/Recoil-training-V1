"""Attach notices and inventory a local candidate. Never emits mouse input."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import pefile
from check_brand_icon import verify_pe

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--analysis',type=Path,required=True)
    args=parser.parse_args()
    bundle=args.bundle.resolve()
    if ROOT not in bundle.parents:raise ValueError('Bundle must be inside this project')
    for source in [ROOT/'THIRD_PARTY_NOTICES.txt', ROOT/'packaging/LEIA-ME.txt', *sorted((ROOT/'licenses').rglob('*'))]:
        if not source.is_file():continue
        relative=source.relative_to(ROOT) if ROOT/'licenses' in source.parents else Path(source.name)
        target=bundle/relative
        if target.exists() and sha(target)!=sha(source):raise ValueError('Will not replace existing bundle notice')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    branding=verify_pe(bundle/'R6-Rebuild.exe',ROOT/'assets/branding/r6-rebuild.ico')
    for part in ('frontend','data'):
        for file in (bundle/'_internal'/part).rglob('*'):
            if file.is_file() and sha(file)!=sha(ROOT/file.relative_to(bundle/'_internal')):raise ValueError('Resource mismatch')
    if sha(bundle/'_internal/assets/branding/r6-rebuild.ico')!=sha(ROOT/'assets/branding/r6-rebuild.ico'):raise ValueError('Window icon mismatch')
    toc=ast.literal_eval(args.analysis.read_text(encoding='utf-8'))
    entries=[]
    def walk(obj):
        if isinstance(obj,(list,tuple)):
            if len(obj)==3 and all(isinstance(x,str) for x in obj) and obj[2] in ('BINARY','EXTENSION','DATA','PYMODULE','PYSOURCE'):
                name,source,kind=obj
                group='Windows system' if 'windows\\system32' in source.lower() else ('Python environment' if 'site-packages' in source else 'Python or project')
                entries.append({'name':name,'kind':kind,'source_category':group})
            else:
                for child in obj:walk(child)
    walk(toc)
    natives=[]; files={}
    for file in sorted(bundle.rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(bundle).as_posix();files[relative]=sha(file)
        if file.name in ('settings.json','settings.last-valid.json') or file.suffix in ('.log','.pyc'):raise ValueError('Unexpected private/development file')
        if file.suffix.lower() in ('.dll','.pyd','.exe'):
            info={}
            with pefile.PE(str(file),fast_load=False) as pe:
                for group in getattr(pe,'FileInfo',[]):
                    for entry in group:
                        for table in getattr(entry,'StringTable',[]):
                            for key,value in table.entries.items():
                                if key in (b'FileVersion',b'ProductVersion',b'ProductName',b'CompanyName'):
                                    info[key.decode()]=value.decode(errors='replace')
            natives.append({'file':relative,'sha256':files[relative],'version_info':info})
    output={'status':'local candidate; redistribution audit pending','branding':branding,
            'operators':len(list((bundle/'_internal/frontend/assets/operators').glob('*.svg'))),
            'native_files':natives,'analysis_entries':entries,'files_sha256':files}
    report_dir=ROOT/'build/reports'
    report_dir.mkdir(parents=True,exist_ok=True)
    (report_dir/'distribution.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(files),'native_files':len(natives),'branding':branding,'operators':output['operators']}))
if __name__=='__main__':main()
