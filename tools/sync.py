#!/usr/bin/env python3
"""Detect upstream AUR updates and open one PR per outdated package.

The repo is the mirror state: each top-level directory holding a ``.SRCINFO`` is
a tracked package.  Detection uses the AUR metadata archive
(``packages-meta-ext-v1.json.gz``) — a single conditional request that covers
every package and is the AUR-blessed alternative to hammering the RPC.

Modes:
    sync.py                 # detect + (with --open-prs) open update PRs
    sync.py --dry-run       # report what would happen, touch nothing
    sync.py --add NAME ...  # seed new package dir(s) from upstream AUR

Dependency-free (stdlib only) so it runs in a bare container.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import srcinfo  # noqa: E402

ARCHIVE_URL = "https://aur.archlinux.org/packages-meta-ext-v1.json.gz"
AUR_GIT = "https://aur.archlinux.org/{pkg}.git"
META_FILE = ".aurmeta"  # per-package sidecar: {"maintainer": ..., "commit": ...}


# -- metadata archive ----------------------------------------------------------


def load_archive(cache_dir: Optional[str] = None) -> Dict[str, dict]:
    """Fetch the AUR metadata archive (conditional on cached ETag).

    Returns a mapping ``pkgbase/Name -> entry``.  Honors ``ETag`` so repeated
    runs only re-download when the archive actually changed.
    """
    etag_path = os.path.join(cache_dir, "archive.etag") if cache_dir else None
    body_path = os.path.join(cache_dir, "archive.json.gz") if cache_dir else None

    headers = {"User-Agent": "miur-sync"}
    if etag_path and os.path.exists(etag_path) and body_path and os.path.exists(body_path):
        with open(etag_path) as fh:
            headers["If-None-Match"] = fh.read().strip()

    req = Request(ARCHIVE_URL, headers=headers)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
            etag = resp.headers.get("ETag")
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
                with open(body_path, "wb") as fh:
                    fh.write(raw)
                if etag:
                    with open(etag_path, "w") as fh:
                        fh.write(etag)
    except Exception as exc:  # noqa: BLE001
        # 304 Not Modified surfaces as HTTPError in urllib; reuse cache.
        if body_path and os.path.exists(body_path):
            with open(body_path, "rb") as fh:
                raw = fh.read()
        else:
            raise RuntimeError(f"failed to fetch AUR archive: {exc}") from exc

    data = json.loads(gzip.decompress(raw))
    index: Dict[str, dict] = {}
    for entry in data:
        # Index by both Name and PackageBase so either lookup resolves.
        for key in (entry.get("Name"), entry.get("PackageBase")):
            if key:
                index.setdefault(key, entry)
    return index


# -- repo state ----------------------------------------------------------------


def tracked_packages(repo_root: str) -> List[str]:
    """Top-level dirs containing a ``.SRCINFO`` — the mirror's tracked set."""
    out = []
    for name in sorted(os.listdir(repo_root)):
        if name.startswith("."):
            continue
        path = os.path.join(repo_root, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, ".SRCINFO")):
            out.append(name)
    return out


def local_version(repo_root: str, pkg: str) -> str:
    return srcinfo.parse_file(os.path.join(repo_root, pkg, ".SRCINFO")).version


def local_maintainer(repo_root: str, pkg: str) -> Optional[str]:
    meta = os.path.join(repo_root, pkg, META_FILE)
    if os.path.exists(meta):
        try:
            with open(meta) as fh:
                return json.load(fh).get("maintainer")
        except (OSError, ValueError):
            return None
    return None


# -- upstream fetch ------------------------------------------------------------


def fetch_upstream(pkg: str, dest: str) -> str:
    """Shallow-clone the AUR package repo into ``dest``; return HEAD commit."""
    subprocess.run(
        ["git", "clone", "--depth", "1", AUR_GIT.format(pkg=pkg), dest],
        check=True,
        capture_output=True,
        text=True,
    )
    commit = subprocess.run(
        ["git", "-C", dest, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit


def upstream_files(clone_dir: str) -> List[str]:
    """All git-tracked files in the clone (PKGBUILD, .SRCINFO, install/patches)."""
    res = subprocess.run(
        ["git", "-C", clone_dir, "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [f for f in res.stdout.splitlines() if f and f != ".gitignore"]


def materialize(clone_dir: str, target: str, entry: Optional[dict], commit: str) -> None:
    """Copy the upstream tracked files verbatim into ``target`` + write sidecar."""
    if os.path.isdir(target):
        # Replace mirrored files but keep our sidecar handling explicit.
        for name in os.listdir(target):
            if name == META_FILE:
                continue
            p = os.path.join(target, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    else:
        os.makedirs(target, exist_ok=True)
    for rel in upstream_files(clone_dir):
        src = os.path.join(clone_dir, rel)
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    with open(os.path.join(target, META_FILE), "w") as fh:
        json.dump(
            {"maintainer": (entry or {}).get("Maintainer"), "commit": commit},
            fh,
            indent=2,
        )
        fh.write("\n")


# -- git / PR helpers ----------------------------------------------------------


def branch_name(pkg: str, version: str) -> str:
    safe = version.replace(":", "-").replace("/", "-")
    return f"update/{pkg}/{safe}"


def pr_exists(branch: str) -> bool:
    res = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "number"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return False
    try:
        return len(json.loads(res.stdout)) > 0
    except ValueError:
        return False


def branch_exists_remote(branch: str) -> bool:
    res = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


# -- update flow ---------------------------------------------------------------


def detect(repo_root: str, index: Dict[str, dict]) -> List[dict]:
    """Return a list of pending updates with old/new versions."""
    updates = []
    for pkg in tracked_packages(repo_root):
        entry = index.get(pkg)
        if not entry:
            print(f"WARN {pkg}: not found in AUR archive (orphaned/renamed?)", file=sys.stderr)
            continue
        new_ver = entry.get("Version", "")
        cur_ver = local_version(repo_root, pkg)
        if new_ver and srcinfo.is_newer(new_ver, cur_ver):
            updates.append(
                {
                    "pkg": pkg,
                    "old_version": cur_ver,
                    "new_version": new_ver,
                    "maintainer": entry.get("Maintainer"),
                    "old_maintainer": local_maintainer(repo_root, pkg),
                    "entry": entry,
                }
            )
    return updates


def open_update_pr(repo_root: str, update: dict, base: str = "master") -> Optional[str]:
    pkg = update["pkg"]
    branch = branch_name(pkg, update["new_version"])
    if pr_exists(branch) or branch_exists_remote(branch):
        print(f"SKIP {pkg}: PR/branch {branch} already exists")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        clone = os.path.join(tmp, pkg)
        commit = fetch_upstream(pkg, clone)
        subprocess.run(["git", "-C", repo_root, "checkout", "-B", branch, base],
                       check=True, capture_output=True, text=True)
        materialize(clone, os.path.join(repo_root, pkg), update["entry"], commit)

    subprocess.run(["git", "-C", repo_root, "add", "-A", pkg], check=True)
    msg = f"{pkg}: {update['old_version']} -> {update['new_version']}"
    subprocess.run(["git", "-C", repo_root, "commit", "-m", msg],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", repo_root, "push", "-u", "origin", branch],
                   check=True, capture_output=True, text=True)

    body = _pr_body(update)
    res = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--head", branch,
         "--title", msg, "--body", body],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        print(f"ERROR creating PR for {pkg}: {res.stderr}", file=sys.stderr)
        return None
    url = res.stdout.strip()
    # Let GitHub auto-merge once required checks (triage/audit/build) pass.
    subprocess.run(["gh", "pr", "merge", "--auto", "--squash", branch],
                   capture_output=True, text=True)
    print(f"PR {pkg}: {url}")
    return url


def _pr_body(update: dict) -> str:
    maint_note = ""
    if update.get("old_maintainer") and update["maintainer"] != update["old_maintainer"]:
        maint_note = (
            f"\n\n⚠️ **Maintainer changed**: "
            f"`{update['old_maintainer']}` → `{update['maintainer']}`"
        )
    return (
        f"Automated AUR sync for **{update['pkg']}**.\n\n"
        f"- Version: `{update['old_version']}` → `{update['new_version']}`\n"
        f"- Maintainer: `{update.get('maintainer')}`\n"
        f"{maint_note}\n\n"
        "CI will triage the diff and run the LLM audit if it touches the attack "
        "surface (sources, checksums, build/install code, dependencies)."
    )


def add_packages(repo_root: str, names: List[str], index: Dict[str, dict]) -> None:
    """Seed new tracked package dirs from upstream AUR (one-off, see plan)."""
    for pkg in names:
        with tempfile.TemporaryDirectory() as tmp:
            clone = os.path.join(tmp, pkg)
            commit = fetch_upstream(pkg, clone)
            materialize(clone, os.path.join(repo_root, pkg), index.get(pkg), commit)
        print(f"ADDED {pkg}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=os.getcwd())
    ap.add_argument("--cache-dir", default=os.environ.get("MIUR_CACHE", ".cache"))
    ap.add_argument("--base", default="master")
    ap.add_argument("--dry-run", action="store_true",
                    help="report pending updates without writing anything")
    ap.add_argument("--open-prs", action="store_true",
                    help="actually create branches/PRs for pending updates")
    ap.add_argument("--add", nargs="+", metavar="PKG",
                    help="seed new package dir(s) from upstream AUR and exit")
    args = ap.parse_args(argv)

    index = load_archive(args.cache_dir)

    if args.add:
        add_packages(args.repo_root, args.add, index)
        return 0

    updates = detect(args.repo_root, index)
    if not updates:
        print("up to date")
        return 0

    print(f"{len(updates)} update(s) pending:")
    for u in updates:
        print(f"  {u['pkg']}: {u['old_version']} -> {u['new_version']}")

    if args.dry_run or not args.open_prs:
        if not args.dry_run:
            print("\n(use --open-prs to create PRs)")
        return 0

    for u in updates:
        open_update_pr(args.repo_root, u, base=args.base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
