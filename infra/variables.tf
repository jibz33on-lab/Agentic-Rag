variable "region" {
  description = "The AWS region DEV lives in. Everything is in one region by design."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "Shared across environments by design; see designs/environments.md."
  type        = string
  default     = "basic-rag-cluster"
}

variable "alb_enabled" {
  description = <<-EOT
    Whether the ALB, its security group, target group and listener exist.

    False by default and deliberately so. designs/environments.md argues for
    ephemeral infrastructure: an always-on ALB is ~$16.20/month forever for a
    single-user project, where standing it up, learning it and tearing it down
    costs a few dollars. Flipping this to false removes the ALB and detaches the
    ECS service in one plan, with nothing else touched.
  EOT
  type        = bool
  default     = false
}

variable "keep_alb_sg" {
  description = <<-EOT
    Retain the ALB security group even when alb_enabled is false.

    This exists to make teardown orderable, and it was added after a teardown
    failed. basic-rag-api-sg holds an ingress rule referencing the ALB's group,
    and AWS refuses to delete a group another group's rule points at:

        DependencyViolation: resource sg-... has a dependent object

    The rule has to be revoked first. But with alb_enabled = false the ALB group
    becomes a count-orphan, and Terraform destroys orphans in the same run,
    without an ordering edge to the rule revocation -- so it tried the delete
    first and retried it for fifteen minutes. -target does not help, because
    orphan destroys are processed regardless of it.

    So teardown is two applies:

      terraform apply -var="keep_alb_sg=true"   revoke the rule, keep the group
      terraform apply                           delete the now-unreferenced group
  EOT
  type        = bool
  default     = false
}
