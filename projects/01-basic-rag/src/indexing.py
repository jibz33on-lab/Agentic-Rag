"""Puts chunks into Qdrant, skipping anything already there."""

# Imported from a private module because langchain-community does not
# re-export it, and no maintained package supplies a SQL-backed record
# manager. langchain-postgres has PGVector but nothing equivalent. This is
# the most fragile import in the project — see the design doc.
from langchain_community.indexes._sql_record_manager import SQLRecordManager
from langchain_core.indexing import index
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def build_embeddings(config):
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


def index_chunks(chunks, config, embeddings):
    """Index `chunks`, skipping any whose content is already stored.

    cleanup="scoped_full" with source_id_key="source" means an edited file has
    its old chunks removed once the run finishes, rather than leaving both
    versions in the collection.
    """
    return index(
        chunks,
        _record_manager(config),
        _vector_store(config, embeddings),
        # scoped_full, not incremental. Incremental cleans up after every
        # batch, so a file whose chunks straddle a batch boundary has its
        # tail deleted by one batch and re-added by the next, on every run.
        # scoped_full cleans up once at the end, still only touching the
        # sources actually seen.
        cleanup="scoped_full",
        source_id_key="source",
        # key_encoder stays SHA-1 despite LangChain warning about it. Qdrant
        # only accepts an integer or a UUID as a point ID, and sha256 or
        # blake2b produce digests too long to be either. Collision resistance
        # is not in our threat model: these are local files we control.
    )


def _vector_store(config, embeddings):
    client = QdrantClient(url=config.qdrant_url)
    if not client.collection_exists(config.collection_name):
        client.create_collection(
            collection_name=config.collection_name,
            vectors_config=VectorParams(size=config.embedding_dimensions, distance=Distance.COSINE),
        )
    return QdrantVectorStore(
        client=client,
        collection_name=config.collection_name,
        embedding=embeddings,
    )


def _record_manager(config):
    manager = SQLRecordManager(namespace=config.collection_name, db_url=config.postgres_url)
    manager.create_schema()
    return manager
