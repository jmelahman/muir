# muir — My Arch User Repository

A security-vetting mirror for the AUR packages you use. When a tracked package
changes upstream, a bot opens a PR and an LLM audits the diff; only audit-clean
changes merge, then get built into a **signed pacman repo**. Net effect:
`yay -Syu` installs **only vetted, signed builds** — never raw from the AUR.

**Pipeline:** detect update → PR → triage + LLM audit (`gate`) → merge if clean
→ build + GPG-sign → publish `[muir]` repo on GitHub Releases.

**Merge policy:** the bot's audit-clean PRs **auto-merge** (a GitHub App bypasses
review); **all human contributions require your code-owner review** — enforced by
a branch ruleset (see [`.github/bot-app.md`](.github/bot-app.md)).

## Adopt (fork-and-go)

1. **Use this template** / fork it.
2. `git clone … && ./bootstrap.sh` — rewrites `CODEOWNERS`, Terraform vars, and
   the pacman stanza from your fork's remote. Everything else derives from the
   repo automatically.
3. **Bot App** — create the muir GitHub App so its vetted PRs auto-merge while
   human PRs need your review; set `MUIR_APP_ID` + `MUIR_APP_PRIVATE_KEY` and
   `bot_app_id` in tfvars. See [`.github/bot-app.md`](.github/bot-app.md).
4. **Secrets** (`gh secret set …`): one audit backend key — `OPENROUTER_API_KEY`
   *or* `CLAUDE_CODE_OAUTH_TOKEN` *or* `ANTHROPIC_API_KEY` — and
   `MUIR_GPG_PRIVATE_KEY` (signing; see [`keys/`](keys/)).
5. **Configure the repo**: `cd terraform && terraform init &&
   terraform import github_repository.this <repo> && terraform apply`.
6. **Seed** from this machine: `python tools/sync.py --from-installed`, then
   commit + push. Enable the timer in [`contrib/`](contrib/) to track new installs.

## Use the repo

```sh
sudo pacman-key --add keys/signing.pub && sudo pacman-key --lsign-key <KEYID>
cat contrib/pacman-repo.conf | sudo tee -a /etc/pacman.conf
yay -Syu        # installs the vetted, signed builds
```

## Layout

| Path | Role |
|---|---|
| `<pkg>/` | mirrored `PKGBUILD` / `.SRCINFO` / `*.install` (one dir per package) |
| `tools/` | `sync` (detect/seed/PRs), `triage` (risk classifier), `audit` (LLM verdict) |
| `.github/workflows/` | `sync` (cron) · `audit`→`gate` (PR gate) · `build` (sign+publish) · `terraform` |
| `terraform/`, `contrib/`, `keys/` | repo config · seeding & new-install discovery · signing key |
| `bootstrap.sh` | point a fresh fork at itself |

Detail lives in each subdirectory's README. Tests: `python tools/tests/run.py`.
