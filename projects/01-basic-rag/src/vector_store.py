"""Opens the Qdrant collection for a given set of settings."""

from config import Config
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def open_vector_store(
    config: Config, embeddings: Embeddings, collection_name: str | None = None
) -> QdrantVectorStore:
    """Return the collection for these settings, creating it if needed.

    The collection is named from the settings, so a different chunk size or
    embedding model opens a different, empty collection rather than mixing
    with chunks built the old way.

    `collection_name` overrides that name. It is an explicit argument and
    deliberately not an environment variable: a caller naming a collection is
    visible at the call site, where a silent env-var mismatch would produce the
    project's worst failure — 200 OK from an empty collection. The one caller
    that passes it is the AWS rebuild, which stages a new collection beside the
    live one so the live one is never at risk. See `designs/environments.md`.
    """
    name = collection_name or config.collection_name
    client = QdrantClient(url=config.qdrant_url)
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=config.embedding_dimensions, distance=Distance.COSINE),
        )
    return QdrantVectorStore(
        client=client,
        collection_name=name,
        embedding=embeddings,
    )
