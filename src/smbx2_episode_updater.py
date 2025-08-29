# smbx2_episode_updater.py
# Minimal CLI updater for SMBX2 episodes.
# Dependencies: requests, tqdm

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from fnmatch import fnmatch
from download import (
    download_zip,
    probe_remote_metadata,
)
import ctl

APP_NAME = "smbx2_episode_updater"

BASE_DIR = Path.cwd()
CONFIG_DIR = BASE_DIR / "data"
STATE_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "data/cache"
STATE_PATH = STATE_DIR / "state.json"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Files to not touch when updating
DEFAULT_PRESERVE = ["save*-ext.dat", "save*.sav","progress.json"]

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

def read_state():
    return load_json(STATE_PATH, {
        "last_zip_name": "",
        "last_zip_sha256": "",
        "install_dir_name": "",
        "installed_at": ""
    })

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

def unzip_to_stage(zip_path: Path) -> tuple[Path, str | None]:
    stage_root = CACHE_DIR / "stage" / sha256_file(zip_path)
    if stage_root.exists():
        # Determine wrapper folder if there's exactly one top-level directory
        try:
            children = [p for p in stage_root.iterdir()]
            if len(children) == 1 and children[0].is_dir():
                return children[0], children[0].name
            return stage_root, None
        except Exception:
            return stage_root, None
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
        return children[0], children[0].name
    return stage_root, None

def find_episode_root(stage: Path) -> Path:
    """Return the directory that directly contains a *.wld file.

    Heuristics:
    - If stage itself contains any *.wld at top-level, use stage.
    - Else search for any *.wld in subtree and pick the shallowest containing directory.
    - If none found, fall back to stage.
    """
    # Top-level check
    try:
        for p in stage.iterdir():
            if p.is_file() and p.suffix.lower() == ".wld":
                return stage
    except Exception:
        pass

    # Find shallowest *.wld in subtree
    candidates = []
    for p in stage.rglob("*.wld"):
        try:
            rel = p.relative_to(stage)
            depth = len(rel.parts)
            candidates.append((depth, p.parent))
        except Exception:
            candidates.append((9999, p.parent))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # Fallback
    return stage

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
    save_json(CONFIG_PATH, cfg)
    log(f"Config saved to {CONFIG_PATH}.")

def do_set_url(args):
    ensure_dirs()
    cfg = read_config()
    if not args.episode_url:
        log("Missing --episode-url")
        sys.exit(2)
    cfg["episode_url"] = args.episode_url
    save_json(CONFIG_PATH, cfg)
    log(f"URL updated in {CONFIG_PATH}.")

def do_set_dir(args):
    ensure_dirs()
    cfg = read_config()
    episodes_dir = Path(args.episodes_dir).expanduser().resolve()
    if not validate_path_is_dir(episodes_dir):
        log(f"Episodes folder was not found at the path {args.episodes_dir}.")
        sys.exit(2)
    cfg["episodes_dir"] = str(episodes_dir)
    save_json(CONFIG_PATH, cfg)
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
        stage, wrapper_name_opt = unzip_to_stage(zip_path)
        # Pick directory that contains the episode's *.wld as root
        episode_root = find_episode_root(stage)
        # Always use the exact directory name that contains the .wld file
        target_name = episode_root.name
        install_dir = episodes_dir / target_name

        if not install_dir.exists():
            log(f"Will perform fresh install to {install_dir}")
            install_dir.mkdir(parents=True, exist_ok=True)
            log("Performing fresh install... (This part may take a bit.)")
            changed = merge_stage_into_install(episode_root, install_dir, cfg.get("preserve_globs") or [])
        else:
            log(f"Will merge into existing {install_dir}")
            log("Creating backup of previous installation...")
            backup = create_backup(install_dir)
            log(f"Backup created with name: {backup.name}")
            log("Performing merge... (This part may take a bit.)")
            changed = merge_stage_into_install(episode_root, install_dir, cfg.get("preserve_globs") or [])

        log("Recording state...")

        st["last_zip_name"] = server_name
        st["last_zip_sha256"] = sha
        st["install_dir_name"] = target_name
        st["installed_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        save_json(STATE_PATH, st)

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
    print("The config contains info about where episode data is stored and where to get it from.")
    print("Config:")
    print(json.dumps(cfg, indent=2))
    print("The state contains info about the last update.")
    print("State:")
    print(json.dumps(st, indent=2))

def main():
    try:
        args = ctl.make_parser().parse_args()
        args.func(args)
    except KeyboardInterrupt:
        log("Cancelled by user.")
        sys.exit(130)

if __name__ == "__main__":
    main()
