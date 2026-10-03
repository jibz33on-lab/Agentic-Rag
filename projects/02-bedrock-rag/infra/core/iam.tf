# What Bedrock assumes to do the ingesting.
#
# Four separate concerns, not one: who may assume the role, the embedding_model
# it may invoke, the documents it may read, and the index it may write. KB
# creation fails outright without this role, and the failure messages do not
# say which of the four is missing -- so each is its own policy, named for what
# it grants.

data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  embedding_model_arn = "arn:${local.partition}:bedrock:${var.region}::foundation-model/${var.embedding_model_id}"
}

resource "aws_iam_role" "kb" {
  name = "${var.name_prefix}-kb-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        # Confused-deputy protection: without these, any account whose Bedrock
        # could be induced to name this role ARN could use it.
        StringEquals = { "aws:SourceAccount" = local.account_id }
        # Scoped to knowledge bases in this account rather than to this
        # knowledge base. Narrowing it to the specific id would need the id,
        # which needs the knowledge_base, which needs this role -- a cycle.
        # AWS suggests tightening it by hand after creation; doing that here
        # would mean Terraform fighting itself on the next apply.
        ArnLike = {
          "aws:SourceArn" = "arn:${local.partition}:bedrock:${var.region}:${local.account_id}:knowledge-base/*"
        }
      }
    }]
  })
}

# Invoking the embedding_model. Scoped to the one model, so switching
# var.embedding_model_id without re-applying this policy fails loudly at
# ingest rather than quietly embedding with something unexpected.
resource "aws_iam_role_policy" "embedding_model" {
  name = "invoke-embedding-model"
  role = aws_iam_role.kb.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = [local.embedding_model_arn]
    }]
  })
}

# Reading the documents. ListBucket on the bucket, GetObject on its contents --
# two different resource shapes, and omitting the first produces an
# ingestion_job that finds no documents rather than an access error.
resource "aws_iam_role_policy" "documents" {
  name = "read-documents"
  role = aws_iam_role.kb.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.documents.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.documents.arn}/*"]
      },
    ]
  })
}

# Writing and querying the index. QueryVectors is here because the same role
# serves Retrieve, not just ingestion.
resource "aws_iam_role_policy" "vectors" {
  name = "write-vectors"
  role = aws_iam_role.kb.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:GetIndex",
      ]
      Resource = [aws_s3vectors_index.main.index_arn]
    }]
  })
}
