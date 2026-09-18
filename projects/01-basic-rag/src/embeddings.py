"""Builds the embedding model client.

Its own module, deliberately, rather than living in `indexing.py` where it
started. `indexing.py` imports `SQLRecordManager` at module level, which drags
SQLAlchemy and psycopg in behind it. The AWS ingestion path rebuilds the
collection outright and uses no record manager at all, so importing it from
there would put Postgres in an image that must never need it — see
`designs/environments.md`, "Decided: AWS ingestion drops the record_manager".

Keeping this here means "no Postgres in the AWS ingestion path" is a property
you can check by reading the imports, rather than by tracing a call graph and
trusting that nothing ever calls `index_chunks`.
"""

from config import Config
from langchain_openai import OpenAIEmbeddings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_embeddings(config: Config) -> OpenAIEmbeddings:
    """The real embedding model, served by OpenRouter.

    check_embedding_ctx_length is off because the client would otherwise try
    to count tokens with a tokeniser it only has for OpenAI's own models.
    """
    return OpenAIEmbeddings(
        model=config.embedding_model,
        api_key=config.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
        check_embedding_ctx_length=False,
    )
