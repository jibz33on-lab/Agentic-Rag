# Service discovery: how the API finds Qdrant.
#
# The API's QDRANT_URL is http://qdrant.basic-rag.local:6333 -- a name, not an
# address, because the Qdrant task's IP changes every time it is replaced. Cloud
# Map keeps an A record pointing at whatever the current task's IP is.
#
# `health_check_custom_config` means ECS reports instance health rather than
# Cloud Map polling an endpoint itself. Note the consequence, recorded in the
# Issue #2 investigation: the Qdrant task definition has no container health
# check, so ECS reports it healthy the moment the task is RUNNING. That is a
# separate issue and deliberately not fixed here.

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "basic-rag.local"
  description = "Private DNS for basic-rag internal services"
  vpc         = data.aws_vpc.default.id
}

resource "aws_service_discovery_service" "qdrant" {
  name          = "qdrant"
  description   = "Qdrant vector DB task, registered by ECS"
  force_destroy = false

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 15
    }
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}
