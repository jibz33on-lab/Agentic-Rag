# Outputs exist for the smoke test, which drives the raw AWS CLI before src/
# exists. Once main.py is built it reads SSM instead -- see parameters.tf.

output "documents_bucket" {
  description = "Where to upload the corpus."
  value       = aws_s3_bucket.documents.id
}

output "knowledge_base_id" {
  description = "Also at the SSM path in parameters.tf."
  value       = aws_bedrockagent_knowledge_base.main.id
}

output "data_source_id" {
  description = "Also at the SSM path in parameters.tf."
  value       = aws_bedrockagent_data_source.main.data_source_id
}

output "vector_index_arn" {
  description = "For confirming the non-filterable metadata keys took effect."
  value       = aws_s3vectors_index.main.index_arn
}
