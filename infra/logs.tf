# Log groups, one per workload.
#
# The retention values are as they are today, not as they should be: the API
# group has none and grows forever, which designs/environments.md lists as an
# open gap. Written down as-is on purpose -- this step is about making the
# current estate reproducible, not about fixing it. Changing a value here is a
# one-line follow-up once the import is proven clean.

resource "aws_cloudwatch_log_group" "api" {
  name = "/ecs/basic-rag-api"
  # No retention_in_days: never expires. This is the open gap, recorded.
}

resource "aws_cloudwatch_log_group" "qdrant" {
  name              = "/ecs/basic-rag-qdrant"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/ecs/basic-rag-ingest"
  retention_in_days = 14
}
