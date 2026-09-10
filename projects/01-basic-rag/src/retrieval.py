"""Finds the chunks closest to a question, and optionally reranks them."""

from config import Config
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.embeddings import Embeddings
from vector_store import open_vector_store


def retrieve(
    query: str,
    config: Config,
    embeddings: Embeddings,
    reranker: BaseDocumentCompressor | None,
) -> list[Document]:
    """Return the chunks the answerer should see, best first.

    Without a `reranker` this is a plain nearest-neighbour search for TOP_K —
    exactly what this function did before reranking existed, which is what lets
    the baseline be reproduced on this code.

    With one, it fetches CANDIDATE_COUNT candidates and the reranker chooses
    which TOP_K of them survive. The embedding_model compared two vectors built
    apart; the reranker reads the query and the chunk together. That is the
    whole point: the wider fetch costs one larger search, and the accuracy comes
    from scoring pairs rather than from looking at more chunks.

    `reranker` has no default. Omitting it would silently mean "no reranking",
    and an evaluation_run that quietly skipped the reranker would carry baseline
    numbers under a reranked label.

    TOP_K is read from `config` rather than passed in, so the number of chunks
    reaching the answerer has exactly one source. A reranker built with its own
    top_n cannot disagree with it.
    """
    store = open_vector_store(config, embeddings)

    if reranker is None:
        return store.as_retriever(search_kwargs={"k": config.top_k}).invoke(query)

    candidates = store.as_retriever(search_kwargs={"k": config.candidate_count}).invoke(query)
    return reranker.compress_documents(candidates, query)[: config.top_k]
