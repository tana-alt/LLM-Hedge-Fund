import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data" / "private"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def config():
    return json.loads((ROOT / "config" / "experiment.json").read_text())


def save(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def digest(obj):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def fail(kind, code, detail):
    return {"status": "failed", "failure_class": kind, "code": code, "detail": str(detail), "at": utc_now()}
