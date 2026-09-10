from types import SimpleNamespace

import pytest
from bm25 import build_bm25_retriever
from config import load_config


def _config(**overrides):
    return load_config(env={"OPENROUTER_API_KEY": "sk-or-test", **overrides})


def _fake_client(texts, page_size, reported_count=None):
    """Stands in for QdrantClient: scroll() hands back one page at a time with a
    next_page_offset, and count() reports the true total — the two facts the
    build has to reconcile.

    `reported_count` lets the two disagree, which is the only way to simulate a
    collection read that came back short."""

    def scroll(collection_name, limit, offset=None, **kwargs):
        start = offset or 0
        page = [
            SimpleNamespace(payload={"page_content": text, "metadata": {}})
            for text in texts[start : start + page_size]
        ]
        nxt = start + page_size if start + page_size < len(texts) else None
        return page, nxt

    return SimpleNamespace(
        scroll=scroll,
        count=lambda collection_name, exact=True: SimpleNamespace(
            count=len(texts) if reported_count is None else reported_count
        ),
    )


def test_indexes_every_chunk_in_the_collection_across_scroll_pages():
    """Qdrant's scroll() returns one page plus a next_page_offset, and its default
    limit is far below the corpus size. A build that reads the first page and
    stops indexes a fraction of the collection, returns 20 candidates for every
    query, completes cleanly, and reports numbers that read as 'hybrid didn't
    help'. Nothing else in the pipeline notices — the ±15% prompt-token fault
    band cannot see it, because a short index changes which chunks are selected,
    not how many.
    """
    texts = [f"chunk {i}" for i in range(126)]
    client = _fake_client(texts, page_size=64)

    retriever = build_bm25_retriever(_config(), client=client)

    assert len(retriever.chunks) == 126


def test_matches_a_query_term_against_its_punctuated_form_in_a_chunk():
    """The experiment's whole premise is that required quotes carry literal
    tokens BM25 matches exactly. Under `text.split()` they do not: 'Depends'
    and 'Depends()' are different terms, as are '502' and '502.', and 'RRF'
    and 'RRF,'. Every query term would then miss, every chunk would score
    zero, and BM25 would contribute its arbitrary storage order to fusion —
    a null Step 0 indistinguishable from the lexical hypothesis being wrong.

    This is the retrieval-side twin of `normalise()` in evaluators.py, which
    exists because otherwise 'a quote that is genuinely present scores a miss,
    and a whole dataset of them looks like terrible retrieval rather than a
    broken ruler'.
    """
    texts = [
        "the router collects handlers",
        "settings are read once at startup",
        "FastAPI resolves Depends() before the handler runs",
    ]
    client = _fake_client(texts, page_size=64)
    retriever = build_bm25_retriever(_config(CANDIDATE_COUNT="1"), client=client)

    found = retriever.invoke("What does Depends do?")

    assert found[0].page_content == texts[2]


def test_raises_when_the_scroll_returns_fewer_chunks_than_the_collection_holds():
    """A short read is silent everywhere else. Every query still returns
    CANDIDATE_COUNT candidates, fusion still runs, the evaluation_run still
    completes, and the numbers come back worse than they should be with nothing
    saying why. The ±15% prompt-token fault band cannot see it either: a short
    index changes which chunks are selected, not how many.

    So it fails here, at build time, before a single query is embedded and
    before any money is spent — the same stance build_reranker takes when
    RERANKER_MODEL is set but unloadable, and for the same reason. An
    evaluation_run that quietly measured something other than what it claimed
    is the failure this design exists to prevent.
    """
    client = _fake_client([f"chunk {i}" for i in range(64)], page_size=64, reported_count=126)

    with pytest.raises(RuntimeError, match="126"):
        build_bm25_retriever(_config(), client=client)


def test_raises_when_the_collection_is_empty():
    """An empty collection passes the short-scroll check — count() and scroll()
    agree at zero — so it needs its own guard. Without one, fusion degenerates
    to vector-search-at-CANDIDATE_COUNT-cut-to-TOP_K, the run completes, and it
    reports a number near baseline that reads as 'hybrid didn't help'.

    An empty BM25 index is not a legitimate vector-only mode. Vector-only is the
    None path through retrieve(), explicitly chosen at the call site.
    """
    client = _fake_client([], page_size=64)

    with pytest.raises(RuntimeError, match="empty"):
        build_bm25_retriever(_config(), client=client)
