from conftest import FAKE_DIMENSIONS
from indexing import index_chunks
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

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
