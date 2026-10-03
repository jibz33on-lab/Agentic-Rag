# The managed pipeline itself.
#
# Two resources, and between them they own the five components project 01
# hand-builds: splitting, embedding, storing, retrieving and reranking. There
# is no compute to provision and no record_manager -- the knowledge_base tracks
# what it has already ingested, so a re-run syncs changes. That absence is one
# whole component of project 01 that does not exist here, and it belongs in the
# slice 3 comparison.

resource "aws_bedrockagent_knowledge_base" "main" {
  name     = "${var.name_prefix}-kb"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn

      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions = var.embedding_dimensions
          # Uppercase here, lowercase "float32" on the index in vectors.tf.
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.main.index_arn
    }
  }

  # IAM is eventually consistent, so Bedrock can refuse to assume a role that
  # was created seconds earlier. The dependency is implicit through role_arn,
  # but the policies are not -- without this the knowledge_base can be created
  # before the role can do anything, and the first ingestion_job fails for a
  # reason the plan gave no hint of.
  depends_on = [
    aws_iam_role_policy.embedding_model,
    aws_iam_role_policy.documents,
    aws_iam_role_policy.vectors,
  ]
}

resource "aws_bedrockagent_data_source" "main" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.main.id
  name              = "${var.name_prefix}-s3"

  # DELETE, not the default, and the reason is the one index.
  #
  # A knowledge_base has exactly one vector index, and any chunking change
  # replaces this data_source. Under RETAIN the replaced data_source's vectors
  # stay in the index beside the new ones, so Retrieve returns two generations
  # of chunk with nothing to tell them apart -- a corrupted baseline that looks
  # like a retrieval-quality problem. DELETE makes a replacement mean what it
  # reads like.
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn = aws_s3_bucket.documents.arn
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"

      fixed_size_chunking_configuration {
        max_tokens         = var.chunk_max_tokens
        overlap_percentage = var.chunk_overlap_percentage
      }
    }
  }
}
