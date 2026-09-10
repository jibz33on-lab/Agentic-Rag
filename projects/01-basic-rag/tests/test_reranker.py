from types import SimpleNamespace

import pytest
from config import load_config
from langchain_core.documents import Document
from reranker import build_reranker


def _config(**overrides):
    return load_config(env={"OPENROUTER_API_KEY": "sk-or-test", **overrides})


def _fake_encoder(scores=None, max_length=512):
    """Stands in for a sentence-transformers CrossEncoder: predict() over pairs,
    and max_length, which is public API rather than a nested internal."""
    scores = scores or {}
    return SimpleNamespace(
        max_length=max_length,
        predict=lambda pairs: [scores.get(text, 0.0) for _, text in pairs],
    )


def test_builds_no_reranker_when_none_is_configured():
    """RERANKER_MODEL unset leaves retrieval exactly as it was. This is the path
    the baseline gate runs on, and it must work without sentence-transformers
    installed — the module imports torch lazily, inside load_cross_encoder."""
    assert build_reranker(_config()) is None


def test_raises_when_the_reranker_model_cannot_be_loaded():
    """Silent fallback to vector order is the failure this design exists to
    prevent: an evaluation_run would complete, be labelled reranked, and report
    baseline numbers. It fails here instead, before any question is asked.

    The loader is injected so CI exercises this path without installing torch
    or downloading a 1.1 GB model. main.py passes nothing and gets the real one.
    """
    config = _config(RERANKER_MODEL="not-a-real-org/not-a-real-model")

    def load(name):
        raise OSError(f"{name} is not a local folder and is not a valid model identifier")

    with pytest.raises(RuntimeError, match="RERANKER_MODEL"):
        build_reranker(config, load=load)


def test_reranks_candidates_by_score_and_cuts_to_top_k():
    """The order comes from the cross-encoder, not from vector order, and the
    answerer receives exactly TOP_K chunks however many candidates arrived."""
    config = _config(RERANKER_MODEL="BAAI/bge-reranker-base", TOP_K="2", CANDIDATE_COUNT="5")
    encoder = _fake_encoder(scores={"a": 0.5, "b": 0.1, "c": 0.9})
    reranker = build_reranker(config, load=lambda name: encoder)
    candidates = [Document(page_content=text) for text in ("a", "b", "c")]

    kept = reranker.compress_documents(candidates, "a question")

    assert [doc.page_content for doc in kept] == ["c", "a"]


def test_survives_candidates_that_score_identically():
    """Sorting on the score alone. Sorting the (score, Document) pair would make
    Python compare two Documents on a tie, and they are not orderable — the
    query would die on a coincidence."""
    config = _config(RERANKER_MODEL="BAAI/bge-reranker-base", TOP_K="2", CANDIDATE_COUNT="5")
    encoder = _fake_encoder(scores={"a": 0.5, "b": 0.5, "c": 0.5})
    reranker = build_reranker(config, load=lambda name: encoder)
    candidates = [Document(page_content=text) for text in ("a", "b", "c")]

    assert len(reranker.compress_documents(candidates, "a question")) == 2


def test_warns_when_chunk_size_crowds_the_reranker_token_limit():
    """bge-reranker-base reads 512 tokens. Past roughly 1800 characters it scores
    a prefix of the chunk and returns a confident number, which during a future
    chunk-size experiment reads as 'larger chunks hurt retrieval'.

    The limit comes from the loaded model, not a constant: RERANKER_MODEL is a
    knob, and bge-reranker-v2-m3 reads 8192."""
    config = _config(RERANKER_MODEL="BAAI/bge-reranker-base", CHUNK_SIZE="4000")

    with pytest.warns(UserWarning, match="CHUNK_SIZE"):
        build_reranker(config, load=lambda name: _fake_encoder(max_length=512))


def test_warns_when_the_reranker_token_limit_cannot_be_read():
    """The guard degrades loudly rather than vanishing. If the attribute ever
    moves, silently skipping the check would leave truncation unnoticed — the
    failure shape this project keeps meeting."""
    config = _config(RERANKER_MODEL="BAAI/bge-reranker-base", CHUNK_SIZE="1000")

    with pytest.warns(UserWarning, match="Could not read the token limit"):
        build_reranker(config, load=lambda name: SimpleNamespace())
