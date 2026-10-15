"""Check actual Git candidates, including forcibly tracked ignored files."""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
allowed_data = {"src/investlab/engine/data/research/protocol_lock.json"}
try:
    listing = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root)
    paths = sorted({root / p.decode() for p in listing.split(b"\0") if p})
except (OSError, subprocess.CalledProcessError):
    paths = [p for p in root.rglob("*") if p.is_file() and not any(x in p.parts for x in (".git", "__pycache__", ".venv", "build", "dist")) and not any(x.endswith(".egg-info") for x in p.parts)]
errors = []
for p in paths:
    if not p.is_file():
        continue  # A tracked deletion is absent from the candidate tree.
    rel = p.relative_to(root).as_posix()
    if p.is_symlink():
        errors.append("symlink: " + rel); continue
    if p.suffix in (".sqlite3", ".db", ".zip", ".log", ".pyc", ".pem", ".key", ".p12", ".pfx") or p.name.startswith("monitor.sqlite3"):
        errors.append("runtime/key artifact: " + rel)
    if (p.name == ".env" or p.name.startswith(".env.")) and p.name != ".env.example":
        errors.append("environment secrets: " + rel)
    if "/data/" in "/" + rel and rel not in allowed_data:
        errors.append("unexpected data: " + rel)
    if any(part in {"runtime", "private", "backups", "__pycache__", ".venv"} for part in p.relative_to(root).parts):
        errors.append("private/runtime directory: " + rel)
    if p.suffix in (".py", ".json", ".md", ".yml", ".yaml", ".html", ".js", ".toml", ".txt", ".css", ".service", ".timer") or p.name.startswith(".env"):
        text = p.read_text("utf8")
        for pattern in (r"177682" + r"1759@", r"sk-[A-Za-z0-9]{24,}", r"gh[pousr]_[A-Za-z0-9]{25,}", r"BEGIN (?:RSA |OPENSSH )?PRIVATE KEY"):
            if re.search(pattern, text): errors.append("sensitive pattern: " + rel)
if errors:
    print("\n".join(sorted(set(errors)))); sys.exit(1)
print("PASS: Git release candidates exclude personal state, credentials and private backups")
