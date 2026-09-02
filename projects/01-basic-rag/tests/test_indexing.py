import uuid

import pytest
from config import load_config
from indexing import index_chunks
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

FAKE_DIMENSIONS = 8


@pytest.fixture
def config():
    """Config pointing at a throwaway collection, so runs never collide."""
    return load_config(
        env={
            "OPENROUTER_API_KEY": "not-used-with-fake-embeddings",
            "EMBEDDING_MODEL": f"test/{uuid.uuid4().hex[:12]}",
            "EMBEDDING_DIMENSIONS": str(FAKE_DIMENSIONS),
        }
    )


@pytest.fixture
def services(config):
    """Skip unless Qdrant and Postgres are actually up."""
    import urllib.request

    from sqlalchemy import create_engine

    try:
        urllib.request.urlopen(config.qdrant_url, timeout=2)
    except Exception:
        pytest.skip("Qdrant is not running")
    try:
        create_engine(config.postgres_url).connect().close()
    except Exception:
        pytest.skip("Postgres is not running")


# More than one batch of 100. A single-batch test passes even when cleanup
# deletes and re-adds the tail of a file on every run.
CHUNK_COUNT = 150


def test_indexing_the_same_chunks_twice_skips_them(services, config):
    chunks = [
        Document(page_content=f"chunk number {i}", metadata={"source": "test.pdf"})
        for i in range(CHUNK_COUNT)
    ]
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)

    first = index_chunks(chunks, config, embeddings)
    second = index_chunks(chunks, config, embeddings)

    assert first["num_added"] == CHUNK_COUNT
    assert second["num_skipped"] == CHUNK_COUNT
    assert second["num_added"] == 0
    assert second["num_deleted"] == 0
