import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import triage  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _classify(name):
    old = triage._load_dir(os.path.join(FIXTURES, name, "old"))
    new = triage._load_dir(os.path.join(FIXTURES, name, "new"))
    return triage.classify(old, new)


def test_low_bump_is_low_risk():
    result = _classify("low_bump")
    assert result["risk"] == "low", result["reasons"]
    assert result["reasons"] == []


def test_source_host_swap_is_high_risk():
    result = _classify("source_swap")
    assert result["risk"] == "high"
    assert any("host changed" in r for r in result["reasons"])


def test_checksum_change_without_source_change_is_high_risk():
    result = _classify("checksum_only")
    assert result["risk"] == "high"
    assert any("byte-identical" in r for r in result["reasons"])


def test_injected_build_command_is_high_risk():
    result = _classify("malicious_build")
    assert result["risk"] == "high"
    assert any("build() body changed" in r for r in result["reasons"])


def test_dependency_change_is_high_risk():
    old = triage._load_dir(os.path.join(FIXTURES, "low_bump", "old"))
    new = triage._load_dir(os.path.join(FIXTURES, "low_bump", "new"))
    # Inject a new dependency into the new revision only.
    new.srcinfo_text = new.srcinfo_text.replace(
        "\tdepends = glibc\n", "\tdepends = glibc\n\tdepends = curl\n"
    )
    result = triage.classify(old, new)
    assert result["risk"] == "high"
    assert any("dependency field changed" in r for r in result["reasons"])


def test_maintainer_change_flag():
    old = triage._load_dir(os.path.join(FIXTURES, "low_bump", "old"))
    new = triage._load_dir(os.path.join(FIXTURES, "low_bump", "new"))
    result = triage.classify(old, new, maintainer_changed=True)
    assert result["risk"] == "high"
    assert any("maintainer changed" in r for r in result["reasons"])
