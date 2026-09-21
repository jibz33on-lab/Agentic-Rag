# Step 4: the Application Load Balancer.
#
# Everything here is behind `var.alb_enabled` so the whole thing can be removed
# with one flag:
#
#   terraform apply -var="alb_enabled=true"    stand it up
#   terraform apply -var="alb_enabled=false"   tear it down
#
# That matters because this state now holds the entire DEV estate, so a bare
# `terraform destroy` would take Qdrant and its EFS filesystem with it. A flag
# scoped to the ALB is the safe way to do ephemeral infrastructure on shared
# state, and the plan shows exactly what goes.
#
# Why an ALB at all, for one task: not load distribution and not availability.
# A STABLE DNS NAME in front of a task IP that changes on every deploy, and a
# place to terminate TLS in step 15. Today's alternative is a security-group
# rule pinned to a laptop address that has already gone stale.
#
# Cost while it is up: roughly $0.0225/hour, about $16.20/month, plus LCUs.

# ---------------------------------------------------------------------------
# The only thing exposed to the internet.
#
# Note the shape: the ALB's group accepts 80 from anywhere, and the task's group
# accepts 8000 *from this group only*. Nothing on the internet can address the
# task directly. That is the security win, and it is why the rule added to
# basic-rag-api-sg references a group rather than a CIDR -- ALB nodes get
# private IPs that change as it scales, so no CIDR would stay correct.
# ---------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  # Retained a little longer than the rest of the ALB during teardown, so the
  # ingress rule pointing at it can be revoked before it is deleted. See
  # var.keep_alb_sg.
  count = (var.alb_enabled || var.keep_alb_sg) ? 1 : 0

  name        = "basic-rag-alb-sg"
  description = "Public entry point for the basic-rag API. HTTP only; HTTPS is step 15."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Egress to the VPC on 8000, not to the API's security group by reference.
  #
  # The obvious version -- `security_groups = [aws_security_group.api.id]` --
  # does not work here, and the reason is worth knowing: the API group already
  # references THIS group for its ingress rule, so pointing back at it creates a
  # dependency cycle and Terraform refuses to build a graph:
  #
  #     Error: Cycle: aws_security_group.alb, aws_security_group.api
  #
  # The strict fix is to lift one side out into a standalone
  # aws_vpc_security_group_egress_rule, which depends on both groups while
  # neither depends on the other. That is avoided here because this group's
  # ingress is written inline, and the AWS provider warns against mixing inline
  # rules with standalone rule resources on the same group -- it produces
  # perpetual diffs.
  #
  # So: the CIDR of this VPC, on the one port, outbound only. The control that
  # actually matters is the API group's INGRESS rule, which does reference this
  # group by id, and which is what stops anything on the internet reaching the
  # task directly.
  egress {
    description = "to the API tasks inside this VPC"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }
}

# ---------------------------------------------------------------------------
# The load balancer.
#
# Six subnets because an ALB requires at least two availability zones, and
# mirroring the ECS service's six keeps one rule to remember: the ALB spans what
# the service spans. These are all public subnets, which is what
# `internal = false` needs.
# ---------------------------------------------------------------------------
resource "aws_lb" "main" {
  count = var.alb_enabled ? 1 : 0

  name               = "basic-rag-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb[0].id]
  subnets            = data.aws_subnets.default.ids
}

# ---------------------------------------------------------------------------
# The target group: the set of backends, plus the rule for which are eligible.
#
# target_type = "ip" is REQUIRED here, not a preference. Fargate tasks use
# awsvpc networking: each task owns an ENI with its own private IP and there is
# no EC2 instance to register. "instance" targets cannot express that.
#
# Targets are never registered by hand. ECS registers a task's IP when it passes
# its health check and deregisters it during DEACTIVATING.
# ---------------------------------------------------------------------------
resource "aws_lb_target_group" "api" {
  count = var.alb_enabled ? 1 : 0

  name        = "basic-rag-api-tg"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.default.id

  # 30s rather than the 300s default. This is how long the ALB keeps a
  # connection open to a target it is removing, and it is added to the end of
  # every deployment. Five minutes of waiting per deploy is a poor trade at one
  # task with no long-lived requests.
  deregistration_delay = 30

  # The same /health the container health check uses, reached a different way:
  # from the ALB, across the network, through the security group. The container
  # check asks "is this process alive"; this asks "should this target receive
  # traffic". They fail differently and both are worth having.
  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

# ---------------------------------------------------------------------------
# The listener: the port the ALB accepts on, and where those connections go.
#
# Port 80, HTTP, one default action and no rules -- there is one backend, so
# there is nothing to route between. Step 15 turns this into a 443 listener with
# an ACM certificate, and usually leaves an 80 listener behind that redirects.
# ---------------------------------------------------------------------------
resource "aws_lb_listener" "http" {
  count = var.alb_enabled ? 1 : 0

  load_balancer_arn = aws_lb.main[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}
