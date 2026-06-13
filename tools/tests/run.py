#!/usr/bin/env python3
"""Zero-dependency test runner (so tests run without pytest installed).

Discovers ``test_*`` functions in ``test_*.py`` modules in this directory and
runs them.  CI may instead use ``pytest tools/tests`` — these tests are written
to work under both.
"""

import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path):
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    passed = failed = 0
    failures = []
    for fn in sorted(os.listdir(HERE)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        mod = _load(os.path.join(HERE, fn))
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            func = getattr(mod, name)
            if not callable(func):
                continue
            try:
                func()
                passed += 1
                print(f"PASS {fn}::{name}")
            except Exception:  # noqa: BLE001
                failed += 1
                failures.append((fn, name, traceback.format_exc()))
                print(f"FAIL {fn}::{name}")
    print(f"\n{passed} passed, {failed} failed")
    for fn, name, tb in failures:
        print(f"\n=== {fn}::{name} ===\n{tb}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
