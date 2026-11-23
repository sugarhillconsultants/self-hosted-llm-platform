terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.59, < 7.0"
    }
  }

  # Starts with local state, because the bucket doesn't exist yet. After the
  # first apply, uncomment this block and move the state into the bucket it
  # created (infra/terraform/README.md, step 4).
  #
  backend "s3" {
     key          = "bootstrap/terraform.tfstate"
     region       = "us-east-1"
     encrypt      = true
     use_lockfile = true
   }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Layer     = "bootstrap"
    }
  }
}
