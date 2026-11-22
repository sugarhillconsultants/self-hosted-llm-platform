terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.59, < 7.0"
    }
  }

  # Bucket is passed at init time, derived from the account ID:
  #   terraform init -backend-config="bucket=self-hosted-llm-platform-tfstate-<account-id>"
  # scripts/up.sh and the workflow do this for you.
  backend "s3" {
    key          = "envs/demo/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = var.project
      Environment = "demo"
      ManagedBy   = "terraform"
    }
  }
}
