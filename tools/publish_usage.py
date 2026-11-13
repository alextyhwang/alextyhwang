"""Render and publish the public T3 usage charts from the local T3 feed.

Only ``spend`` is read from ``t3plus-home.json``. The other feed fields never
enter the temporary checkout or the output branch.

    python tools/publish_usage.py
    python tools/publish_usage.py --feed C:/path/to/t3plus-home.json
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_FEED = pathlib.Path.home() / ".t3" / "userdata" / "tailnet-files" / "t3plus-home.json"
ASSETS = ("usage-dark.svg", "usage-light.svg", "cost-dark.svg", "cost-light.svg")
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def run(args, cwd=None, quiet=False):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=quiet, text=True)


def config(key, fallback):
    try:
        value = run((GIT, "-C", str(ROOT), "config", "--get", key), quiet=True).stdout.strip()
    except subprocess.CalledProcessError:
        value = ""
    return value or fallback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", type=pathlib.Path, default=DEFAULT_FEED)
    args = parser.parse_args()
    feed = args.feed.expanduser().resolve()
    if not feed.is_file():
        raise SystemExit(f"T3 usage feed not found: {feed}")

    with tempfile.TemporaryDirectory(prefix="alextyhwang-usage-") as work:
        rendered = pathlib.Path(work) / "rendered"
        run((sys.executable, str(ROOT / "tools" / "render.py"), "usage", str(rendered), "--feed", str(feed)))

        checkout = pathlib.Path(work) / "output"
        remote = run((GIT, "-C", str(ROOT), "remote", "get-url", "origin"), quiet=True).stdout.strip()
        run((GIT, "clone", "--depth", "1", "--branch", "output", remote, str(checkout)), quiet=True)
        for name in ASSETS:
            shutil.copyfile(rendered / name, checkout / name)
        run((GIT, "-C", str(checkout), "config", "user.name", config("user.name", "Alex Tyh Wang")))
        run((GIT, "-C", str(checkout), "config", "user.email", config("user.email", "41898282+alextyhwang@users.noreply.github.com")))
        run((GIT, "-C", str(checkout), "add", *ASSETS))
        changed = subprocess.run((GIT, "-C", str(checkout), "diff", "--cached", "--quiet"))
        if changed.returncode == 0:
            print("T3 usage charts unchanged")
            return 0
        run((GIT, "-C", str(checkout), "commit", "-m", "Update T3 usage charts"), quiet=True)
        run((GIT, "-C", str(checkout), "push", "origin", "output"), quiet=True)
        print("Published T3 usage charts: " + ", ".join(ASSETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
