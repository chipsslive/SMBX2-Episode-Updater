"""Public module consumed by both CLI and GUI.

This file now delegates core logic to `core/` modules and re-exports the
public API expected by the GUI (e.g., ensure_dirs, read_config, unzip_to_stage).
"""

import argparse
import json
import sys
from pathlib import Path
from logger import setup_logging, get_logger
from download import (
    download_zip,
    probe_remote_metadata,
)
from config_state import (
    STATE_PATH,
    CONFIG_PATH,
    DEFAULT_PRESERVE,
    ensure_dirs,
    read_config,
    read_state,
    save_json,
    validate_path_is_dir,
)
from zip_merge import (
    unzip_to_stage,
    find_episode_root,
    merge_stage_into_install,
    create_backup,
)

# Initialize logging
logger = get_logger(__name__)

def do_init(args):
    ensure_dirs()
    cfg = read_config()

    episodes_dir = Path(args.episodes_dir).expanduser().resolve() if args.episodes_dir else None
    if not episodes_dir or not validate_path_is_dir(episodes_dir):
        logger.error(f"Episodes folder was not found at the path {args.episodes_dir}. If you do not have SMBX2, install it here:")
        logger.info("https://codehaus.moe/smbx2")  # Show a link only. Do not open browser automatically.
        sys.exit(2)

    if not args.episode_url:
        logger.error("You must pass --episode-url to set the distributor ZIP link.")
        sys.exit(2)

    cfg["episodes_dir"] = str(episodes_dir)
    cfg["episode_url"] = args.episode_url
    if not cfg.get("preserve_globs"):
        cfg["preserve_globs"] = DEFAULT_PRESERVE
    save_json(CONFIG_PATH, cfg)
    logger.info(f"Config saved to {CONFIG_PATH}.")

def do_set_url(args):
    ensure_dirs()
    cfg = read_config()
    if not args.episode_url:
        logger.error("Missing --episode-url")
        sys.exit(2)
    cfg["episode_url"] = args.episode_url
    save_json(CONFIG_PATH, cfg)
    logger.info(f"URL updated in {CONFIG_PATH}.")

def do_set_dir(args):
    ensure_dirs()
    cfg = read_config()
    episodes_dir = Path(args.episodes_dir).expanduser().resolve()
    if not validate_path_is_dir(episodes_dir):
        logger.error(f"Episodes folder was not found at the path {args.episodes_dir}.")
        sys.exit(2)
    cfg["episodes_dir"] = str(episodes_dir)
    save_json(CONFIG_PATH, cfg)
    logger.info(f"Episodes directory updated in {CONFIG_PATH}.")

def do_check(args):
    ensure_dirs()
    cfg = read_config()
    if not cfg["episode_url"]:
        logger.error("No episode_url set. Run init or set-url.")
        sys.exit(2)
    try:
        url = cfg["episode_url"]
        name, size = probe_remote_metadata(url)
        logger.info(f"Remote file: {name} ({size} bytes)")
    except Exception as e:
        logger.error(f"Check failed: {e}")
        sys.exit(1)

def do_update(args):
    ensure_dirs()
    cfg = read_config()
    st = read_state()

    if not cfg["episodes_dir"] or not cfg["episode_url"]:
        logger.error("Config incomplete. Run init first.")
        sys.exit(2)

    episodes_dir = Path(cfg["episodes_dir"])
    if not validate_path_is_dir(episodes_dir):
        logger.error(f"Episodes folder was not found at the path {cfg['episodes_dir']}. Fix with set-dir.")
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
            logger.info(f"Will perform fresh install to {install_dir}")
            install_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Performing fresh install... (This part may take a bit.)")
            changed = merge_stage_into_install(episode_root, install_dir, cfg.get("preserve_globs") or [])
        else:
            logger.info(f"Will merge into existing {install_dir}")
            logger.info("Creating backup of previous installation...")
            backup = create_backup(install_dir)
            logger.info(f"Backup created with name: {backup.name}")
            logger.info("Performing merge... (This part may take a bit.)")
            changed = merge_stage_into_install(episode_root, install_dir, cfg.get("preserve_globs") or [])

        logger.info("Recording state...")

        st["last_zip_name"] = server_name
        st["last_zip_sha256"] = sha
        st["install_dir_name"] = target_name
        st["installed_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        save_json(STATE_PATH, st)

        logger.info(f"Done. {len(changed)} files changed.")
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

def make_parser():
    p = argparse.ArgumentParser(prog="ctl", description="SMBX2 episode updater controller")
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
    sp.add_argument("--install-name", help="Override the target folder name under episodes dir", required=False)
    sp.set_defaults(func=do_update)

    sp = sub.add_parser("show", help="print current config and state")
    sp.set_defaults(func=do_show)

    return p

def main():
    # Initialize logging for CLI
    setup_logging()
    try:
        args = make_parser().parse_args()
        args.func(args)
    except KeyboardInterrupt:
        logger.info("Cancelled by user.")
        sys.exit(130)

if __name__ == "__main__":
    main()
