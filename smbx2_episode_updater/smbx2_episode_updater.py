# smbx2_episode_updater.py
# Minimal CLI updater for SMBX2 episodes.
# Dependencies: requests, tqdm

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from fnmatch import fnmatch
from .download_helpers.download import (
    download_zip,
    probe_remote_metadata,
)
 

APP_NAME = "smbx2_episode_updater"

BASE_DIR = Path.cwd()
CONFIG_DIR = BASE_DIR / "config"
STATE_DIR = BASE_DIR / "state"
CACHE_DIR = BASE_DIR / "cache"
STATE_PATH = STATE_DIR / "state.json"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PRESERVE = []

def log(s: str):
    print(s, flush=True)

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
        "preserve_globs": DEFAULT_PRESERVE
    })

def write_config(cfg):
    save_json(CONFIG_PATH, cfg)

def read_state():
    return load_json(STATE_PATH, {
        "last_zip_name": "",
        "last_zip_sha256": "",
        "install_dir_name": "",
        "installed_at": ""
    })

def write_state(st):
    save_json(STATE_PATH, st)

def validate_path_is_dir(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir()
    except Exception:
        return False

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_join(base: Path, *parts) -> Path:
    # Prevent zip path traversal
    p = (base / Path(*parts)).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise RuntimeError("Blocked path traversal while extracting")
    return p

def unzip_to_stage(zip_path: Path) -> Path:
    stage_root = CACHE_DIR / "stage" / sha256_file(zip_path)
    if stage_root.exists():
        return stage_root
    stage_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for zi in zf.infolist():
            # Block absolute paths and traversal
            name = zi.filename
            if name.endswith("/"):
                # directory entry
                out_dir = safe_join(stage_root, name)
                out_dir.mkdir(parents=True, exist_ok=True)
                continue
            # normalize to forward slashes from zip
            parts = Path(name)
            out_file = safe_join(stage_root, parts)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, open(out_file, "wb") as dst:
                shutil.copyfileobj(src, dst)

    # If contents are flat files, keep as-is. If a single top folder, collapse to that folder for consistency.
    children = [p for p in stage_root.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return stage_root

def _glob_preserved(path: Path, globs: list[str], base: Path) -> bool:
    rel = str(path.relative_to(base)).replace("\\", "/")
    for g in globs:
        if fnmatch(rel, g):
            return True
    return False

def inventory_hashes(root: Path) -> dict[str, str]:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            out[rel] = sha256_file(p)
    return out

def merge_stage_into_install(stage: Path, install_dir: Path, preserve: list[str]) -> list[str]:
    changed = []
    install_dir.mkdir(parents=True, exist_ok=True)

    stage_map = inventory_hashes(stage)
    target_map = inventory_hashes(install_dir)

    # Copy or update files
    for rel, hsh in stage_map.items():
        src = stage / rel
        dst = install_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            if not _glob_preserved(dst, preserve, install_dir):
                shutil.copy2(src, dst)
                changed.append(rel)
            continue
        # Exists. Compare hash.
        old = target_map.get(rel)
        if old != hsh and not _glob_preserved(dst, preserve, install_dir):
            shutil.copy2(src, dst)
            changed.append(rel)

    # Deletions: remove files that existed before but do not exist in stage
    for rel in target_map.keys():
        if rel not in stage_map:
            dst = install_dir / rel
            if not _glob_preserved(dst, preserve, install_dir):
                try:
                    dst.unlink()
                    changed.append(rel)
                except Exception:
                    pass

    # Clean up empty folders
    for p in sorted(install_dir.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_dir():
            try:
                next(p.iterdir())
            except StopIteration:
                try:
                    p.rmdir()
                except Exception:
                    pass

    return changed

def create_backup(install_dir: Path) -> Path:
    backups = CACHE_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = hashlib.sha1(str(install_dir).encode("utf-8")).hexdigest()[:8]
    out = backups / f"backup_{install_dir.name}_{stamp}.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in install_dir.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(install_dir)))
    return out

def do_init(args):
    ensure_dirs()
    cfg = read_config()

    episodes_dir = Path(args.episodes_dir).expanduser().resolve() if args.episodes_dir else None
    if not episodes_dir or not validate_path_is_dir(episodes_dir):
        log(f"Episodes folder was not found at the path {args.episodes_dir}. If you do not have SMBX2, install it here:")
        log("https://codehaus.moe/smbx2")  # Show a link only. Do not open browser automatically.
        sys.exit(2)

    if not args.episode_url:
        log("You must pass --episode-url to set the distributor ZIP link.")
        sys.exit(2)

    cfg["episodes_dir"] = str(episodes_dir)
    cfg["episode_url"] = args.episode_url
    if not cfg.get("preserve_globs"):
        cfg["preserve_globs"] = DEFAULT_PRESERVE
    write_config(cfg)
    log(f"Config saved to {CONFIG_PATH}.")

def do_set_url(args):
    ensure_dirs()
    cfg = read_config()
    if not args.episode_url:
        log("Missing --episode-url")
        sys.exit(2)
    cfg["episode_url"] = args.episode_url
    write_config(cfg)
    log(f"URL updated in {CONFIG_PATH}.")

def do_set_dir(args):
    ensure_dirs()
    cfg = read_config()
    episodes_dir = Path(args.episodes_dir).expanduser().resolve()
    if not validate_path_is_dir(episodes_dir):
        log(f"Episodes folder was not found at the path {args.episodes_dir}.")
        sys.exit(2)
    cfg["episodes_dir"] = str(episodes_dir)
    write_config(cfg)
    log(f"Episodes directory updated in {CONFIG_PATH}.")

def do_check(args):
    ensure_dirs()
    cfg = read_config()
    if not cfg["episode_url"]:
        log("No episode_url set. Run init or set-url.")
        sys.exit(2)
    try:
        url = cfg["episode_url"]
        name, size = probe_remote_metadata(url)
        log(f"Remote file: {name} ({size} bytes)")
    except Exception as e:
        log(f"Check failed: {e}")
        sys.exit(1)

def do_update(args):
    ensure_dirs()
    cfg = read_config()
    st = read_state()

    if not cfg["episodes_dir"] or not cfg["episode_url"]:
        log("Config incomplete. Run init first.")
        sys.exit(2)

    episodes_dir = Path(cfg["episodes_dir"])
    if not validate_path_is_dir(episodes_dir):
        log(f"Episodes folder was not found at the path {cfg['episodes_dir']}. Fix with set-dir.")
        sys.exit(2)

    zip_path, server_name, sha = download_zip(cfg["episode_url"])
    try:
        stage = unzip_to_stage(zip_path)
        # Folder name rule: use the zip filename without extension
        target_name = Path(server_name).stem
        install_dir = episodes_dir / target_name

        if not install_dir.exists():
            log(f"Fresh install to {install_dir}")
            install_dir.mkdir(parents=True, exist_ok=True)
            changed = merge_stage_into_install(stage, install_dir, cfg.get("preserve_globs") or [])
        else:
            log(f"Merging into existing {install_dir}")
            backup = create_backup(install_dir)
            log(f"Backup created: {backup.name}")
            changed = merge_stage_into_install(stage, install_dir, cfg.get("preserve_globs") or [])

        st["last_zip_name"] = server_name
        st["last_zip_sha256"] = sha
        st["install_dir_name"] = target_name
        st["installed_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        write_state(st)

        log(f"Done. {len(changed)} files changed.")
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass

def do_show(args):
    ensure_dirs()
    cfg = read_config()
    st = read_state()
    print("Config:")
    print(json.dumps(cfg, indent=2))
    print("State:")
    print(json.dumps(st, indent=2))

def make_parser():
    p = argparse.ArgumentParser(prog="smbx2-updater", description="SMBX2 episode updater")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="set episodes dir and distributor URL")
    sp.add_argument("--episodes-dir", required=True, help="Path to SMBX2 episodes directory")
    sp.add_argument("--episode-url", required=True, help="Direct download URL of episode zip")
    sp.set_defaults(func=do_init)

    sp = sub.add_parser("set-url", help="update distributor URL")
    sp.add_argument("--episode-url", required=True)
    sp.set_defaults(func=do_set_url)

    sp = sub.add_parser("set-dir", help="update episodes dir")
    sp.add_argument("--episodes-dir", required=True)
    sp.set_defaults(func=do_set_dir)

    sp = sub.add_parser("check", help="print remote filename and size")
    sp.set_defaults(func=do_check)

    sp = sub.add_parser("update", help="download and install or merge")
    sp.set_defaults(func=do_update)

    sp = sub.add_parser("show", help="print current config and state")
    sp.set_defaults(func=do_show)

    return p

def main():
    try:
        parser = make_parser()
        args = parser.parse_args()
        args.func(args)
    except KeyboardInterrupt:
        log("Cancelled by user.")
        sys.exit(130)

if __name__ == "__main__":
    main()
