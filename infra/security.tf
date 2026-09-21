# The three security groups, written as they exist today.
#
# Inline `ingress`/`egress` blocks rather than separate rule resources. Both are
# valid; inline blocks import with their group as one object and one import ID,
# which is simpler to follow. The two styles cannot be mixed on the same group,
# so the ALB's new rule in step 4 will be another inline block here.
#
# Every cross-service rule references a *security group*, never a CIDR. A task's
# private IP changes on every deployment, so an IP-based rule between these
# services would be wrong within a day. Group-to-group rules never go stale.

resource "aws_security_group" "api" {
  name        = "basic-rag-api-sg"
  description = "Created in ECS ConsoleSecurity group for Basic RAG API ECS service"
  vpc_id      = data.aws_vpc.default.id

  # The only way in from outside today, and it is already broken: the laptop
  # address it names has since changed. The ALB in step 4 is what replaces it.
  ingress {
    description = "temporary: direct access from my laptop (no ALB yet)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["103.104.46.6/32"]
  }

  # Added by step 4. Sourced from the ALB's security group, never a CIDR: ALB
  # nodes hold private IPs that change as it scales, so an address-based rule
  # would be wrong within days. This one rule carries both real traffic and the
  # target group's health probes.
  dynamic "ingress" {
    for_each = var.alb_enabled ? [1] : []
    content {
      description     = "8000 from the ALB"
      from_port       = 8000
      to_port         = 8000
      protocol        = "tcp"
      security_groups = [aws_security_group.alb[0].id]
    }
  }

  # Outbound to anywhere: the task pulls from ECR, reads SSM and calls
  # OpenRouter. These are public subnets with no NAT gateway, so this is also
  # the task's only route off the VPC.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "qdrant" {
  name        = "basic-rag-qdrant-sg"
  description = "Qdrant vector DB for basic-rag. Inbound only from the API task SG."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "HTTP API from basic-rag-api task"
    from_port       = 6333
    to_port         = 6333
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  ingress {
    description     = "gRPC from basic-rag-api task"
    from_port       = 6334
    to_port         = 6334
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "qdrant_efs" {
  name        = "basic-rag-qdrant-efs-sg"
  description = "EFS mount targets for Qdrant storage. NFS only from the Qdrant task SG."
  vpc_id      = data.aws_vpc.default.id

  # 2049 is NFS. Only Qdrant mounts this filesystem.
  ingress {
    description     = "NFS from Qdrant task"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.qdrant.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
