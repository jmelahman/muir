# muir — My Arch User Repository

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
| `.github/workflows/audit.yml` | PR CI: `triage` → `audit` → `build-check` → `gate` |
| `.github/workflows/terraform.yml` | PR check: `terraform fmt -check` + `validate` (CI-provisioned, no local deps) |
| `terraform/` | repo config: branch protection, labels, auto-merge, Actions vars |
| `contrib/` | seed from installed packages; systemd timer / pacman hook for new installs |

## Audit backend

`tools/audit.py` is provider-pluggable; it picks a backend by `MUIR_AUDIT_BACKEND`
(repo Actions variable) or auto-detects from whichever credential is present:

| Backend | Credential | Notes |
|---|---|---|
| `openrouter` (default) | `OPENROUTER_API_KEY` | OpenAI-compatible, one key → many models. Stdlib only (no install in CI). Set the model via `MUIR_AUDIT_MODEL` (an OpenRouter slug). |
| `claude-cli` | `CLAUDE_CODE_OAUTH_TOKEN` | Headless `claude -p` on your Claude **subscription** — no metered API key. Token from `claude setup-token`. |
| `anthropic` | `ANTHROPIC_API_KEY` | Direct Anthropic API (SDK, structured output, prompt caching). |

A Claude PR *review* (via the Claude GitHub app/action) posts comments but cannot
itself block a merge, so the deterministic `audit.py` exit code stays the gate;
the subscription `claude-cli` backend is how you run that audit without a metered
key.

## Setup

Repository configuration (branch protection, labels, auto-merge, Actions
variables) is managed by Terraform — see [`terraform/`](terraform/). Then:

1. **Seed packages** (one-off, on your Arch box): mirror everything you already
   have installed —
   ```sh
   python tools/sync.py --from-installed --dry-run   # preview
   python tools/sync.py --from-installed             # materialize, then commit + push
   ```
   `--from-installed` reads `pacman -Qmq`, resolves each to its AUR `pkgbase`,
   skips non-AUR packages, and tracks the ones not already mirrored. For a single
   named package use `--add <pkg>`. To keep new installs flowing in as audited
   PRs, set up the systemd timer / pacman hook in [`contrib/`](contrib/).
2. **Secrets** (set with `gh secret set …` — *not* in Terraform state):
   - `MUIR_PR_TOKEN` — PAT with `contents`+`pull-requests` write. Required so
     sync's PRs trigger CI (PRs opened with the default `GITHUB_TOKEN` do not).
   - one backend credential from the table above.
3. **Branch protection** — Terraform requires the single `gate` check (it
   aggregates the per-package matrix jobs) and enables auto-merge.

With this in place: `risk:low` and audit-`clean` PRs satisfy `gate` and
auto-merge; `suspicious`/`malicious` PRs fail `gate`, get the `audit:flagged`
label and a findings comment, and are held until a maintainer acts.

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
