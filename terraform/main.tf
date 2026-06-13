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

# Default-branch ruleset.
#
# Requires the status checks AND a code-owner (you) approval on every PR — so all
# contributions go through you. The bot App (var.bot_app_id) is a bypass actor,
# so its audit-clean update PRs auto-merge without that review. The `gate` check
# still independently blocks audit-flagged PRs.
resource "github_repository_ruleset" "default" {
  name        = "default-branch"
  repository  = github_repository.this.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true # block branch deletion
    non_fast_forward = true # block force-push

    pull_request {
      required_approving_review_count = 1
      require_code_owner_review       = true
      dismiss_stale_reviews_on_push   = true
    }

    required_status_checks {
      strict_required_status_checks_policy = true # up to date with base
      dynamic "required_check" {
        for_each = toset(var.required_status_checks)
        content {
          context = required_check.value
        }
      }
    }
  }

  # The bot App bypasses required review -> its vetted PRs auto-merge.
  dynamic "bypass_actors" {
    for_each = var.bot_app_id > 0 ? [1] : []
    content {
      actor_id    = var.bot_app_id
      actor_type  = "Integration"
      bypass_mode = "always"
    }
  }
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
