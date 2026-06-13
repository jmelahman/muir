import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sync  # noqa: E402

INDEX = {
    # name -> entry, indexed by both Name and PackageBase (as load_archive does)
    "foo": {"Name": "foo", "PackageBase": "foo", "Version": "1-1"},
    "foo-docs": {"Name": "foo-docs", "PackageBase": "foo", "Version": "1-1"},
    "bar-git": {"Name": "bar-git", "PackageBase": "bar-git", "Version": "r5-1"},
}


def test_resolve_bases_maps_split_to_base_and_dedups():
    # foo + foo-docs both resolve to base "foo" -> one entry; order preserved.
    assert sync.resolve_bases(["foo", "foo-docs", "bar-git"], INDEX) == ["foo", "bar-git"]


def test_resolve_bases_skips_non_aur():
    # A locally-built package not in the AUR archive is skipped, not errored.
    assert sync.resolve_bases(["foo", "my-local-pkg"], INDEX) == ["foo"]


def test_resolve_bases_empty():
    assert sync.resolve_bases([], INDEX) == []
