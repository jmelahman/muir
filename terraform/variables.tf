variable "github_owner" {
  description = "GitHub user or org that owns the repository."
  type        = string
  default     = "jmelahman"
}

variable "repository_name" {
  description = "Repository name."
  type        = string
  default     = "muir"
}

variable "default_branch" {
  description = "Default branch the protection rule applies to."
  type        = string
  default     = "master"
}

variable "required_status_checks" {
  description = "Status checks that must pass before merge. `gate` aggregates the matrix audit/build jobs; `terraform` validates this module."
  type        = list(string)
  default     = ["gate", "terraform"]
}

variable "bot_app_id" {
  description = <<-EOT
    GitHub App ID of the muir bot. The branch ruleset requires a code-owner
    review on every PR, but this App bypasses that — so the bot's audit-clean
    update PRs auto-merge while all human contributions still need your review.
    Leave 0 until the App exists (then NO PR can auto-merge — everything needs a
    review). See .github/bot-app.md.
  EOT
  type        = number
  default     = 0
}

variable "audit_backend" {
  description = "LLM backend for the audit (repo Actions variable MUIR_AUDIT_BACKEND)."
  type        = string
  default     = "openrouter"
  validation {
    condition     = contains(["openrouter", "claude-cli", "anthropic"], var.audit_backend)
    error_message = "audit_backend must be one of: openrouter, claude-cli, anthropic."
  }
}

variable "audit_model" {
  description = "Optional model override (Actions variable MUIR_AUDIT_MODEL). Empty = backend default."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Issue/PR labels to manage (name => hex color)."
  type        = map(string)
  default = {
    "risk:low"      = "0e8a16"
    "risk:high"     = "d93f0b"
    "audit:flagged" = "b60205"
  }
}
