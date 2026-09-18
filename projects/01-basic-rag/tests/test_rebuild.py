"""The full-rebuild write path used by AWS ingestion.

These use the real Qdrant from docker-compose with fake embeddings, the same
way the indexing tests do, because what is under test is what happens to a
collection — which a fake store would not tell us.

Note what is absent: no Postgres fixture and no record manager. That is the
point of the path. See `designs/environments.md`.
"""

from conftest import FAKE_DIMENSIONS
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient
from rebuild import rebuild_collection

CHUNK_COUNT = 30


def chunks(count: int, text: str = "chunk") -> list[Document]:
    return [
        Document(page_content=f"{text} number {i}", metadata={"source": "test.pdf", "page": i})
        for i in range(count)
    ]


def qdrant(config) -> QdrantClient:
    return QdrantClient(url=config.qdrant_url)


def test_rebuilding_writes_every_chunk(qdrant_only, config):
    written = rebuild_collection(
        chunks(CHUNK_COUNT), config, DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)
    )

    assert written == CHUNK_COUNT
    assert qdrant(config).count(config.collection_name).count == CHUNK_COUNT


def test_rebuilding_twice_does_not_double_the_collection(qdrant_only, config):
    """The difference from `ingest`, and the reason this path needs no state.

    `index_chunks` would skip on the second run by consulting the record
    manager. This drops the collection instead, so the count is the same
    without anything remembering the first run.
    """
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)

    rebuild_collection(chunks(CHUNK_COUNT), config, embeddings)
    rebuild_collection(chunks(CHUNK_COUNT), config, embeddings)

    assert qdrant(config).count(config.collection_name).count == CHUNK_COUNT


def test_rebuilding_removes_chunks_whose_source_document_is_gone(qdrant_only, config):
    """A full rebuild is how a deleted document leaves the collection.

    With no record manager there is no cleanup pass, so this only holds
    because the collection is dropped outright.
    """
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)

    rebuild_collection(chunks(CHUNK_COUNT, text="original"), config, embeddings)
    rebuild_collection(chunks(5, text="replacement"), config, embeddings)

    assert qdrant(config).count(config.collection_name).count == 5


def test_rebuilding_into_a_staging_name_leaves_the_live_collection_untouched(qdrant_only, config):
    """What protects the live corpus while a rebuild is being verified."""
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)
    staging = f"{config.collection_name}-staging"

    rebuild_collection(chunks(CHUNK_COUNT), config, embeddings)
    rebuild_collection(chunks(5), config, embeddings, collection_name=staging)

    client = qdrant(config)
    assert client.count(config.collection_name).count == CHUNK_COUNT
    assert client.count(staging).count == 5
    client.delete_collection(staging)


def test_chunk_metadata_survives_the_write(qdrant_only, config):
    """`source` and `page` are what the API prints and the benchmark matches on.

    `add_documents` carries metadata into the Qdrant payload rather than the
    record manager doing it, so this is worth asserting directly.
    """
    rebuild_collection(chunks(3), config, DeterministicFakeEmbedding(size=FAKE_DIMENSIONS))

    points, _ = qdrant(config).scroll(config.collection_name, limit=3, with_payload=True)
    sources = {point.payload["metadata"]["source"] for point in points}
    assert sources == {"test.pdf"}
    assert all("page" in point.payload["metadata"] for point in points)
