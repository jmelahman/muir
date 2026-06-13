# muir — AUR Mirror with LLM-Audited Update PRs

## Context

`muir` ("My Arch User Repository") should be a **security-vetting source mirror** of a chosen set
of AUR packages. AUR packages are arbitrary bash scripts (`PKGBUILD` + `.install` hooks) that run
with the user's privileges during `makepkg`, so the real value of a mirror is a **supply-chain
gate**: every time an upstream package changes, the change should be reviewed before it lands.

Goal: a bot detects upstream AUR updates, opens one PR per update copying the new PKGBUILD into the
repo, and CI audits the *diff*. Cheap version bumps flow through automatically; changes that touch
the actual attack surface (sources, checksums, build/install code, dependencies) get a full LLM
audit and are held for a human if the audit flags them.

### Decisions locked with the user
- **Package scope**: directory-presence model — each top-level dir (`/<pkgname>/`) is one tracked package. Adding a dir adds a package; the repo *is* the mirror state.
- **Mirror type**: source only (PKGBUILD + `.SRCINFO` + `*.install`). No building/serving binaries. Matches the existing `.gitignore` (`pkg/`, `src/`, `*.tar.*`, `*.sig` ignored).
- **Audit triage**: field-based risk triage (not dependency-only). The LLM audit is the expensive path, gated by *which fields changed*.
- **Merge policy**: auto-merge audit-clean PRs; hold flagged PRs for human review.

### Recommended stack (defaults — flag at approval if you want different)
- **CI/PR host**: GitHub Actions. Jobs run in an `archlinux:latest` container for `vercmp`, `makepkg --printsrcinfo`, `namcap`.
- **Tooling language**: Python 3 (AUR JSON + Claude SDK + GitHub API).
- **LLM**: Anthropic Claude API (`anthropic` SDK, structured/tool output, prompt caching). See the `claude-api` skill for SDK conventions.

## Repo layout

```
<pkgname>/PKGBUILD             # mirrored verbatim from upstream AUR
<pkgname>/.SRCINFO             # encodes synced epoch:pkgver-pkgrel (this IS the version state)
<pkgname>/*.install           # if the package has install hooks
tools/sync.py                 # detect updates -> open one PR per package
tools/triage.py               # field-based risk classifier (pure code, no LLM)
tools/audit.py                # Claude diff audit -> structured verdict + PR check
tools/lib/srcinfo.py          # .SRCINFO parser + vercmp wrapper + field extraction
tools/tests/                  # fixtures: low-risk bump, source swap, injected malicious build()
.github/workflows/sync.yml    # scheduled detector (cron)
.github/workflows/audit.yml   # PR CI: triage -> audit -> build-check -> auto-merge gate
CODEOWNERS                    # require human review on flagged PRs
```

No checksum/`.SRCINFO` regeneration: we mirror upstream's committed files **verbatim** and only
*verify* that `.SRCINFO` matches `PKGBUILD`. This keeps the mirror faithful and avoids us mutating
package metadata.

## Component 1 — Detection & PR creation (`tools/sync.py`, `sync.yml`)

Scheduled workflow (default hourly cron).

1. **Bulk detect (one request for all packages)**: conditional `GET https://aur.archlinux.org/packages-meta-ext-v1.json.gz` using a stored `ETag`/`Last-Modified` (cached via `actions/cache`). Archive refreshes ~5 min and is the AUR-blessed way to avoid hammering the RPC. (RPC `type=info` is the fallback for individual lookups.)
2. For each tracked dir, read local synced version from its `.SRCINFO` (`pkgver`/`pkgrel`/`epoch`) and compare to the archive's `Version` using **`vercmp`** (correct epoch/pkgrel ordering).
3. For each outdated package: `git clone https://aur.archlinux.org/<pkg>.git`, check out the new revision, copy `PKGBUILD`/`.SRCINFO`/`*.install` into `<pkg>/` on branch `update/<pkg>/<newver>`.
4. Open **one PR per package** via `gh`/GitHub API. Idempotent: skip if that branch or an open PR for `<newver>` already exists. Enable GitHub **auto-merge** on the PR (it will only fire once required checks pass).

Reuse note: tools like Renovate / `aur-auto-update` solve version bumping for *your own* AUR packages via `nvchecker`; we don't need their checksum-rewrite machinery because we mirror verbatim — the metadata archive + `vercmp` covers detection for the whole AUR in one shot.

## Component 2 — Field-based risk triage (`tools/triage.py`)

Runs first in PR CI. Pure code, deterministic, no LLM cost. Parses old vs new `.SRCINFO` (machine
-readable) and diffs `PKGBUILD`/`*.install` to classify changed fields.

- **LOW-RISK fast-path** (skip LLM): *only* `pkgver`/`pkgrel`/`epoch` changed **AND** every `source` entry is identical except the embedded version string (same host + path shape) **AND** `*sums` changed in lockstep with sources **AND** no change to any function body (`prepare/build/package/check/pkgver`) or `*.install`. → label `risk:low`.
- **HIGH-RISK** → full LLM audit. Triggered by any of: changed `source*`; changed `*sums` **without** a corresponding source change (sneaky tarball swap — important signal); new/changed `depends`/`makedepends`/`checkdepends`/`optdepends`; any change to `prepare/build/package/check/pkgver` bodies; new/changed `install=` or `.install` contents; changed `arch`/`validpgpkeys`; maintainer/packager change.

Emits `triage.json` (`{risk, changed_fields[], reasons[]}`) consumed by the audit step.

## Component 3 — LLM audit (`tools/audit.py`)

Only runs when triage says HIGH-RISK.

- **Inputs**: unified diff of `PKGBUILD` + `*.install`, the `.SRCINFO` field-level diff, old/new `source` URLs, maintainer delta, and `triage.json` reasons. Use prompt caching for the static system prompt.
- **Structured output** (tool/JSON schema): `{verdict: "clean"|"suspicious"|"malicious", risk_score: 0-100, findings: [{severity, field, explanation}], summary}`.
- **Red flags the prompt targets**: new source hosts / non-HTTPS / non-official mirrors; checksum change without source change; obfuscated or encoded commands (`base64`, `eval`, hex); `curl|bash` / network fetches inside `build()`/`package()`/install hooks; writes outside `$srcdir`/`$pkgdir`; data-exfiltration patterns; suspicious new dependencies; install-hook command injection.
- **Outcome → GitHub check**: `clean` → check passes (PR stays auto-merge-eligible). `suspicious`/`malicious` → check **fails**, findings posted as a PR comment, label `audit:flagged`. CODEOWNERS requires a human approval, so a failed/flagged PR cannot auto-merge.

## Component 4 — Build verification (`audit.yml`, isolated job)

Defense-in-depth, no LLM:
- `makepkg --printsrcinfo` and assert it equals the committed `.SRCINFO` (catches tampering/mismatch).
- `namcap PKGBUILD` for lint.
- Optional sandboxed `makepkg -s` in an ephemeral container.

**Security boundary (call this out in implementation):** any job that *executes* PKGBUILD code
(build verification) runs in an isolated container with **no repository secrets**. The
`ANTHROPIC_API_KEY` and `GITHUB_TOKEN` live only in the audit/sync jobs, which read the diff as text
and never run untrusted package code. This prevents a malicious PKGBUILD from exfiltrating secrets
via CI.

## Auto-merge gate (`audit.yml`)

Branch protection requires: `triage`, `audit` (or `risk:low` skip), and `build-check` to pass plus
CODEOWNERS review for `audit:flagged`. Flow:
- `risk:low` → audit skipped, build-check passes → auto-merge fires, no human.
- HIGH-RISK + `clean` → auto-merge fires.
- HIGH-RISK + `suspicious`/`malicious` → check fails + `audit:flagged` → blocked until a human reviews and approves.

## Secrets / config
- `ANTHROPIC_API_KEY` (repo secret, audit job only).
- `GITHUB_TOKEN`/PAT with PR write + auto-merge.
- Optional `tools/config.yml`: cron interval, model id, risk thresholds, per-package overrides (e.g. force-full-audit list).

## Verification

1. **Unit — triage** (`tools/tests/`): fixtures for (a) pure pkgver bump → `risk:low`; (b) source host swap → HIGH; (c) checksum change w/ unchanged source → HIGH; (d) injected `curl … | bash` in `build()` → HIGH. Assert `triage.json` classification.
2. **Unit — audit**: feed fixture (d) diff to `audit.py` against the API → expect `verdict != clean` and a finding citing the network call; feed a clean bump diff → `verdict == clean`.
3. **Dry-run sync**: run `sync.py --dry-run` against 2–3 small real AUR packages seeded as dirs; confirm it detects a real outdated one and would open the right branch/PR (no writes).
4. **End-to-end on GitHub**:
   - Seed one package, hand-open a PR with a benign version bump → expect `risk:low`, build-check green, auto-merge.
   - Open a PR injecting a malicious `build()` → expect `audit:flagged`, failing check, comment with findings, merge blocked.
5. Confirm the build-verification job has **no** access to `ANTHROPIC_API_KEY` (inspect job env / try a deliberate secret echo and confirm it's empty).

## Open follow-ups (not blocking)
- Initial seeding of the package dirs (manual `git clone` of the first batch, or a one-off `sync.py --add <pkg>`).
- Whether to also `vercmp`-gate downgrades (reject upstream version going backwards — itself a red flag).
