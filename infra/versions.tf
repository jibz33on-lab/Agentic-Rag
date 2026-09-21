# Terraform and provider versions.
#
# Pinned rather than floating: an `apply` that produces a different result
# because a provider moved underneath it is the exact failure this whole step
# exists to prevent. `~>` allows patch and minor updates, not a major one.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}
