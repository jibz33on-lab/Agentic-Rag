"""Opens the Qdrant collection for a given set of settings."""

from config import Config
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


def open_vector_store(config: Config, embeddings: Embeddings) -> QdrantVectorStore:
    """Return the collection for these settings, creating it if needed.

    The collection is named from the settings, so a different chunk size or
    embedding model opens a different, empty collection rather than mixing
    with chunks built the old way.
    """
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
