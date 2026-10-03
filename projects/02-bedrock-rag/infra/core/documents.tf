# Where the documents land.
#
# An ordinary S3 bucket, and the distinction from the vector_bucket in
# vectors.tf is the first mistake available in this slice: that one is an S3
# Vectors resource and not an S3 bucket at all.

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are globally unique, so the account id is suffixed -- the same
  # trick project 01 uses for the frontend bucket.
  documents_bucket_name = "${var.name_prefix}-documents-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "documents" {
  bucket = local.documents_bucket_name

  # Deliberately destroyable, and the opposite of the prevent_destroy on
  # project 01's EFS filesystem. That filesystem holds the only copy of the
  # ingested chunks; this bucket holds a copy of four PDFs that also live in
  # data/ on the laptop and are verified against data/corpus.sha256 before
  # upload. It is a staging area, not a store, so a destroy that empties it
  # loses nothing a re-upload does not restore.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
