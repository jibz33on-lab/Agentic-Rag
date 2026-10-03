# The vector store: an S3 Vectors vector_bucket and one index inside it.
#
# This is not an S3 bucket. It is a separate service with its own API
# (s3vectors, not s3), and the only thing it shares with documents.tf is a
# naming convention.

resource "aws_s3vectors_vector_bucket" "main" {
  vector_bucket_name = "${var.name_prefix}-vectors-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3vectors_index" "main" {
  index_name         = "${var.name_prefix}-index"
  vector_bucket_name = aws_s3vectors_vector_bucket.main.vector_bucket_name

  # Lowercase here, uppercase FLOAT32 on the knowledge_base in
  # knowledge_base.tf. Same value, two spellings, one per API.
  data_type       = "float32"
  dimension       = var.embedding_dimensions
  distance_metric = "cosine"

  # The setting that fails quietly if it is wrong.
  #
  # Bedrock writes the chunk text itself into per-vector metadata, as
  # AMAZON_BEDROCK_TEXT, with the source JSON in AMAZON_BEDROCK_METADATA. S3
  # Vectors caps *filterable* metadata at 2048 bytes per vector, and an index
  # created with no metadata_configuration makes every key filterable. At
  # max_tokens 250 a chunk is roughly 1000 characters, so this rejects most of
  # the corpus rather than an unlucky tail.
  #
  # Declaring them non-filterable removes them from that budget and changes
  # nothing else: they are still stored and still returned by Retrieve.
  #
  # Two properties make this worth a comment this long. It is immutable -- the
  # keys cannot be changed without replacing the index, and the knowledge_base
  # sits on top of the index. And it presents as success: the ingestion_job
  # reports COMPLETE over an incomplete corpus, which is the exact failure the
  # non-zero exit in main.py ingest exists to catch.
  metadata_configuration {
    non_filterable_metadata_keys = [
      "AMAZON_BEDROCK_TEXT",
      "AMAZON_BEDROCK_METADATA",
    ]
  }
}
