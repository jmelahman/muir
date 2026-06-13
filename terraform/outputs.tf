output "repository_full_name" {
  description = "owner/name of the managed repository."
  value       = github_repository.this.full_name
}

output "protected_branch" {
  description = "Branch the protection rule applies to."
  value       = github_branch_protection.default.pattern
}

output "required_status_checks" {
  description = "Status check contexts required before merge."
  value       = var.required_status_checks
}
