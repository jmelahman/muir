# Terraform — repository configuration

Manages the GitHub repository config for `miur` with the
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
| `github_branch_protection.default` | require the `gate` status check (and CODEOWNERS review if `require_human_review = true`) |
| `github_issue_label.this` | `risk:low`, `risk:high`, `audit:flagged` |
| `github_actions_variable.*` | `MIUR_AUDIT_BACKEND`, `MIUR_AUDIT_MODEL` |

## Merge gate

The single required check is **`gate`** (it aggregates the per-package matrix
jobs, whose check names are dynamic). `gate` fails for audit-flagged PRs — which
is what holds them — and passes for clean / `risk:low` PRs, which then
auto-merge. So the default needs **no** human review. Flip `require_human_review`
to also gate every PR on a CODEOWNERS approval.

## Secrets (set out of band)

Resources-only by design, so no plaintext secrets touch Terraform state. Set the
ones your chosen backend needs:

```sh
gh secret set MIUR_PR_TOKEN            # PAT so sync's PRs trigger CI (always)
gh secret set OPENROUTER_API_KEY       # backend=openrouter
gh secret set CLAUDE_CODE_OAUTH_TOKEN  # backend=claude-cli (subscription, no metered key)
gh secret set ANTHROPIC_API_KEY        # backend=anthropic
```

## State

Local state by default. For shared/CI use, uncomment a remote backend block in
`versions.tf` and run `terraform init -migrate-state`.
