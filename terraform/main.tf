# The repository already exists, so import it before the first apply:
#   terraform import github_repository.this muir
resource "github_repository" "this" {
  name        = var.repository_name
  description = "Security-vetting AUR source mirror with LLM-audited update PRs"
  visibility  = "public"

  # Merge policy: squash-only, auto-merge enabled, branches cleaned up.
  allow_auto_merge       = true
  allow_squash_merge     = true
  allow_merge_commit     = false
  allow_rebase_merge     = false
  delete_branch_on_merge = true

  has_issues = true

  lifecycle {
    prevent_destroy = true
  }
}

# Branch protection on the default branch.
#
# The `gate` status check is the real merge gate: it fails for audit-flagged
# PRs (holding them) and passes for clean / risk:low PRs (which then auto-merge).
resource "github_branch_protection" "default" {
  repository_id = github_repository.this.node_id
  pattern       = var.default_branch

  required_status_checks {
    strict   = true # PRs must be up to date with the base branch
    contexts = var.required_status_checks
  }

  # Optional, off by default — see require_human_review. When on, this needs the
  # CODEOWNERS file in the repo root.
  dynamic "required_pull_request_reviews" {
    for_each = var.require_human_review ? [1] : []
    content {
      require_code_owner_reviews      = true
      required_approving_review_count = 1
    }
  }

  enforce_admins      = false
  allows_force_pushes = false
  allows_deletions    = false
}

# Labels applied by the audit workflow / triage.
resource "github_issue_label" "this" {
  for_each = var.labels

  repository = github_repository.this.name
  name       = each.key
  color      = each.value
}

# Non-secret Actions configuration consumed by .github/workflows/audit.yml.
resource "github_actions_variable" "audit_backend" {
  repository    = github_repository.this.name
  variable_name = "MUIR_AUDIT_BACKEND"
  value         = var.audit_backend
}

resource "github_actions_variable" "audit_model" {
  count = var.audit_model == "" ? 0 : 1

  repository    = github_repository.this.name
  variable_name = "MUIR_AUDIT_MODEL"
  value         = var.audit_model
}

# --------------------------------------------------------------------------
# Secrets are intentionally NOT managed here (resources-only) so plaintext
# never lands in Terraform state. Set them out of band, e.g.:
#
#   gh secret set MUIR_PR_TOKEN            # PAT so sync PRs trigger CI
#   gh secret set OPENROUTER_API_KEY       # backend=openrouter
#   gh secret set CLAUDE_CODE_OAUTH_TOKEN  # backend=claude-cli (subscription)
#   gh secret set ANTHROPIC_API_KEY        # backend=anthropic
#
# To manage them in Terraform instead, add `github_actions_secret` resources
# fed from sensitive variables AND move state to an encrypted remote backend.
# --------------------------------------------------------------------------
