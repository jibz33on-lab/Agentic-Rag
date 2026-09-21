# The one piece of state in this project.
#
# designs/environments.md: the ingested chunks live here and nowhere else. EFS
# rather than a task volume because a Fargate task's own disk dies with it, and
# this has to survive the task being replaced on every deploy.

resource "aws_efs_file_system" "qdrant" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  tags = {
    Name = "basic-rag-qdrant-storage"
  }

  lifecycle {
    # The ingested chunks exist here and nowhere else, and there is no backup
    # plan yet. A destroy that reaches this filesystem has to be a deliberate
    # act, not a consequence of some other command.
    prevent_destroy = true
  }
}

# One mount target per availability zone. A task can only mount the filesystem
# through a target in its *own* AZ, and the Qdrant service is free to place its
# task in any of the six, so all six need one.
resource "aws_efs_mount_target" "qdrant" {
  for_each = toset(data.aws_subnets.default.ids)

  file_system_id  = aws_efs_file_system.qdrant.id
  subnet_id       = each.value
  security_groups = [aws_security_group.qdrant_efs.id]
}
