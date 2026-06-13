import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audit  # noqa: E402


def _clear_env(monkeysetenv=None):
    for k in ("MIUR_AUDIT_BACKEND", "OPENROUTER_API_KEY",
              "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        os.environ.pop(k, None)


def test_resolve_backend_explicit_override():
    _clear_env()
    os.environ["MIUR_AUDIT_BACKEND"] = "claude-cli"
    os.environ["OPENROUTER_API_KEY"] = "x"  # ignored when forced
    try:
        assert audit.resolve_backend() == "claude-cli"
    finally:
        _clear_env()


def test_resolve_backend_priority_openrouter_first():
    _clear_env()
    os.environ["OPENROUTER_API_KEY"] = "x"
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "y"
    os.environ["ANTHROPIC_API_KEY"] = "z"
    try:
        assert audit.resolve_backend() == "openrouter"
    finally:
        _clear_env()


def test_resolve_backend_subscription_when_only_token():
    _clear_env()
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "y"
    try:
        assert audit.resolve_backend() == "claude-cli"
    finally:
        _clear_env()


def test_resolve_backend_none_raises():
    _clear_env()
    try:
        audit.resolve_backend()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_extract_json_plain():
    assert audit._extract_json('{"verdict": "clean"}') == {"verdict": "clean"}


def test_extract_json_fenced():
    text = 'Here you go:\n```json\n{"verdict": "malicious"}\n```\n'
    assert audit._extract_json(text) == {"verdict": "malicious"}


def test_extract_json_embedded():
    text = 'preamble {"verdict": "suspicious", "risk_score": 70} trailing'
    assert audit._extract_json(text)["risk_score"] == 70


def test_validate_accepts_and_fills_defaults():
    v = {"verdict": "clean"}
    audit._validate(v)
    assert v["risk_score"] == 0 and v["findings"] == []


def test_validate_rejects_bad_verdict():
    for bad in ({}, {"verdict": "fine"}, "nope", None):
        try:
            audit._validate(bad)
            assert False, f"expected RuntimeError for {bad!r}"
        except RuntimeError:
            pass


def test_render_markdown_includes_findings():
    md = audit.render_markdown("demo", {
        "verdict": "malicious",
        "risk_score": 95,
        "summary": "bad",
        "findings": [{"severity": "critical", "field": "build", "explanation": "curl|bash"}],
    })
    assert "critical" in md and "`build`" in md and "95/100" in md
