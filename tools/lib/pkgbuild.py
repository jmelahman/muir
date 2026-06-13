"""Lightweight extraction of shell function bodies from a ``PKGBUILD``.

We are not a full bash parser; we only need to know whether the body of a
build-time function (``prepare`` / ``build`` / ``check`` / ``package`` /
``pkgver``) changed between two revisions.  A brace-matching scan that respects
quotes and ``#`` comments is sufficient and avoids running untrusted code.
"""

from __future__ import annotations

import re
from typing import Dict

# Matches ``name() {`` or ``function name {`` at the start of a (stripped) line.
_FUNC_RE = re.compile(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_:-]*)\s*\(\s*\)\s*\{")

# Functions whose bodies execute during makepkg and define the attack surface.
BUILD_FUNCTIONS = ("prepare", "build", "check", "package", "pkgver")


def extract_functions(text: str) -> Dict[str, str]:
    """Return a mapping of ``func_name -> body`` for top-level functions.

    Split-package PKGBUILDs use ``package_<pkgname>()``; those are captured
    under their full name so a change to any of them is still detected.
    """
    out: Dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        m = _FUNC_RE.match(stripped)
        if not m:
            i += 1
            continue
        name = m.group(1)
        # Start counting braces from the opening one on this line.
        depth = _net_braces(lines[i])
        body_lines = [lines[i]]
        i += 1
        while i < n and depth > 0:
            body_lines.append(lines[i])
            depth += _net_braces(lines[i])
            i += 1
        out[name] = "\n".join(body_lines)
    return out


def _net_braces(line: str) -> int:
    """Net ``{`` minus ``}`` on a line, ignoring quoted/commented braces."""
    depth = 0
    quote: str | None = None
    prev = ""
    for ch in line:
        if quote:
            if ch == quote and prev != "\\":
                quote = None
            prev = ch
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            break  # rest of line is a comment
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        prev = ch
    return depth


def build_function_bodies(text: str) -> Dict[str, str]:
    """Only the security-relevant build functions (incl. ``package_*`` splits)."""
    funcs = extract_functions(text)
    return {
        name: body
        for name, body in funcs.items()
        if name in BUILD_FUNCTIONS
        or any(name.startswith(p + "_") for p in BUILD_FUNCTIONS)
    }
