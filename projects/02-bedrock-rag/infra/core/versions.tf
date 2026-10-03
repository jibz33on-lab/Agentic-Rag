# Terraform and provider versions.
#
# Pinned for the same reason project 01's are: an apply that produces a
# different result because a provider moved underneath it is the failure this
# whole module exists to avoid.
#
# The floor is 6.27 rather than 6.0, and it is a real floor, not caution. The
# three things this module cannot be written without arrived in three separate
# releases:
#
#   6.24  aws_s3vectors_vector_bucket, aws_s3vectors_index
#   6.26  aws_s3vectors_index metadata_configuration  -- see vectors.tf
#   6.27  aws_bedrockagent_knowledge_base storage_configuration.s3_vectors_configuration
#
# On 6.26 this module plans and applies and silently has a filterable chunk
# text field, which is the one failure mode designs/ingestion_job.md singles
# out. The constraint is what stops that being discoverable only at ingest.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.27"
    }
  }
}

provider "aws" {
  region = var.region
}
