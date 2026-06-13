"""Parsing for ``.SRCINFO`` files and Arch version comparison.

``.SRCINFO`` is the machine-readable snapshot of a ``PKGBUILD`` produced by
``makepkg --printsrcinfo``.  Its format is line-oriented ``key = value`` pairs,
grouped into a leading ``pkgbase`` section (the shared/global fields) followed by
one ``pkgname`` section per (split) package.  Keys may repeat (``depends``,
``source``, ``sha256sums`` ...) and may be architecture-suffixed
(``source_x86_64``).

This module is intentionally dependency-free so it can run in the bare
``archlinux:latest`` CI container without ``pip install``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Multi-value keys we care about for triage.  These accumulate into lists.
_MULTI_PREFIXES = (
    "arch",
    "depends",
    "makedepends",
    "checkdepends",
    "optdepends",
    "provides",
    "conflicts",
    "replaces",
    "source",
    "validpgpkeys",
    "noextract",
    "backup",
    "md5sums",
    "sha1sums",
    "sha224sums",
    "sha256sums",
    "sha384sums",
    "sha512sums",
    "b2sums",
)

_CHECKSUM_PREFIXES = (
    "md5sums",
    "sha1sums",
    "sha224sums",
    "sha256sums",
    "sha384sums",
    "sha512sums",
    "b2sums",
)


@dataclass
class SrcInfo:
    """Structured view of a parsed ``.SRCINFO``."""

    pkgbase: str = ""
    # field name -> ordered list of values.  Single-value fields hold one item.
    fields: Dict[str, List[str]] = field(default_factory=dict)
    pkgnames: List[str] = field(default_factory=list)

    # -- convenience accessors -------------------------------------------------

    def get(self, key: str) -> List[str]:
        return self.fields.get(key, [])

    def first(self, key: str, default: str = "") -> str:
        vals = self.fields.get(key)
        return vals[0] if vals else default

    @property
    def pkgver(self) -> str:
        return self.first("pkgver")

    @property
    def pkgrel(self) -> str:
        return self.first("pkgrel")

    @property
    def epoch(self) -> str:
        return self.first("epoch", "")

    @property
    def version(self) -> str:
        """Full ``[epoch:]pkgver-pkgrel`` string used for vercmp."""
        ver = self.pkgver
        if self.pkgrel:
            ver = f"{ver}-{self.pkgrel}"
        if self.epoch:
            ver = f"{self.epoch}:{ver}"
        return ver

    def sources(self) -> List[str]:
        """All ``source`` / ``source_<arch>`` entries, in declared order."""
        out: List[str] = []
        for key, vals in self.fields.items():
            if key == "source" or key.startswith("source_"):
                out.extend(vals)
        return out

    def checksums(self) -> List[str]:
        out: List[str] = []
        for key, vals in self.fields.items():
            if any(key == p or key.startswith(p + "_") for p in _CHECKSUM_PREFIXES):
                out.extend(vals)
        return out

    def depends(self) -> List[str]:
        out: List[str] = []
        for key, vals in self.fields.items():
            for p in ("depends", "makedepends", "checkdepends", "optdepends"):
                if key == p or key.startswith(p + "_"):
                    out.extend(vals)
        return out


def parse(text: str) -> SrcInfo:
    """Parse ``.SRCINFO`` text into a :class:`SrcInfo`."""
    info = SrcInfo()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "pkgbase":
            info.pkgbase = value
            continue
        if key == "pkgname":
            info.pkgnames.append(value)
            continue
        info.fields.setdefault(key, []).append(value)
    return info


def parse_file(path: str) -> SrcInfo:
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())


# -- version comparison --------------------------------------------------------

_VERCMP_BIN = shutil.which("vercmp")


def vercmp(a: str, b: str) -> int:
    """Compare two full versions like pacman's ``vercmp``.

    Returns -1 if ``a < b``, 0 if equal, 1 if ``a > b``.  Prefers the real
    ``vercmp`` binary (exact pacman semantics) and falls back to a faithful
    pure-Python port when it is unavailable (e.g. local dev off-Arch).
    """
    if _VERCMP_BIN:
        res = subprocess.run(
            [_VERCMP_BIN, a, b], capture_output=True, text=True, check=True
        )
        return _clamp(int(res.stdout.strip()))
    return _pyvercmp(a, b)


def _clamp(n: int) -> int:
    return (n > 0) - (n < 0)


def _parse_evr(evr: str):
    """Split ``[epoch:]version[-release]`` like pacman's ``parseEVR``."""
    epoch, sep, rest = evr.partition(":")
    if sep and epoch.isdigit():
        version = rest
    else:
        epoch = "0"
        version = evr
    version, sep, release = version.rpartition("-")
    if not sep:  # no release present
        version, release = release, ""
    return epoch, version, release


def _pyvercmp(a: str, b: str) -> int:
    ea, va, ra = _parse_evr(a)
    eb, vb, rb = _parse_evr(b)
    ret = _rpmvercmp(ea or "0", eb or "0")
    if ret == 0:
        ret = _rpmvercmp(va, vb)
        if ret == 0 and ra and rb:
            ret = _rpmvercmp(ra, rb)
    return _clamp(ret)


def _rpmvercmp(a: str, b: str) -> int:
    """Port of alpm/rpm ``rpmvercmp`` segment comparison."""
    if a == b:
        return 0
    one = list(a)
    two = list(b)
    i = j = 0
    n, m = len(one), len(two)
    while i < n and j < m:
        while i < n and not (one[i].isalnum() or one[i] == "~"):
            i += 1
        while j < m and not (two[j].isalnum() or two[j] == "~"):
            j += 1

        # tilde sorts before everything, including the empty string.
        one_tilde = i < n and one[i] == "~"
        two_tilde = j < m and two[j] == "~"
        if one_tilde or two_tilde:
            if not one_tilde:
                return 1
            if not two_tilde:
                return -1
            i += 1
            j += 1
            continue

        if i >= n or j >= m:
            break

        si, sj = i, j
        if one[i].isdigit():
            while si < n and one[si].isdigit():
                si += 1
            while sj < m and two[sj].isdigit():
                sj += 1
            isnum = True
        else:
            while si < n and one[si].isalpha():
                si += 1
            while sj < m and two[sj].isalpha():
                sj += 1
            isnum = False

        seg_one = "".join(one[i:si])
        seg_two = "".join(two[j:sj])

        # Differing segment types: numeric beats alpha (and alpha beats empty).
        if sj == j:
            return 1 if isnum else -1

        if isnum:
            seg_one = seg_one.lstrip("0") or "0"
            seg_two = seg_two.lstrip("0") or "0"
            if len(seg_one) > len(seg_two):
                return 1
            if len(seg_two) > len(seg_one):
                return -1

        if seg_one != seg_two:
            return -1 if seg_one < seg_two else 1

        i, j = si, sj

    if i >= n and j >= m:
        return 0
    # Trailing tilde on the remainder sorts lower.
    if i < n and one[i] == "~":
        return -1
    if j < m and two[j] == "~":
        return 1
    return 1 if i < n else -1


def is_newer(candidate: str, current: str) -> bool:
    """True if ``candidate`` is a strictly newer version than ``current``."""
    return vercmp(candidate, current) > 0
