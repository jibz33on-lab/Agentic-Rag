"""Reorders candidates by reading the query and each chunk together.

The embedding_model encodes the query and a chunk separately and compares two
vectors, which is what makes it cheap enough to search the whole collection and
also why it is imprecise. A cross-encoder reads both texts at once — far more
accurate, far too slow for the whole corpus, and affordable over
CANDIDATE_COUNT candidates.

The compressor is ours rather than LangChain's. `CrossEncoderReranker` lives in
`langchain_classic` and `HuggingFaceCrossEncoder` in `langchain_community`,
which announces on import that it is being sunset. Both would be new deprecated
surfaces in a new component, next to the SQLRecordManager import that indexing.py
already calls the most fragile in the project. `BaseDocumentCompressor` comes
from `langchain_core`, is maintained, is already a dependency, and is already the
type `retrieve` is annotated against — so this subclasses that and drives
sentence-transformers directly.

sentence-transformers and torch are the optional `rerank` extra, imported inside
load_cross_encoder rather than at module level. That keeps this module importable
with reranking off, so CI runs every test here without installing torch.
"""

import warnings
from collections.abc import Callable
from typing import Any

from config import Config
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from pydantic import ConfigDict

# A rough characters-per-token ratio for English prose. Only ever used to decide
# whether to warn, so being approximate costs nothing.
CHARS_PER_TOKEN = 4
# Room for the question, which shares the token budget with the chunk.
QUESTION_TOKENS = 64


class CrossEncoderReranker(BaseDocumentCompressor):
    """Scores every (query, chunk) pair and keeps the best `top_n`."""

    encoder: Any
    top_n: int

    # The encoder is a sentence-transformers CrossEncoder, not a pydantic type.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def compress_documents(
        self,
        documents: list[Document],
        query: str,
        callbacks: Any = None,
    ) -> list[Document]:
        """The `top_n` documents, most relevant first.

        Sorting on the score alone, never on the tuple: two chunks scoring
        identically would otherwise make Python compare the Documents, which
        are not orderable, and the whole query would die on a tie.
        """
        if not documents:
            return []
        scores = self.encoder.predict([(query, doc.page_content) for doc in documents])
        ranked = sorted(zip(scores, documents, strict=True), key=lambda pair: pair[0], reverse=True)
        return [doc for _, doc in ranked[: self.top_n]]


def load_cross_encoder(name: str):
    """Load the cross-encoder. The only place torch is imported."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name)


def build_reranker(
    config: Config,
    load: Callable[[str], Any] | None = None,
) -> CrossEncoderReranker | None:
    """The reranker, or None when RERANKER_MODEL is unset.

    None is not a failure. It is today's pipeline: retrieval fetches TOP_K and
    the answerer sees exactly what it saw before this module existed. That path
    is what the baseline gate reproduces, and it is what lets `ask` work on a
    machine that has never downloaded the model.

    `load` exists so a test can drive the failure path without installing torch
    or downloading 1.1 GB. Callers pass nothing and get the real loader.
    """
    if not config.reranker_model:
        return None

    load = load or load_cross_encoder
    try:
        encoder = load(config.reranker_model)
    except Exception as error:
        # Never fall back to vector order. An evaluation_run would complete,
        # be labelled reranked, and carry baseline numbers — the conclusion
        # "reranking does nothing" from a system that never ran it.
        raise RuntimeError(
            f"RERANKER_MODEL is set to {config.reranker_model!r} but it could not be "
            f"loaded: {error}. Reranking is not optional once configured — retrieval "
            f"will not quietly fall back to vector order. Install the extra with "
            f"`uv sync --extra rerank`, or unset RERANKER_MODEL to run without it."
        ) from error

    _warn_if_chunks_will_not_fit(encoder, config)
    # top_n from config.top_k, the same value retrieve cuts to, so the two
    # cannot disagree about how many chunks reach the answerer.
    return CrossEncoderReranker(encoder=encoder, top_n=config.top_k)


def _warn_if_chunks_will_not_fit(encoder: Any, config: Config) -> None:
    """Warn, do not raise, when a chunk is too long for the reranker to read.

    A cross-encoder over its limit scores a prefix and returns a confident
    number. Nothing errors, so a chunk-size experiment would read the result as
    "larger chunks hurt retrieval" rather than "the reranker only saw half".

    A warning rather than a failure because truncation degrades a ranking; it
    does not corrupt an answer, and at a large CHUNK_SIZE it may be a trade
    worth making. That is the caller's call to make knowingly.
    """
    limit = _token_limit(encoder)
    if limit is None:
        # Deliberately noisy. The alternative is a guard that quietly stops
        # guarding, which is how this project has been bitten before.
        warnings.warn(
            f"Could not read the token limit from {config.reranker_model!r}, so "
            f"CHUNK_SIZE was not checked against it. If chunks are longer than the "
            f"reranker reads, it scores a prefix and its ranking quietly degrades.",
            UserWarning,
            stacklevel=3,
        )
        return

    needed = config.chunk_size // CHARS_PER_TOKEN + QUESTION_TOKENS
    if needed > limit:
        warnings.warn(
            f"CHUNK_SIZE is {config.chunk_size}, about {needed} tokens with the "
            f"question, but {config.reranker_model!r} reads {limit}. Longer chunks "
            f"are truncated, so the reranker scores a prefix and returns a confident "
            f"number for text it never saw. Lower CHUNK_SIZE, or use a reranker with "
            f"a larger window such as BAAI/bge-reranker-v2-m3.",
            UserWarning,
            stacklevel=3,
        )


def _token_limit(encoder: Any) -> int | None:
    """The reranker's token window, or None when it cannot be read.

    `max_length` is public API on sentence-transformers' CrossEncoder, unlike
    the nested attribute the same value sits behind when it is wrapped.
    """
    limit = getattr(encoder, "max_length", None)
    return limit if isinstance(limit, int) else None
