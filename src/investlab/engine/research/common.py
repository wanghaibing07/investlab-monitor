import hashlib
import json
from pathlib import Path
import monitor
ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = monitor.DATA_ROOT
PROTOCOL = ROOT / 'research/protocol.json'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def read_protocol():
    p = json.loads(PROTOCOL.read_text('utf8'))
    lock = DATA_ROOT / 'research/protocol_lock.json'
    if lock.exists() and json.loads(lock.read_text())['protocol_sha256'] != digest(p):
        raise ValueError('Protocol changed after freeze; register a new research version')
    return p

def write_json(path, value):
    monitor.atomic_write(Path(path), json.dumps(value, ensure_ascii=False,
                         indent=2, allow_nan=False).encode())

def code_sources():
    files=sorted((ROOT/'research').glob('*.py'))+sorted((ROOT/'research').glob('*.json'))+[ROOT/'strategy.py',ROOT/'monitor.py',ROOT/'strategy_config.json',ROOT/'advisory.py',ROOT/'advisory_policy.json',ROOT/'web_extract.py']
    return {str(p.relative_to(ROOT)):p.read_text('utf8') for p in files}

def code_hash():
    return digest({name:hashlib.sha256(value.encode()).hexdigest() for name,value in code_sources().items()})
