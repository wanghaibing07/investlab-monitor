"""Create the canonical private project archive, preserving old and new evidence.

Source-only GitHub publishing must NEVER use this archive: it contains account data.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import hashlib
import json
import zipfile
from investlab.core import canonical, file_hash, lock
from investlab.storage import backup, verify_archive

p=argparse.ArgumentParser();p.add_argument('--home',required=True);p.add_argument('--output',required=True)
a=p.parse_args();home=Path(a.home).resolve();source=Path(__file__).resolve().parents[1];out=Path(a.output).resolve()
if out.exists():raise SystemExit('Do not overwrite an existing release artifact')
with lock(home), TemporaryDirectory(prefix='package-') as temp:
    snapshot=Path(temp)/'runtime.zip';b=backup(home,snapshot);manifest={}
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(source.rglob('*')):
            if not path.is_file() or any(x in path.parts for x in ('.git','__pycache__','build','dist','.venv')) or any(x.endswith('.egg-info') for x in path.parts):continue
            rel=path.relative_to(source)
            if path.suffix in ('.zip','.sqlite3','.db','.log','.pyc'):raise SystemExit('Unexpected runtime file in source')
            name='investlab/'+rel.as_posix();z.write(path,name);manifest[name]=file_hash(path)
        with zipfile.ZipFile(snapshot) as src:
            inner=verify_archive(snapshot)
            for name in inner['files']:
                payload=src.read(name);dest='runtime/'+name;z.writestr(dest,payload);manifest[dest]=hashlib.sha256(payload).hexdigest()
        readme='''# InvestLab v6.0 私有主文件\n\n本包包含个人账本与研究证据，不上传GitHub。\n源码在investlab/；唯一运行账本在runtime/data/monitor.sqlite3。\n\n安装：python -m pip install ./investlab\n运行：python -m investlab --home ./runtime run --online --independent-check --require-current\n检查：python -m investlab --home ./runtime audit\n短通知：python -m investlab --home ./runtime summary\n\n不要重新init或用目标配置覆盖实际持仓。保留原运行、账户、模型快照与源码版本。后续任务从此布局继续。\n'''.encode()
        z.writestr('README_PRIVATE.md',readme);manifest['README_PRIVATE.md']=hashlib.sha256(readme).hexdigest()
        z.writestr('MANIFEST.json',canonical({'format':'investlab-private-v6','files':manifest}))
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist())==set(manifest)|{'MANIFEST.json'}
        for name,h in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==h,name
out.chmod(0o600)
print(json.dumps({'path':str(out),'sha256':file_hash(out),'files':len(manifest),'contains_private_state':True}))
