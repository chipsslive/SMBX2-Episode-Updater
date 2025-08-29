import argparse
from smbx2_episode_updater import (
    do_init,
    do_set_url,
    do_set_dir,
    do_check,
    do_update,
    do_show,
)

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