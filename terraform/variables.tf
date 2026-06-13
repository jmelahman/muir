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

variable "require_human_review" {
  description = <<-EOT
    If true, also require a CODEOWNERS approval on EVERY PR (stricter; even
    audit-clean PRs then need a human). If false (default), the merge gate is the
    `gate` status check alone — clean/risk:low PRs auto-merge with no human, and
    flagged PRs are held because their `gate` check fails.
  EOT
  type        = bool
  default     = false
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
