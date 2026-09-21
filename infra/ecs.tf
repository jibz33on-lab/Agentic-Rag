# The cluster, the Qdrant task definition, and both services.
#
# The `basic-rag-api` task definition is deliberately NOT here. ci.yml registers
# a new revision on every deploy by reading the live one and swapping the image.
# If Terraform also owned it, every plan would show drift wanting to revert to
# whatever image this code names, and every apply would fight the pipeline. Two
# owners of one resource is the bug; the service below carries an
# ignore_changes for exactly that reason.
#
# The Qdrant task definition IS here, because nothing else writes it. It was
# made by hand once and its image is pinned.

resource "aws_ecs_cluster" "main" {
  name = var.cluster_name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  # AWS stores this even though nothing set it deliberately. Written down so the
  # plan is clean; ECS Exec itself is roadmap step 5 and needs a task role first.
  configuration {
    execute_command_configuration {
      logging = "DEFAULT"
    }
  }
}

resource "aws_ecs_task_definition" "qdrant" {
  family                   = "basic-rag-qdrant"
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = "arn:aws:iam::222043263320:role/ecsTaskExecutionRole"

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  volume {
    name = "qdrant-storage"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.qdrant.id
      root_directory     = "/"
      transit_encryption = "ENABLED"
    }
  }

  container_definitions = jsonencode([
    {
      name      = "qdrant"
      image     = "222043263320.dkr.ecr.us-east-1.amazonaws.com/qdrant:v1.19.0"
      essential = true
      portMappings = [
        { name = "qdrant-http", containerPort = 6333, hostPort = 6333, protocol = "tcp" },
        { name = "qdrant-grpc", containerPort = 6334, hostPort = 6334, protocol = "tcp" },
      ]
      mountPoints = [
        { sourceVolume = "qdrant-storage", containerPath = "/qdrant/storage", readOnly = false },
      ]
      environment = []
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.qdrant.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "basic-rag-api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = "basic-rag-api:6"
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }

  # Enabled with rollback. Since Issue #2 gave the container a health check,
  # this can catch a task that starts cleanly and then fails to serve -- not
  # only one that fails to start.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  enable_ecs_managed_tags       = true
  propagate_tags                = "NONE"
  availability_zone_rebalancing = "ENABLED"

  # Attaching the target group. Verified against the UpdateService API docs that
  # this is an in-place update for a rolling-update service, NOT a service
  # recreation: "you can add, update, or remove Elastic Load Balancing target
  # groups". It does start a replacement task and stop the old one.
  dynamic "load_balancer" {
    for_each = var.alb_enabled ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api[0].arn
      container_name   = "api"
      container_port   = 8000
    }
  }

  # Only meaningful once a load balancer exists: it is the window in which the
  # scheduler ignores ELB health checks on a newly started task. The container
  # health check has its own startPeriod and does not use this.
  health_check_grace_period_seconds = var.alb_enabled ? 60 : 0

  lifecycle {
    # ci.yml owns the revision. Without this, every deploy would show up here
    # as drift and the next apply would roll the service back to an older image.
    ignore_changes = [task_definition]
  }
}

resource "aws_ecs_service" "qdrant" {
  name    = "basic-rag-qdrant-service"
  cluster = aws_ecs_cluster.main.id
  # family:revision, which is the form AWS stores. Using .arn here is also
  # valid but shows as permanent drift against the imported value.
  task_definition = "${aws_ecs_task_definition.qdrant.family}:${aws_ecs_task_definition.qdrant.revision}"
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }

  # 0/100 rather than the API's 100/200, and no circuit breaker. One EFS writer
  # means the old task must stop before the new one starts, so a Qdrant deploy
  # is a brief outage by design. designs/environments.md says so explicitly.
  deployment_maximum_percent         = 100
  deployment_minimum_healthy_percent = 0

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.qdrant.id]
    assign_public_ip = true
  }

  # This is what publishes qdrant.basic-rag.local.
  service_registries {
    registry_arn = aws_service_discovery_service.qdrant.arn
  }

  availability_zone_rebalancing = "DISABLED"
  wait_for_steady_state         = false
}
