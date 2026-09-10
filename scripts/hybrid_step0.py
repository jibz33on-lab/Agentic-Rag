"""Step 0 of the hybrid search design: does the lexical hypothesis hold?

Two relevance mechanisms have failed the same way. Widening TOP_K eight-fold
moved evidence_rank_reciprocal 0.32 -> 0.50; a cross-encoder moved it 0.46 ->
0.463. Both score meaning, so the reranker inherited bge-m3's blind spot. The
claim behind hybrid search is that the blind spot is lexical — that several
required quotes carry literal tokens BM25 matches exactly.

That claim is measurable without asking a model anything. This runs the 25
benchmark questions through both retrievers at CANDIDATE_COUNT and reports:

    - the overlap between vector top-20 and BM25 top-20, per question
    - where each required chunk ranks in each list
    - the same, restricted to the questions vector search misses at TOP_K=4

It is a gate, not a formality. If the required chunks rank low in BM25 too, that
is three mechanisms with one blind spot, and the work redirects rather than
proceeding to a paid evaluation_run.

    uv run python scripts/hybrid_step0.py

Costs 25 query embeddings and no LLM calls. Needs Qdrant up, an ingested
collection, and LANGSMITH_API_KEY for the dataset.

Evidence is matched with evaluators.find_evidence — the same function the
evidence evaluator uses — so this probe and the experiment it gates cannot drift
into disagreeing about whether a run had its evidence.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "projects/01-basic-rag/src"))

load_dotenv(REPO_ROOT / ".env")

from bm25 import build_bm25_retriever  # noqa: E402
from config import load_config  # noqa: E402
from evaluation.evaluators import find_evidence  # noqa: E402
from indexing import build_embeddings  # noqa: E402
from langsmith import Client  # noqa: E402
from vector_store import open_vector_store  # noqa: E402

# The PRD's fusion parameters, fixed. Not a knob this probe is allowed to turn:
# the whole value of a prediction is that it was made at the settings the
# experiment will actually run at.
RRF_C = 60
RRF_WEIGHTS = (1.0, 1.0)


def fuse(lists: list[list[str]], weights=RRF_WEIGHTS, c: int = RRF_C) -> list[str]:
    """Reciprocal Rank Fusion over ranked lists of chunk text, best first.

    score(chunk) = sum over the lists it appears in of weight / (c + rank).

    Rank positions only, never the retrievers' own scores: a cosine similarity
    and a BM25 score are not on comparable scales and cannot be added.

    Ties keep first-seen order, which is the vector list's order, because dicts
    preserve insertion order and sorted() is stable. Deterministic rather than
    arbitrary, so a re-run of this probe reports the same numbers.
    """
    scores: dict[str, float] = {}
    for texts, weight in zip(lists, weights, strict=True):
        for rank, text in enumerate(texts, 1):
            scores[text] = scores.get(text, 0.0) + weight / (c + rank)
    return sorted(scores, key=lambda text: scores[text], reverse=True)


def reciprocal(found: list[int | None]) -> float:
    """The evidence evaluator's evidence_rank_reciprocal, on one question.

    The DEEPEST required rank, because that is the smallest TOP_K that would
    have retrieved every piece. Zero when any is missing.
    """
    return 1 / max(found) if complete(found) else 0.0


def quotes_of(example) -> list[str]:
    """The spans this example requires, single- and multi-chunk alike."""
    outputs = example.outputs
    return outputs.get("quotes") or [outputs["quote"]]


def ranks(texts: list[str], quotes: list[str]) -> list[int | None]:
    return [find_evidence(texts, quote) for quote in quotes]


def complete(found: list[int | None]) -> bool:
    """Every required quote present. Partial evidence is not evidence."""
    return all(rank is not None for rank in found)


def show(found: list[int | None]) -> str:
    return ",".join("-" if rank is None else str(rank) for rank in found)


def main() -> None:
    config = load_config(os.environ)
    embeddings = build_embeddings(config)
    store = open_vector_store(config, embeddings)
    bm25 = build_bm25_retriever(config)

    print(f"{config.langsmith_dataset} | {config.collection_name}")
    print(f"BM25 index: {len(bm25.chunks)} chunks | depth {config.candidate_count} both sides\n")

    examples = sorted(
        Client().list_examples(dataset_name=config.langsmith_dataset),
        key=lambda e: e.created_at,
    )

    header = f"{'#':>3} {'n':>2} {'vec@20':>8} {'bm25@20':>8} {'ovl':>4}"
    print(f"{header} {'base':>5} {'fused':>10} {'hyb':>5}")
    print("-" * 56)

    rows = []
    for number, example in enumerate(examples, 1):
        question = example.inputs["question"]
        quotes = quotes_of(example)

        vector = store.as_retriever(search_kwargs={"k": config.candidate_count}).invoke(question)
        keyword = bm25.invoke(question)

        vector_texts = [chunk.page_content for chunk in vector]
        keyword_texts = [chunk.page_content for chunk in keyword]

        fused = fuse([vector_texts, keyword_texts])
        fused_top_k = ranks(fused[: config.top_k], quotes)

        row = {
            "n": len(quotes),
            "vector": ranks(vector_texts, quotes),
            "keyword": ranks(keyword_texts, quotes),
            "overlap": len(set(vector_texts) & set(keyword_texts)),
            # The recorded baseline: what the answerer actually saw at TOP_K=4.
            "baseline": complete(ranks(vector_texts[: config.top_k], quotes)),
            # Where the required chunks land once the two lists are fused, and
            # whether they survive the cut to TOP_K. This is the prediction.
            "fused": ranks(fused, quotes),
            "hybrid": complete(fused_top_k),
            "hybrid_rr": reciprocal(fused_top_k),
            "baseline_rr": reciprocal(ranks(vector_texts[: config.top_k], quotes)),
        }
        rows.append(row)
        print(
            f"{number:>3} {row['n']:>2} {show(row['vector']):>8} {show(row['keyword']):>8} "
            f"{row['overlap']:>4} {'ok' if row['baseline'] else 'MISS':>5} "
            f"{show(row['fused']):>10} {'ok' if row['hybrid'] else 'MISS':>5}"
        )

    report(rows, config)


def report(rows: list[dict], config) -> None:
    total = len(rows)
    misses = [row for row in rows if not row["baseline"]]
    overlaps = [row["overlap"] for row in rows]

    print(
        f"\nbaseline evidence_found at TOP_K={config.top_k}: "
        f"{(total - len(misses)) / total:.3f}  ({total - len(misses)}/{total})"
    )
    print(
        "  recorded baseline is 0.680 (17/25) — a different number here means "
        "the collection or the dataset has moved"
    )

    print(f"\noverlap of the two top-{config.candidate_count} lists:")
    print(f"  mean {sum(overlaps) / total:.1f} | min {min(overlaps)} | max {max(overlaps)}")
    print(
        f"  questions with overlap >= {config.top_k}: "
        f"{sum(1 for o in overlaps if o >= config.top_k)}/{total}"
    )
    print(
        f"  at c=60 a chunk in both lists always outranks one in either, so where overlap "
        f">= {config.top_k}\n  the answerer sees only chunks both retrievers agreed on"
    )

    print(f"\nBM25 on all {total} questions:")
    print(
        f"  every required chunk inside its top {config.candidate_count}: "
        f"{sum(1 for r in rows if complete(r['keyword']))}/{total}"
    )

    print(f"\nBM25 on the {len(misses)} questions vector search misses at TOP_K={config.top_k}:")
    if not misses:
        print("  none — the baseline did not reproduce, so this gate cannot be read")
        return
    print(f"  {'vector@20':>10} {'bm25@20':>10} {'fused':>10} {'in top ' + str(config.top_k):>10}")
    for row in misses:
        print(
            f"  {show(row['vector']):>10} {show(row['keyword']):>10} {show(row['fused']):>10} "
            f"{'ok' if row['hybrid'] else 'MISS':>10}"
        )
    print(
        f"\n  complete in BM25's top {config.candidate_count}: "
        f"{sum(1 for r in misses if complete(r['keyword']))}/{len(misses)}"
    )
    print(
        f"  recovered by fusion into top {config.top_k}: "
        f"{sum(1 for r in misses if r['hybrid'])}/{len(misses)}"
    )

    predicted = sum(1 for r in rows if r["hybrid"])
    fixed = [i for i, r in enumerate(rows, 1) if r["hybrid"] and not r["baseline"]]
    broken = [i for i, r in enumerate(rows, 1) if r["baseline"] and not r["hybrid"]]

    print(f"\n{'=' * 60}")
    print(f"PREDICTED HYBRID RESULT — RRF c={RRF_C}, weights {RRF_WEIGHTS}, top {config.top_k}")
    print("=" * 60)
    print(
        f"  evidence_found            {predicted / total:.3f}  ({predicted}/{total})"
        f"    baseline 0.680    bar 0.780"
    )
    print(
        f"  evidence_rank_reciprocal  {sum(r['hybrid_rr'] for r in rows) / total:.3f}"
        f"             baseline {sum(r['baseline_rr'] for r in rows) / total:.3f}"
        f"    diagnostic, no bar"
    )
    print(f"  fixed   {fixed or 'none'}")
    print(f"  broken  {broken or 'none'}")
    print(
        "\n  No LLM was called. correct and grounded cannot be predicted from retrieval alone;"
        "\n  evidence_found is the metric the bar is set on."
    )


if __name__ == "__main__":
    main()
