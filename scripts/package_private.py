"""Package private runtime state; GitHub remains the only working source tree.

Historical model source inside evidence snapshots is retained for replay.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import hashlib
import json
import re
import zipfile
from investlab.core import canonical, file_hash, lock
from investlab.storage import backup, verify_archive

p=argparse.ArgumentParser()
p.add_argument('--home',required=True)
p.add_argument('--output',required=True)
p.add_argument('--repository',required=True,help='Verified public GitHub repository URL')
p.add_argument('--revision',required=True,help='Full verified Git commit SHA')
a=p.parse_args()
if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',a.repository):
    raise SystemExit('Expected a canonical public GitHub repository URL')
if not re.fullmatch(r'[0-9a-f]{40}',a.revision):
    raise SystemExit('Expected an exact 40-character commit SHA')
home=Path(a.home).resolve();out=Path(a.output).resolve()
if out.exists():raise SystemExit('Do not overwrite an existing release artifact')
with lock(home), TemporaryDirectory(prefix='package-') as temp:
    snapshot=Path(temp)/'runtime.zip';backup(home,snapshot);manifest={}
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        with zipfile.ZipFile(snapshot) as src:
            inner=verify_archive(snapshot)
            for name in inner['files']:
                payload=src.read(name);dest='runtime/'+name
                z.writestr(dest,payload);manifest[dest]=hashlib.sha256(payload).hexdigest()
        source=canonical({'repository':a.repository,'revision':a.revision,'source_policy':'GITHUB_CANONICAL_RUNTIME_PRIVATE'}).encode()
        z.writestr('SOURCE.json',source);manifest['SOURCE.json']=hashlib.sha256(source).hexdigest()
        readme=('''# InvestLab 私有运行数据\n\n本包包含个人账本和研究证据，不上传GitHub。工作源码只在GitHub保存。\nSOURCE.json固定本包对应的仓库及完整提交；runtime/data/monitor.sqlite3是事实账本。\n\n取回源码：\n  git clone '''+a.repository+''' investlab\n  git -C investlab checkout --detach '''+a.revision+'''\n  python -m pip install ./investlab\n运行：python -m investlab --home ./runtime run --online --independent-check --require-current\n检查：python -m investlab --home ./runtime audit\n通知：python -m investlab --home ./runtime summary\n\n不要重新init、不要把目标或建议写成成交。模型证据里的历史源码保留用于重放，不能代替SOURCE.json指向的工作源码。\n''').encode()
        z.writestr('README_PRIVATE.md',readme);manifest['README_PRIVATE.md']=hashlib.sha256(readme).hexdigest()
        z.writestr('MANIFEST.json',canonical({'format':'investlab-private-v6','files':manifest}))
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist())==set(manifest)|{'MANIFEST.json'}
        for name,h in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==h,name
out.chmod(0o600)
print(json.dumps({'path':str(out),'sha256':file_hash(out),'files':len(manifest),'contains_private_state':True,'source_revision':a.revision}))
