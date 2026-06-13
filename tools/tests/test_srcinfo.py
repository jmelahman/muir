import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import srcinfo  # noqa: E402


def test_parse_basic():
    text = (
        "pkgbase = demo\n"
        "\tpkgver = 1.2.3\n"
        "\tpkgrel = 2\n"
        "\tepoch = 1\n"
        "\tarch = x86_64\n"
        "\tdepends = glibc\n"
        "\tdepends = zlib\n"
        "\tsource = https://example.com/demo-1.2.3.tar.gz\n"
        "\tsha256sums = abc\n"
        "pkgname = demo\n"
    )
    info = srcinfo.parse(text)
    assert info.pkgbase == "demo"
    assert info.pkgver == "1.2.3"
    assert info.pkgrel == "2"
    assert info.epoch == "1"
    assert info.version == "1:1.2.3-2"
    assert info.get("depends") == ["glibc", "zlib"]
    assert info.sources() == ["https://example.com/demo-1.2.3.tar.gz"]
    assert info.checksums() == ["abc"]
    assert info.pkgnames == ["demo"]


def test_per_arch_fields_collected():
    text = (
        "pkgbase = demo\n"
        "\tsource = base.tar.gz\n"
        "\tsource_x86_64 = https://example.com/x86.tar.gz\n"
        "\tsha256sums_x86_64 = deadbeef\n"
        "pkgname = demo\n"
    )
    info = srcinfo.parse(text)
    assert "https://example.com/x86.tar.gz" in info.sources()
    assert info.checksums() == ["deadbeef"]


def test_pyvercmp_matches_known_orderings():
    cases = [
        ("1.0.0", "1.0.1", -1),
        ("1.0.1", "1.0.0", 1),
        ("1.0.0", "1.0.0", 0),
        ("1.0.0-1", "1.0.0-2", -1),
        ("1:1.0", "2.0", 1),          # epoch dominates
        ("1.0.0", "1.0.0.1", -1),
        ("1.0", "1.0a", -1),          # alpha after the shared numeric prefix
        ("1.0~rc1", "1.0", -1),       # tilde sorts before release
        ("r100", "r99", 1),           # numeric length/value
    ]
    for a, b, want in cases:
        assert srcinfo._pyvercmp(a, b) == want, (a, b)
        assert srcinfo._pyvercmp(b, a) == -want, (b, a)


def test_is_newer():
    assert srcinfo.is_newer("2.0.0", "1.9.9")
    assert not srcinfo.is_newer("1.0.0", "1.0.0")
    assert not srcinfo.is_newer("1.0.0", "1.0.1")
