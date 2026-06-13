provider "github" {
  owner = var.github_owner
  # Authentication is read from the environment:
  #   export GITHUB_TOKEN=<PAT with repo + admin:repo_hook scopes>
  # (or GITHUB_APP_* for a GitHub App install). Do not hardcode a token here.
}
