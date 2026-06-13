# miur — My Arch User Repository

A **security-vetting source mirror** of selected AUR packages. A bot detects
upstream AUR updates, opens one PR per update, and CI audits the *diff*: cheap
version bumps flow through automatically, while changes that touch the real
attack surface (sources, checksums, build/install code, dependencies) get a full
LLM security audit and are held for human review if flagged.

## How it works

```
                 hourly cron
 AUR metadata  ────────────────▶  tools/sync.py  ──▶  PR  ──┐
 archive (1 GET)                  (vercmp vs .SRCINFO)       │
                                                            ▼
                                          ┌──────── PR CI (audit.yml) ────────┐
                                          │ triage.py  field-based risk        │
                                          │   risk:low ─────────────▶ pass     │
                                          │   high ─▶ audit.py (Claude)        │
                                          │            clean ──────▶ pass      │
                                          │            flagged ────▶ FAIL +    │
                                          │                          label     │
                                          │ build-check  (secret-free sandbox) │
                                          └────────────────────────────────────┘
```

Each top-level directory holding a `.SRCINFO` is one tracked package. The repo
*is* the mirror state — files are copied verbatim from
`https://aur.archlinux.org/<pkg>.git`.

| Path | Role |
|---|---|
| `<pkg>/` | mirrored `PKGBUILD`, `.SRCINFO`, `*.install`, plus a `.aurmeta` sidecar |
| `tools/sync.py` | detect updates (metadata archive + `vercmp`) and open PRs |
| `tools/triage.py` | deterministic field-based risk classifier |
| `tools/audit.py` | Claude diff audit → structured verdict + PR check |
| `tools/lib/` | `.SRCINFO` parsing, `vercmp`, PKGBUILD function extraction |
| `tools/tests/` | unit tests + fixtures (`python tools/tests/run.py`) |
| `.github/workflows/sync.yml` | scheduled detector |
| `.github/workflows/audit.yml` | PR CI: `triage` → `audit` → `build-check` |

## Setup

1. **Seed packages** (one-off): `python tools/sync.py --add <pkg> [<pkg>...]`,
   then commit the new directories.
2. **Secrets** (repo settings → Secrets):
   - `ANTHROPIC_API_KEY` — used only by the `audit` job.
   - `MIUR_PR_TOKEN` — a PAT with `contents`+`pull-requests` write. Required so
     sync's PRs trigger CI (PRs opened with the default `GITHUB_TOKEN` do not).
3. **Branch protection** on the default branch — require these status checks:
   `audit` and `build-check`, plus CODEOWNERS review. Enable **"Allow
   auto-merge"** in repo settings.
4. **CODEOWNERS** — set the real maintainer handle.

With this in place: `risk:low` and audit-`clean` PRs satisfy all required checks
and auto-merge; `suspicious`/`malicious` PRs fail the `audit` check, get the
`audit:flagged` label and a findings comment, and wait for an owner.

### Security boundary

The `build-check` job executes untrusted PKGBUILD code (`makepkg`, `namcap`) and
therefore has **no secrets** — no `ANTHROPIC_API_KEY`, no write token. The
`audit` job holds the API key but only ever reads the diff as text; it never runs
package code. This keeps a malicious PKGBUILD from exfiltrating credentials.

## Local development

```sh
python tools/tests/run.py          # unit tests (no deps)
python tools/sync.py --dry-run     # detect pending updates, write nothing
python tools/triage.py --old-dir A --new-dir B   # classify a diff
```
