from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from fnmatch import fnmatch

from config_state import CACHE_DIR, sha256_file
from logger import get_logger

logger = get_logger(__name__)


def safe_join(base: Path, *parts) -> Path:
    # Prevent zip path traversal
    p = (base / Path(*parts)).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise RuntimeError("Blocked path traversal while extracting")
    return p


def unzip_to_stage(zip_path: Path) -> tuple[Path, str | None]:
    stage_root = CACHE_DIR / "stage" / sha256_file(zip_path)
    logger.debug(f"Extracting to stage: {stage_root}")
    
    if stage_root.exists():
        logger.debug("Stage already exists, reusing")
        # Determine wrapper folder if there's exactly one top-level directory
        try:
            children = [p for p in stage_root.iterdir()]
            if len(children) == 1 and children[0].is_dir():
                return children[0], children[0].name
            return stage_root, None
        except Exception as e:
            logger.warning(f"Error checking existing stage: {e}")
            return stage_root, None
    
    logger.info(f"Extracting ZIP file: {zip_path}")
    stage_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            total_files = len([zi for zi in zf.infolist() if not zi.filename.endswith("/")])
            logger.info(f"Extracting {total_files} files from ZIP")
            
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
    except Exception as e:
        logger.error(f"Failed to extract ZIP file: {e}")
        raise

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
    logger.debug(f"Finding episode root in: {stage}")
    
    # Top-level check
    try:
        wld_files = [p for p in stage.iterdir() if p.is_file() and p.suffix.lower() == ".wld"]
        if wld_files:
            logger.info(f"Found {len(wld_files)} .wld files at top level, using stage as root")
            return stage
    except Exception as e:
        logger.warning(f"Error checking top-level files: {e}")

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
        root = candidates[0][1]
        logger.info(f"Found episode root at depth {candidates[0][0]}: {root}")
        return root

    # Fallback
    logger.warning("No .wld files found, using stage as fallback")
    return stage


def _glob_preserved(path: Path, globs: list[str], base: Path) -> bool:
    rel = str(path.relative_to(base)).replace("\\", "/")
    for g in globs:
        if fnmatch(rel, g):
            return True
    return False


def inventory_hashes(root: Path) -> dict[str, str]:
    from config_state import sha256_file as _sha

    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            out[rel] = _sha(p)
    return out


def merge_stage_into_install(stage: Path, install_dir: Path, preserve: list[str], on_progress=None) -> list[str]:
    """Merge files from stage into install_dir.

    If provided, on_progress is called as on_progress(phase, rel, idx, total)
    where phase is 'write' or 'delete', rel is the relative path, idx is 1-based,
    and total is the total number of operations.
    """
    logger.info(f"Merging from {stage} to {install_dir}")
    changed = []
    install_dir.mkdir(parents=True, exist_ok=True)

    logger.debug("Computing file inventories...")
    stage_map = inventory_hashes(stage)
    target_map = inventory_hashes(install_dir)
    logger.info(f"Stage has {len(stage_map)} files, target has {len(target_map)} files")

    # Plan operations for accurate total
    ops = []  # list of (phase, rel)
    for rel, hsh in stage_map.items():
        dst = install_dir / rel
        if _glob_preserved(dst, preserve, install_dir):
            continue
        old = target_map.get(rel)
        if old is None:
            ops.append(("write", rel))
        elif old != hsh:
            ops.append(("write", rel))
    for rel in target_map.keys():
        if rel not in stage_map:
            dst = install_dir / rel
            if not _glob_preserved(dst, preserve, install_dir):
                ops.append(("delete", rel))

    total = len(ops)
    logger.info(f"Planned {total} operations ({len([op for op in ops if op[0] == 'write'])} writes, {len([op for op in ops if op[0] == 'delete'])} deletes)")
    idx = 0

    # Execute writes
    for phase, rel in ops:
        if phase == "write":
            src = stage / rel
            dst = install_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst)
                changed.append(rel)
        else:  # delete
            dst = install_dir / rel
            try:
                if dst.exists():
                    dst.unlink()
                    changed.append(rel)
            except Exception as e:
                logger.warning(f"Failed to delete {dst}: {e}")

        idx += 1
        if on_progress:
            try:
                on_progress(phase, rel, idx, total)
            except Exception as e:
                logger.debug(f"Progress callback failed: {e}")

    # Clean up empty folders
    for p in sorted(install_dir.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_dir():
            try:
                next(p.iterdir())
            except StopIteration:
                try:
                    p.rmdir()
                except Exception as e:
                    logger.debug(f"Failed to remove empty directory {p}: {e}")

    logger.info(f"Merge complete. {len(changed)} files changed.")
    return changed


def create_backup(install_dir: Path) -> Path:
    import hashlib

    logger.info(f"Creating backup of: {install_dir}")
    backups = CACHE_DIR / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = hashlib.sha1(str(install_dir).encode("utf-8")).hexdigest()[:8]
    out = backups / f"backup_{install_dir.name}_{stamp}.zip"
    
    try:
        files_to_backup = [p for p in install_dir.rglob("*") if p.is_file()]
        logger.debug(f"Backing up {len(files_to_backup)} files to {out}")
        
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for p in files_to_backup:
                try:
                    zf.write(p, arcname=str(p.relative_to(install_dir)))
                except Exception as e:
                    logger.warning(f"Failed to backup file {p}: {e}")
        
        logger.info(f"Backup created: {out} ({out.stat().st_size} bytes)")
        return out
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        raise
