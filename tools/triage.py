#!/usr/bin/env python3
"""Field-based risk triage for an AUR package update.

Compares the *old* and *new* revision of a package (PKGBUILD + .SRCINFO +
install scripts) and decides whether the change is a cheap, mechanical version
bump (``risk:low`` — skip the LLM) or touches the real attack surface
(``HIGH`` — run the full LLM audit).

This is deterministic, dependency-free, and runs first in PR CI.  It emits a
``triage.json`` consumed by the audit step.

Usage:
    triage.py --old-dir OLD --new-dir NEW [--maintainer-changed] [-o triage.json]
    triage.py --pkg NAME --base-ref REF   [-o triage.json]   # reads OLD from git
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import pkgbuild, srcinfo  # noqa: E402

# Dependency-style fields: any change here is high-risk.
_DEP_PREFIXES = ("depends", "makedepends", "checkdepends", "optdepends")
# Metadata fields whose change can alter what is installed/removed on the system.
_SYSTEM_PREFIXES = ("conflicts", "replaces")


@dataclass
class PkgRevision:
    """One revision of a package's security-relevant files."""

    pkgbuild: str = ""
    srcinfo_text: str = ""
    installs: Dict[str, str] = field(default_factory=dict)  # filename -> content

    @property
    def info(self) -> srcinfo.SrcInfo:
        return srcinfo.parse(self.srcinfo_text)


def classify(old: PkgRevision, new: PkgRevision, maintainer_changed: bool = False) -> dict:
    """Return ``{risk, changed_fields, reasons}`` for an old -> new update."""
    oi, ni = old.info, new.info
    reasons: List[str] = []

    # --- version sanity -------------------------------------------------------
    if oi.version and ni.version and srcinfo.vercmp(ni.version, oi.version) <= 0:
        reasons.append(
            f"version does not increase ({oi.version!r} -> {ni.version!r}); "
            "possible downgrade or replay"
        )

    # --- sources & checksums --------------------------------------------------
    old_src, new_src = oi.sources(), ni.sources()
    old_sums, new_sums = oi.checksums(), ni.checksums()
    raw_source_unchanged = old_src == new_src
    sums_changed = old_sums != new_sums

    if len(old_src) != len(new_src):
        reasons.append("source entries added or removed")
    else:
        norm_old = [_normalize_source(s, oi.pkgver) for s in old_src]
        norm_new = [_normalize_source(s, ni.pkgver) for s in new_src]
        if norm_old != norm_new:
            reasons.append("source URL changed beyond a version substitution")
        # Host change is the loudest signal — report it explicitly.
        for a, b in zip(old_src, new_src):
            ha, hb = _host(a), _host(b)
            if ha != hb:
                reasons.append(f"source host changed: {ha or '(local)'} -> {hb or '(local)'}")

    if sums_changed and raw_source_unchanged and old_src:
        reasons.append(
            "checksums changed while source entries are byte-identical "
            "(possible upstream tarball swap)"
        )

    # --- build-time function bodies ------------------------------------------
    old_fns = pkgbuild.build_function_bodies(old.pkgbuild)
    new_fns = pkgbuild.build_function_bodies(new.pkgbuild)
    for name in sorted(set(old_fns) | set(new_fns)):
        if old_fns.get(name) != new_fns.get(name):
            reasons.append(f"{name}() body changed")

    # --- dependencies & system-altering metadata ------------------------------
    changed_fields = _changed_fields(oi, ni)
    for key in changed_fields:
        if any(key == p or key.startswith(p + "_") for p in _DEP_PREFIXES):
            reasons.append(f"dependency field changed: {key}")
        elif any(key == p or key.startswith(p + "_") for p in _SYSTEM_PREFIXES):
            reasons.append(f"system metadata changed: {key}")
        elif key == "arch":
            reasons.append("arch changed")
        elif key == "validpgpkeys":
            reasons.append("validpgpkeys changed")
        elif key == "install":
            reasons.append("install= directive changed")

    # --- install scripts ------------------------------------------------------
    for name in sorted(set(old.installs) | set(new.installs)):
        if old.installs.get(name) != new.installs.get(name):
            reasons.append(f"install script changed: {name}")

    # --- split-package set ----------------------------------------------------
    if set(oi.pkgnames) != set(ni.pkgnames):
        reasons.append("set of produced packages (pkgname) changed")

    if maintainer_changed:
        reasons.append("AUR maintainer changed")

    risk = "high" if reasons else "low"
    return {
        "risk": risk,
        "changed_fields": changed_fields,
        "reasons": reasons,
    }


def _changed_fields(oi: srcinfo.SrcInfo, ni: srcinfo.SrcInfo) -> List[str]:
    keys = set(oi.fields) | set(ni.fields)
    return sorted(k for k in keys if oi.fields.get(k) != ni.fields.get(k))


def _split_url(entry: str) -> str:
    """Return the URL/path part of a ``name::url`` or bare ``source`` entry."""
    return entry.split("::", 1)[1] if "::" in entry else entry


def _normalize_source(entry: str, pkgver: str) -> str:
    """Replace the embedded version so pure version bumps compare equal."""
    url = _split_url(entry)
    if pkgver:
        url = url.replace(pkgver, "${V}")
    return url


def _host(entry: str) -> str:
    url = _split_url(entry)
    parsed = urlparse(url)
    if parsed.scheme in ("", "file") and "://" not in url:
        return ""  # local file reference
    # Strip any VCS scheme prefix like git+https.
    return parsed.netloc


# -- file loading --------------------------------------------------------------


def _load_dir(path: str) -> PkgRevision:
    rev = PkgRevision()
    pb = os.path.join(path, "PKGBUILD")
    si = os.path.join(path, ".SRCINFO")
    if os.path.exists(pb):
        rev.pkgbuild = _read(pb)
    if os.path.exists(si):
        rev.srcinfo_text = _read(si)
    for name in os.listdir(path) if os.path.isdir(path) else []:
        if name.endswith(".install"):
            rev.installs[name] = _read(os.path.join(path, name))
    return rev


def _load_git(pkg: str, ref: str) -> PkgRevision:
    """Load a revision from ``git show REF:pkg/<file>`` (base branch in CI)."""
    rev = PkgRevision()
    rev.pkgbuild = _git_show(f"{ref}:{pkg}/PKGBUILD")
    rev.srcinfo_text = _git_show(f"{ref}:{pkg}/.SRCINFO")
    for name in _git_ls(ref, pkg):
        if name.endswith(".install"):
            rev.installs[os.path.basename(name)] = _git_show(f"{ref}:{name}")
    return rev


def _git_show(spec: str) -> str:
    res = subprocess.run(["git", "show", spec], capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else ""


def _git_ls(ref: str, pkg: str) -> List[str]:
    res = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, f"{pkg}/"],
        capture_output=True,
        text=True,
    )
    return res.stdout.splitlines() if res.returncode == 0 else []


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-dir")
    ap.add_argument("--new-dir")
    ap.add_argument("--pkg", help="package dir name (git mode)")
    ap.add_argument("--base-ref", help="git ref holding the old revision")
    ap.add_argument("--maintainer-changed", action="store_true")
    ap.add_argument("-o", "--output", help="write triage.json here")
    args = ap.parse_args(argv)

    if args.old_dir and args.new_dir:
        old = _load_dir(args.old_dir)
        new = _load_dir(args.new_dir)
    elif args.pkg and args.base_ref:
        old = _load_git(args.pkg, args.base_ref)
        new = _load_dir(args.pkg)
    else:
        ap.error("provide --old-dir/--new-dir or --pkg/--base-ref")

    result = classify(old, new, maintainer_changed=args.maintainer_changed)
    text = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
