# What Terraform reads but must never own.
#
# The VPC and subnets are the account's *default* ones. Importing them would put
# `destroy` one command away from deleting the default VPC, which everything
# else in the account also sits in. Read-only is not a shortcut here; it is the
# correct relationship.
#
# Deliberately absent:
#   - The SSM parameter holding the OpenRouter key. `data "aws_ssm_parameter"`
#     decrypts by default, which would write the plaintext key into
#     terraform.tfstate. Nothing here needs the value, so it is not read at all.
#   - `ecsTaskExecutionRole` and the GitHub deploy role, and both ECR
#     repositories. designs/environments.md marks these shared and never
#     renamed; Terraform owning them means a destroy can break CI.

data "aws_vpc" "default" {
  default = true
}

# All six default subnets, one per availability zone. Both ECS services already
# span all six, and the EFS filesystem has a mount target in each.
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
