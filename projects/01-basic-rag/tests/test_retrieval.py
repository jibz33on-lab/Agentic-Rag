from conftest import FAKE_DIMENSIONS
from indexing import index_chunks
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from retrieval import retrieve


def _indexed(config, count=30):
    """Put `count` chunks in a throwaway collection and hand back the embeddings."""
    chunks = [
        Document(page_content=f"chunk {i}", metadata={"source": "test.pdf"}) for i in range(count)
    ]
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)
    index_chunks(chunks, config, embeddings)
    return embeddings


def test_retrieves_top_k_chunks_when_there_is_no_reranker(services, config):
    embeddings = _indexed(config, count=20)

    found = retrieve("chunk 3", config, embeddings, None)

    assert len(found) == config.top_k


def test_returns_the_rerankers_choice_from_a_wider_candidate_fetch(services, config):
    """With a reranker, retrieval fetches CANDIDATE_COUNT candidates and the
    reranker decides which TOP_K of them reach the answerer. The fake reverses
    vector order, so the result proves the ordering came from the reranker."""
    embeddings = _indexed(config, count=30)
    seen = {}

    class ReversingReranker:
        def compress_documents(self, documents, query, callbacks=None):
            seen["candidates"] = len(documents)
            return list(reversed(documents))[: config.top_k]

    found = retrieve("chunk 3", config, embeddings, ReversingReranker())

    assert seen["candidates"] == config.candidate_count
    assert len(found) == config.top_k
