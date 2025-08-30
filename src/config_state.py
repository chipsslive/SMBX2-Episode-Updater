from __future__ import annotations

import json
import hashlib
from pathlib import Path

# Base paths
BASE_DIR = Path.cwd()
CONFIG_DIR = BASE_DIR / "user_data"
STATE_DIR = BASE_DIR / "user_data"
CACHE_DIR = BASE_DIR / "user_data/cache"
STATE_PATH = STATE_DIR / "state.json"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Files to not touch when updating
DEFAULT_PRESERVE = ["save*-ext.dat", "save*.sav", "progress.json"]


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def read_config():
    return load_json(CONFIG_PATH, {
        "episodes_dir": "",
        "episode_url": "",
        "preserve_globs": DEFAULT_PRESERVE,
    })


def read_state():
    return load_json(STATE_PATH, {
        "last_zip_name": "",
        "last_zip_sha256": "",
        "install_dir_name": "",
        "installed_at": "",
    })


# Returns True if the path exists and is a directory.
def validate_path_is_dir(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir()
    except Exception:
        return False


# Returns the SHA-256 hash of a file. We can use this to check if the currently downloaded file is any different from the last downloaded file.
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
