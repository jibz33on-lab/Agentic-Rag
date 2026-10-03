variable "region" {
  description = "The AWS region this stack lives in. One region by design, matching project 01."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for every named resource, so project 02's estate is greppable apart from project 01's."
  type        = string
  default     = "bedrock-rag"
}

# The chunking and embedding values below are the axes of the experiments
# designs/skeleton.md defers. They are variables so each is a one-line change
# -- but every one of them replaces a resource rather than updating it, and
# that is deliberate. See the immutability table in designs/ingestion_job.md.

variable "chunk_max_tokens" {
  description = <<-EOT
    Tokens per chunk. Replaces the data_source.

    250 is the translation of project 01's 1000-character CHUNK_SIZE: Bedrock
    chunks by tokens, not characters, so there is no exact expression of it.
    250 tokens is roughly 1000 characters of English prose. The translation is
    a guess, and the verification command checks it after the first
    ingestion_job rather than trusting it.
  EOT
  type        = number
  default     = 250
}

variable "chunk_overlap_percentage" {
  description = "Overlap between adjacent chunks. Maps exactly onto project 01's 200/1000. Replaces the data_source."
  type        = number
  default     = 20
}

variable "embedding_model_id" {
  description = <<-EOT
    The embedding_model. Replaces the whole knowledge_base, which is the
    expensive rung of the experiment ladder.

    Titan V2 rather than Cohere Embed v4 because it is AWS's default path, and
    the default path is the more honest thing to compare a hand-built pipeline
    against. See the Models table in designs/skeleton.md.
  EOT
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embedding_dimensions" {
  description = <<-EOT
    Vector dimensions. Must match on the index and the knowledge_base; a
    mismatch is an ingestion failure, not a plan error.

    1024 matches project 01's bge-m3, and matching it is cosmetic -- the
    vectors are not comparable and the dimension count does not make them so.
    designs/skeleton.md says this out loud so the number is not later read as
    evidence of parity.
  EOT
  type        = number
  default     = 1024
}
