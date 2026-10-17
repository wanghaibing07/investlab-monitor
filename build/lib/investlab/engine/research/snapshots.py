"""Content-addressed, compressed evidence; the facts behind a signal remain replayable."""
import hashlib
import json
import zlib
from .common import ROOT,DATA_ROOT,digest
from .dataset import semantic_content

def ensure_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS research_data_snapshots (
        data_sha256 TEXT PRIMARY KEY,identity_basis TEXT NOT NULL,
        registered_at TEXT NOT NULL,dataset_zlib BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS research_shadow_observations (
        observation_id TEXT PRIMARY KEY,
        signal_id TEXT NOT NULL REFERENCES research_shadow_signals(signal_id),
        observed_at TEXT NOT NULL,data_vintage_sha256 TEXT NOT NULL,
        data_sha256 TEXT REFERENCES research_data_snapshots(data_sha256));''')

    columns={r[1] for r in c.execute('PRAGMA table_info(research_shadow_observations)')}
    if 'data_sha256' not in columns:
        c.execute('ALTER TABLE research_shadow_observations ADD COLUMN data_sha256 TEXT')
        c.execute("UPDATE research_shadow_observations SET data_sha256=(SELECT json_extract(signal_json,'$.data_sha256') FROM research_shadow_signals WHERE research_shadow_signals.signal_id=research_shadow_observations.signal_id)")


def archive(c,data,created_at):
    content=semantic_content(data);sha=digest(content)
    if sha!=data['data_sha256']:raise ValueError('Signal dataset identity mismatch')
    payload=json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    c.execute('INSERT OR IGNORE INTO research_data_snapshots VALUES(?,?,?,?)',
              (sha,'SEMANTIC_PRICES_V1',created_at,zlib.compress(payload,9)))
    return sha

def import_matching_legacy(c):
    path=DATA_ROOT/'research/versions/v5_0/historical_dataset.json'
    if not path.exists():return
    data=json.loads(path.read_text('utf8'));content={k:data[k] for k in ('dates','QQQ','TQQQ')};sha=digest(content)
    if not c.execute('SELECT 1 FROM research_shadow_signals WHERE json_extract(signal_json,\'$.data_sha256\')=?',(sha,)).fetchone():return
    payload=json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    c.execute('INSERT OR IGNORE INTO research_data_snapshots VALUES(?,?,?,?)',
              (sha,'V5_VINTAGE_HASH',data['QQQ'][-1].get('fetched_at','LEGACY_ARCHIVE'),zlib.compress(payload,9)))

def read(c,sha):
    row=c.execute('SELECT identity_basis,dataset_zlib FROM research_data_snapshots WHERE data_sha256=?',(sha,)).fetchone()
    if not row:return None
    try:data=json.loads(zlib.decompress(row[1]))
    except (ValueError,zlib.error) as exc:raise ValueError('Corrupt dataset evidence snapshot') from exc
    computed=digest(semantic_content(data)) if row[0]=='SEMANTIC_PRICES_V1' else digest(data)
    if computed!=sha:raise ValueError('Dataset evidence snapshot hash mismatch')
    return data

def source_hash(sources):
    return digest({name:hashlib.sha256(value.encode()).hexdigest() for name,value in sources.items()})
