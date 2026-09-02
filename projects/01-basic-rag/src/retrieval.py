"""Finds the chunks closest to a question."""

from vector_store import open_vector_store


def retrieve(query, config, embeddings, k):
    """Return the `k` chunks nearest to `query`.

    No chat model is involved. The query is turned into numbers by the same
    embedding model that built the collection, and Qdrant returns whatever
    sits closest to it.
    """
    store = open_vector_store(config, embeddings)
    return store.as_retriever(search_kwargs={"k": k}).invoke(query)
