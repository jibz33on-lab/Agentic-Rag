"""The keyword half of hybrid search, built from the chunks Qdrant already holds.

BM25 scores term frequency, term rarity across the collection and chunk length.
It reads the text itself and never embeds anything, which is the whole reason it
is here: the embedding_model and the reranker both score meaning, so a reranker
inherits bge-m3's blind spot rather than correcting it. BM25 can fail
differently.

The chunks come from Qdrant rather than from re-reading and re-splitting data/.
Re-splitting would produce byte-identical chunks and verify-corpus already exists
to catch drift, but scrolling the collection makes corpus parity structural
instead of remembered: BM25 indexes literally what the vector_store searches, so
the two halves of a fused query cannot be searching different corpora.

The retriever is ours rather than LangChain's. `BM25Retriever` lives in
`langchain_community`, which announces on import that it is being sunset — the
same objection reranker.py raised when it declined `HuggingFaceCrossEncoder` and
subclassed `langchain_core` instead. `BaseRetriever` is maintained, is already a
dependency, and `rank_bm25` is a plain dependency doing the actual scoring.

The index is in memory and holds no state between processes. It is built once per
run and passed in, so a corpus change means re-running indexing and then building
a new index from Qdrant before querying.
"""

import re
from typing import Any

from config import Config
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_qdrant import QdrantVectorStore
from pydantic import ConfigDict
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

# Qdrant's own default scroll limit is far smaller than the corpus, and reading
# one page is the failure this module's pagination exists to avoid. Large enough
# that the whole collection usually arrives in one round trip, without assuming
# it does.
SCROLL_PAGE_SIZE = 256


# Terms are runs of letters and digits. Everything else is a separator, so a
# term matches whatever punctuation happens to sit against it in the source.
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def tokenise(text: str) -> list[str]:
    """Split text into the terms BM25 scores, lowercased.

    Not `text.split()`, which is what rank_bm25 is usually paired with. Under
    that, `Depends` does not match `Depends()`, `502` does not match `502.`, and
    `RRF` does not match `RRF,` — so every query term misses, every chunk scores
    zero, and BM25 contributes storage order to fusion. This experiment is
    testing whether literal tokens recover the evidence semantic retrieval
    misses, and that preprocessor would manufacture the null result.

    Case is folded here, unlike in evaluators.normalise, which preserves it
    deliberately so a paraphrasing generator cannot hide. Nothing is being
    checked for honesty here — these are terms to match, and a question asking
    about `RRF` means the same as a chunk saying `rrf`.
    """
    return TOKEN_PATTERN.findall(text.lower())


class BM25Retriever(BaseRetriever):
    """Ranks every chunk in the collection by BM25 and returns the best `k`."""

    chunks: list[Document]
    okapi: Any
    k: int

    # BM25Okapi is a plain rank_bm25 object, not a pydantic type.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Document]:
        """The `k` highest-scoring chunks, best first.

        Scores are zipped with indices rather than with the Documents. Two chunks
        scoring identically would otherwise make Python compare Documents, which
        are not orderable, and the whole query would die on a tie — the same trap
        CrossEncoderReranker.compress_documents documents.
        """
        scores = self.okapi.get_scores(tokenise(query))
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
        return [self.chunks[position] for position, _ in ranked[: self.k]]


def build_bm25_retriever(config: Config, client: QdrantClient | None = None) -> BM25Retriever:
    """A BM25 retriever over every chunk in the collection, fetching CANDIDATE_COUNT.

    `k` comes from `config.candidate_count`, the same value the vector half
    fetches, so neither retriever can quietly contribute a different number of
    candidates to fusion.

    `client` exists so a test can drive pagination without a running Qdrant.
    Callers pass nothing and get the real one.
    """
    client = client or QdrantClient(url=config.qdrant_url)
    expected = client.count(config.collection_name, exact=True).count
    chunks = _scroll_all(client, config.collection_name)
    _refuse_an_unusable_index(chunks, expected, config.collection_name)
    okapi = BM25Okapi([tokenise(chunk.page_content) for chunk in chunks])
    return BM25Retriever(chunks=chunks, okapi=okapi, k=config.candidate_count)


def _refuse_an_unusable_index(chunks: list[Document], expected: int, collection_name: str) -> None:
    """Never build an index over an empty or partial collection.

    Qdrant's scroll() returns a page plus a next_page_offset and its default
    limit is far below the corpus. A short read is silent everywhere else: every
    query still returns CANDIDATE_COUNT candidates, fusion still runs, the
    evaluation_run completes, and the numbers come back worse than they should
    be with nothing saying why. The prompt-token fault band cannot see it, since
    a short index changes which chunks are selected rather than how many.

    An empty collection passes the count comparison — both sides are zero — so it
    is checked first. rank_bm25 would otherwise fail it as a ZeroDivisionError on
    an average document length, which says nothing about the collection.

    Failing here costs one count() call and happens before any query is embedded.
    """
    if not chunks:
        raise RuntimeError(
            f"Collection {collection_name!r} is empty, so there is nothing for BM25 "
            f"to index. An empty index is not a quiet way to run vector-only: fusion "
            f"would degenerate to a vector search cut to TOP_K and report a number "
            f"near baseline that reads as hybrid not helping. Run ingest first, or "
            f"pass None to retrieve() to run the vector-only baseline deliberately."
        )
    if len(chunks) != expected:
        raise RuntimeError(
            f"The BM25 index would hold {len(chunks)} chunks but collection "
            f"{collection_name!r} holds {expected}. Hybrid search will not run on a "
            f"partial corpus: BM25 would search a fraction of what the vector_store "
            f"searches, every query would still return CANDIDATE_COUNT candidates, "
            f"and the evaluation_run would complete and report numbers that read as "
            f"hybrid not helping. Re-run ingest if the collection is mid-rebuild."
        )


def _scroll_all(client: QdrantClient, collection_name: str) -> list[Document]:
    """Every point in the collection, as Documents, following next_page_offset.

    The payload keys are QdrantVectorStore's own constants rather than string
    literals, so a change in how LangChain stores a chunk cannot silently leave
    this reading the wrong field and indexing 126 empty documents.
    """
    chunks: list[Document] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=SCROLL_PAGE_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        chunks.extend(
            Document(
                page_content=point.payload[QdrantVectorStore.CONTENT_KEY],
                metadata=point.payload.get(QdrantVectorStore.METADATA_KEY) or {},
            )
            for point in points
        )
        if offset is None:
            return chunks
