# Terraform — repository configuration

Manages the GitHub repository config for `muir` with the
[`integrations/github`](https://registry.terraform.io/providers/integrations/github/latest)
provider: repository settings (auto-merge, squash-only), branch protection (the
`gate` required check), labels, and the non-secret Actions variables the audit
workflow reads. **Secrets are not managed here** — see below.

## Usage

```sh
cd terraform
export GITHUB_TOKEN=<PAT with repo + admin scopes>     # provider auth
cp terraform.tfvars.example terraform.tfvars           # optional; edit as needed

terraform init

# The repo already exists — import it before the first apply:
terraform import github_repository.this muir

terraform plan
terraform apply
```

## What it configures

| Resource | Purpose |
|---|---|
| `github_repository.this` | auto-merge on, squash-only, delete branch on merge |
| `github_repository_ruleset.default` | require the `gate`+`terraform` checks **and** a code-owner review; the bot App (`bot_app_id`) bypasses the review |
| `github_issue_label.this` | `risk:low`, `risk:high`, `audit:flagged` |
| `github_actions_variable.*` | `MUIR_AUDIT_BACKEND`, `MUIR_AUDIT_MODEL` |

## Merge gate

Two things gate the default branch: the **`gate`** status check (aggregates the
per-package matrix jobs; fails for audit-flagged PRs, which holds them) and a
**code-owner review**. The muir bot App is a ruleset **bypass actor**, so its
audit-clean PRs auto-merge without a review while every human PR waits for your
approval. Set `bot_app_id` (see `.github/bot-app.md`); until then nothing
auto-merges — every PR needs a review.

## Secrets (set out of band)

Resources-only by design, so no plaintext secrets touch Terraform state. Set the
ones your chosen backend needs:

```sh
gh secret set MUIR_PR_TOKEN            # PAT so sync's PRs trigger CI (always)
gh secret set OPENROUTER_API_KEY       # backend=openrouter
gh secret set CLAUDE_CODE_OAUTH_TOKEN  # backend=claude-cli (subscription, no metered key)
gh secret set ANTHROPIC_API_KEY        # backend=anthropic
```

## State

Local state by default. For shared/CI use, uncomment a remote backend block in
`versions.tf` and run `terraform init -migrate-state`.
