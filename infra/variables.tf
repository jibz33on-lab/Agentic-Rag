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
