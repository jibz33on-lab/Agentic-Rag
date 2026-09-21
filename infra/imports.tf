# Adopting what already exists.
#
# Every resource in this configuration already exists in AWS, built by hand or
# by ci.yml. These blocks tell Terraform to take ownership of the real thing
# rather than create a second copy of it.
#
# `import` blocks rather than the `terraform import` CLI command: they are part
# of the configuration, so the plan shows what will be adopted before anything
# happens, and the record of what was adopted stays in the repo.
#
# The goal for this step is a plan that reports imports and NO changes. Any
# "will be updated in-place" means this code does not yet describe what is
# actually running, and the code is what is wrong.
#
# These blocks can be deleted once the import has been applied; they are kept
# for now because they document the estate's origin.

import {
  to = aws_ecs_cluster.main
  id = "basic-rag-cluster"
}

import {
  to = aws_ecs_service.api
  id = "basic-rag-cluster/basic-rag-api-service"
}

import {
  to = aws_ecs_service.qdrant
  id = "basic-rag-cluster/basic-rag-qdrant-service"
}

import {
  to = aws_ecs_task_definition.qdrant
  id = "arn:aws:ecs:us-east-1:222043263320:task-definition/basic-rag-qdrant:2"
}

import {
  to = aws_security_group.api
  id = "sg-0142fb82d02201526"
}

import {
  to = aws_security_group.qdrant
  id = "sg-05f8b38d5df857d95"
}

import {
  to = aws_security_group.qdrant_efs
  id = "sg-0d5844b525da14f1c"
}

import {
  to = aws_efs_file_system.qdrant
  id = "fs-07941fd9547a1fee7"
}

# One per AZ, keyed by subnet so the address matches the for_each above.
import {
  to = aws_efs_mount_target.qdrant["subnet-0dd4ec73b42b20564"]
  id = "fsmt-07027d63ccf655028"
}
import {
  to = aws_efs_mount_target.qdrant["subnet-052d4f3bc4b9af3f3"]
  id = "fsmt-0318f1c9f0716738c"
}
import {
  to = aws_efs_mount_target.qdrant["subnet-02704a0e771e23e86"]
  id = "fsmt-092cb0291e4b8418a"
}
import {
  to = aws_efs_mount_target.qdrant["subnet-0cadd4a3d63a63bf6"]
  id = "fsmt-0cff2cb2555f11ddf"
}
import {
  to = aws_efs_mount_target.qdrant["subnet-044e30f59252b952b"]
  id = "fsmt-07b58ce9918b66d96"
}
import {
  to = aws_efs_mount_target.qdrant["subnet-03385c7d4a92d0615"]
  id = "fsmt-0f36b177dddaa327f"
}

import {
  to = aws_service_discovery_private_dns_namespace.main
  id = "ns-yrtdyt63gydn4ik3:vpc-023412c2ac66597bf"
}

import {
  to = aws_service_discovery_service.qdrant
  id = "srv-qw2nn2pplx6rtphn"
}

import {
  to = aws_cloudwatch_log_group.api
  id = "/ecs/basic-rag-api"
}

import {
  to = aws_cloudwatch_log_group.qdrant
  id = "/ecs/basic-rag-qdrant"
}

import {
  to = aws_cloudwatch_log_group.ingest
  id = "/ecs/basic-rag-ingest"
}
