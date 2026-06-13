#!/usr/bin/env python3
"""LLM security audit of an AUR package update diff.

Runs only when triage classifies an update as HIGH-RISK.  Sends the PKGBUILD /
.install diff plus the deterministic triage reasons to Claude and gets back a
structured verdict (clean / suspicious / malicious).  The verdict drives the PR
check: ``clean`` passes (PR stays auto-merge-eligible); anything else fails the
check, posts the findings, and labels the PR for human review.

Fail-closed: any error (missing key, API failure, malformed output) exits
non-zero so a flagged or un-auditable change cannot auto-merge.

Uses the Anthropic SDK (``pip install anthropic``) — this is the only component
that needs it, and it runs in a job that never executes untrusted PKGBUILD code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional

MODEL = "claude-opus-4-8"

# Static, cacheable analyst instructions.  Kept in one frozen block so the
# prompt-cache prefix is stable across the packages audited in a workflow run.
SYSTEM_PROMPT = """\
You are a supply-chain security auditor for an Arch User Repository (AUR) mirror.

You are given the diff of an AUR package update — changes to its PKGBUILD (a bash
script run with user privileges during makepkg), its .install hooks, and its
.SRCINFO metadata — together with a deterministic triage report listing which
fields changed. Your job is to decide whether the *change* is safe to merge.

A PKGBUILD and its install hooks execute arbitrary shell code on the installing
user's machine. Treat this as untrusted code review focused on the delta, not the
whole package. Judge the change, not pre-existing style.

Red flags to weigh (non-exhaustive):
- source= URLs changed to a new/unofficial host, a non-HTTPS scheme, or a URL
  shortener / paste site / raw gist.
- A checksum changed while the corresponding source entry is byte-identical
  (the upstream tarball was swapped in place — a classic backdoor vector).
- New or obfuscated commands in prepare/build/check/package or install hooks:
  curl|bash, wget -O- | sh, base64 -d, eval, xxd, hex/octal escapes, piping
  remote content to a shell, or writing outside $srcdir/$pkgdir.
- Network access during build/package/install (fetching code at build time).
- New dependencies that pull in unexpected tooling, or a new install= hook that
  runs commands on install/upgrade/removal.
- Data exfiltration patterns: posting environment variables, SSH keys, /etc, or
  user files to a remote host.
- A maintainer change combined with any of the above.

A pure version bump (pkgver/pkgrel/epoch) whose source URLs differ only by the
version string and whose checksums move in lockstep is normal and clean.

Be precise and skeptical but not paranoid: do not flag ordinary, well-explained
version bumps. When genuinely uncertain whether a change is benign, prefer
"suspicious" over "clean" so a human reviews it. Cite concrete evidence from the
diff for every finding."""

# JSON Schema for the structured verdict.  Note: numeric range constraints are not
# supported by structured outputs, so risk_score is a plain integer (0-100 by
# instruction) and we clamp/validate client-side.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["clean", "suspicious", "malicious"],
        },
        "risk_score": {
            "type": "integer",
            "description": "0 (clearly safe) to 100 (clearly malicious).",
        },
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "field": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["severity", "field", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "risk_score", "summary", "findings"],
    "additionalProperties": False,
}


def build_user_content(pkg: str, diff: str, triage: dict) -> str:
    reasons = "\n".join(f"- {r}" for r in triage.get("reasons", [])) or "- (none)"
    changed = ", ".join(triage.get("changed_fields", [])) or "(none)"
    return (
        f"Package: {pkg}\n\n"
        f"Triage flagged this update as {triage.get('risk', 'high').upper()}-risk.\n"
        f"Changed .SRCINFO fields: {changed}\n"
        f"Triage reasons:\n{reasons}\n\n"
        f"Unified diff of the update (PKGBUILD / .install / .SRCINFO):\n"
        f"```diff\n{diff}\n```\n\n"
        "Audit this change and return your structured verdict."
    )


def run_audit(pkg: str, diff: str, triage: dict) -> dict:
    import anthropic  # imported here so the module loads without the SDK

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
        },
        # Frozen instructions first → stable cacheable prefix; the per-package
        # diff goes in the volatile user turn after the breakpoint.
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": build_user_content(pkg, diff, triage)}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("audit returned no structured output")
    return json.loads(text)


# -- diff loading --------------------------------------------------------------


def git_diff(pkg: str, base_ref: str) -> str:
    res = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD", "--", pkg],
        capture_output=True,
        text=True,
    )
    return res.stdout


# -- PR reporting --------------------------------------------------------------


def render_markdown(pkg: str, verdict: dict) -> str:
    lines = [
        f"## 🔍 AUR audit — `{pkg}`",
        "",
        f"**Verdict:** `{verdict['verdict']}` (risk score {verdict['risk_score']}/100)",
        "",
        verdict.get("summary", ""),
    ]
    findings = verdict.get("findings", [])
    if findings:
        lines += ["", "| Severity | Field | Finding |", "|---|---|---|"]
        for f in findings:
            expl = f["explanation"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {f['severity']} | `{f['field']}` | {expl} |")
    return "\n".join(lines)


def post_to_pr(pr: str, pkg: str, verdict: dict) -> None:
    """Comment + label a flagged PR via gh (best-effort)."""
    body = render_markdown(pkg, verdict)
    subprocess.run(["gh", "pr", "comment", pr, "--body", body],
                   capture_output=True, text=True)
    subprocess.run(["gh", "pr", "edit", pr, "--add-label", "audit:flagged"],
                   capture_output=True, text=True)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--base-ref", default="origin/master")
    ap.add_argument("--triage", default="triage.json", help="triage.json from triage.py")
    ap.add_argument("--diff-file", help="read diff from a file instead of git")
    ap.add_argument("-o", "--output", default="audit.json")
    ap.add_argument("--pr", help="PR number/URL to comment on + label when flagged")
    args = ap.parse_args(argv)

    with open(args.triage, encoding="utf-8") as fh:
        triage = json.load(fh)

    # Fast-path: low-risk updates skip the LLM entirely. The audit check passes
    # green without needing the API key, keeping the PR auto-merge-eligible.
    if triage.get("risk") != "high":
        print("triage risk is not high; audit skipped (clean fast-path)")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set; failing closed", file=sys.stderr)
        return 2

    diff = (
        open(args.diff_file, encoding="utf-8").read()
        if args.diff_file
        else git_diff(args.pkg, args.base_ref)
    )
    if not diff.strip():
        print("ERROR: empty diff; failing closed", file=sys.stderr)
        return 2

    try:
        verdict = run_audit(args.pkg, diff, triage)
    except Exception as exc:  # noqa: BLE001 — fail closed on any audit error
        print(f"ERROR: audit failed ({exc}); failing closed", file=sys.stderr)
        return 2

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh, indent=2)
        fh.write("\n")

    md = render_markdown(args.pkg, verdict)
    print(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")

    clean = verdict["verdict"] == "clean"
    if not clean and args.pr:
        post_to_pr(args.pr, args.pkg, verdict)

    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
