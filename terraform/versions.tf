terraform {
  required_version = ">= 1.5"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }

  # State backend. Local by default (terraform.tfstate in this directory).
  #
  # For shared/CI use, switch to a remote backend so state isn't on one laptop.
  # Uncomment and fill in ONE of these, then `terraform init -migrate-state`:
  #
  # backend "s3" {
  #   bucket         = "my-tf-state"
  #   key            = "miur/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "tf-locks"
  #   encrypt        = true
  # }
  #
  # backend "gcs" {
  #   bucket = "my-tf-state"
  #   prefix = "miur"
  # }
  #
  # cloud {                       # Terraform Cloud / HCP
  #   organization = "my-org"
  #   workspaces { name = "miur" }
  # }
}
