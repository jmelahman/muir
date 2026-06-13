output "repository_full_name" {
  description = "owner/name of the managed repository."
  value       = github_repository.this.full_name
}

output "ruleset_bypass_configured" {
  description = "Whether the bot App is set as a ruleset bypass actor (enables bot auto-merge)."
  value       = var.bot_app_id > 0
}

output "required_status_checks" {
  description = "Status check contexts required before merge."
  value       = var.required_status_checks
}
