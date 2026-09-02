from conftest import FAKE_DIMENSIONS
from indexing import index_chunks
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from retrieval import retrieve


def test_retrieves_the_requested_number_of_chunks(services, config):
    chunks = [
        Document(page_content=f"chunk {i}", metadata={"source": "test.pdf"}) for i in range(20)
    ]
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)
    index_chunks(chunks, config, embeddings)

    found = retrieve("chunk 3", config, embeddings, k=5)

    assert len(found) == 5
