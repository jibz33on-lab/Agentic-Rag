"""Terminal entry point: ingest the data folder, then ask it questions.

    uv run python projects/01-basic-rag/main.py verify-corpus
    uv run python projects/01-basic-rag/main.py ingest
    uv run python projects/01-basic-rag/main.py ask

Run from the repo root, so that DATA_FOLDER and .env resolve.
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

from answerer import build_chat_model
from config import load_config
from corpus import MANIFEST_NAME, check_corpus, is_intact, parse_manifest
from document_loader import load_documents
from evaluation.evaluators import evidence, make_judge
from evaluation.golden_dataset import (
    GOLDEN_EXAMPLES,
    choose_chunks,
    choose_related_groups,
    make_generator,
    make_multi_generator,
    push,
    read_chunks,
)
from guardrails import NoAnswerError
from indexing import build_embeddings, index_chunks
from rag_query import rag_query
from reranker import build_reranker
from text_splitter import split_documents


def verify_corpus(config):
    """Is the data folder the corpus the benchmark numbers were measured on?

    Worth running before ingest, and before believing a comparison against an
    older experiment. Exits non-zero when it is not, so CI can call it.
    """
    folder = Path(config.data_folder)
    manifest_path = folder / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SystemExit(f"no manifest at {manifest_path}. See {folder}/README.md")

    checks = check_corpus(folder, parse_manifest(manifest_path.read_text()))
    for check in checks:
        print(f"  {check.status:<9} {check.name}")
        if check.status == "changed":
            print(f"    expected {check.expected}\n    got      {check.actual}")

    if is_intact(checks):
        print(f"{len(checks)} files, all matching {manifest_path}")
        return
    raise SystemExit(
        f"\n{folder}/ is not the corpus the benchmark was built on. Chunk ids and "
        "the dataset's verbatim quotes are tied to these exact files, so an "
        "evaluation run now is not comparable to the recorded experiments."
    )


def ingest(config):
    """Read the data folder and put its chunks in the store."""
    print(f"reading {config.data_folder}/ ...")
    result = load_documents(config.data_folder)

    for failure in result.failures:
        print(f"  skipped {failure.path.name}: {failure.reason}")

    chunks = split_documents(result.documents, config.chunk_size, config.chunk_overlap)
    print(f"  {len(result.documents)} documents -> {len(chunks)} chunks")

    print(f"indexing into {config.collection_name} ...")
    counts = index_chunks(chunks, config, build_embeddings(config))
    print(
        f"  added {counts['num_added']}"
        f", skipped {counts['num_skipped']}"
        f", updated {counts['num_updated']}"
        f", deleted {counts['num_deleted']}"
    )


def _openai(config):
    """The evaluation apparatus' client, traced.

    wrap_openai puts every generator and judge call in LangSmith. The judge is
    otherwise the least inspectable part of the system — it emits a verdict and
    nothing else — and this is the difference between "the judge said incorrect"
    and seeing why.
    """
    from langsmith.wrappers import wrap_openai
    from openai import OpenAI

    if not config.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. The evaluation apparatus runs on OpenAI, "
            "deliberately a different provider from the answerer under test. "
            "ingest and ask do not need it."
        )
    return wrap_openai(OpenAI(api_key=config.openai_api_key))


def golden_set(config):
    """Sample the corpus, write examples, push them to LangSmith.

    LangSmith owns the dataset after this. Nothing is kept locally: two sources
    of truth for a reference set is one more than can be right.
    """
    from langsmith import Client
    from qdrant_client import QdrantClient

    chunks = read_chunks(QdrantClient(url=config.qdrant_url), config.collection_name)
    print(f"{len(chunks)} chunks in {config.collection_name}")

    sample = choose_chunks(chunks, GOLDEN_EXAMPLES)
    generate = make_generator(_openai(config), config.generator_model)

    examples, discarded = [], 0
    for chunk in sample:
        example = generate(chunk)
        if example is None:
            discarded += 1
            print(f"  discarded a chunk from {Path(chunk['source']).name}")
            continue
        examples.append(example)

    print(f"{len(examples)} examples, {discarded} discarded")
    if not examples:
        return

    dataset = push(Client(), config.langsmith_dataset, examples)
    print(f"pushed to LangSmith dataset {dataset.name}")


def golden_set_multi(config, count):
    """Add multi-chunk examples to the dataset that already exists.

    Appends rather than replaces. The single-chunk examples are still a valid
    test — they just cannot show whether retrieval can assemble an answer from
    more than one chunk, which is what these add.
    """
    from langsmith import Client
    from qdrant_client import QdrantClient

    chunks = read_chunks(QdrantClient(url=config.qdrant_url), config.collection_name)
    groups = choose_related_groups(chunks, groups=count)
    print(f"{len(groups)} groups of related chunks, sizes {[len(g) for g in groups]}")

    generate = make_multi_generator(_openai(config), config.generator_model)
    examples, discarded = [], 0
    for group in groups:
        example = generate(group)
        if example is None:
            discarded += 1
            print(f"  discarded a group of {len(group)}")
            continue
        examples.append(example)

    print(f"{len(examples)} multi-chunk examples, {discarded} discarded")
    if not examples:
        return
    dataset = push(Client(), config.langsmith_dataset, examples)
    print(f"appended to LangSmith dataset {dataset.name}")


def benchmark(config, dataset_name, size, count, attempts, seed):
    """Add `count` validated examples of a given chunk size to `dataset_name`.

    One size per run, so a build is short, resumable, and its cost visible.
    Size 1 reuses the single-chunk generator; 2-4 reuse the multi-chunk one,
    including its check that no single chunk answers the question.

    Questions already in the dataset are skipped, so re-running to top up a
    size cannot introduce a duplicate.
    """
    from langsmith import Client
    from qdrant_client import QdrantClient

    ls = Client()
    existing = set()
    if ls.has_dataset(dataset_name=dataset_name):
        existing = {
            " ".join((e.inputs.get("question") or "").lower().split())
            for e in ls.list_examples(dataset_name=dataset_name)
        }
    print(f"{dataset_name}: {len(existing)} examples already, want {count} more of size {size}")

    chunks = read_chunks(QdrantClient(url=config.qdrant_url), config.collection_name)
    client = _openai(config)

    if size == 1:
        candidates = [[c] for c in choose_chunks(chunks, attempts, seed=seed)]
        generate = make_generator(client, config.generator_model)
        produce = lambda group: generate(group[0])  # noqa: E731
    else:
        candidates = choose_related_groups(chunks, groups=attempts, seed=seed, size=size)
        produce = make_multi_generator(client, config.generator_model)

    accepted, rejected, duplicates = [], 0, 0
    for group in candidates:
        if len(accepted) >= count:
            break
        example = produce(group)
        if example is None:
            rejected += 1
            continue
        key = " ".join(example["question"].lower().split())
        if key in existing:
            duplicates += 1
            continue
        existing.add(key)
        accepted.append(example)

    print(
        f"accepted {len(accepted)}, rejected {rejected}, duplicates {duplicates}"
        f" (from {len(candidates)} candidates)"
    )
    if not accepted:
        return
    dataset = push(ls, dataset_name, accepted)
    print(f"appended to {dataset.name}")


def _reranking(config) -> str:
    """One line saying whether reranking is on, printed by ask and evaluate.

    Worth the space: reranking is optional, and the difference between a
    reranked run and a baseline one is otherwise invisible from the terminal.
    """
    if not config.reranker_model:
        return "no reranker"
    return f"reranking {config.candidate_count} -> {config.top_k} with {config.reranker_model}"


def run_evaluation(config):
    """One experiment: the dataset, unchanged, against this configuration."""
    from langsmith import Client
    from langsmith.evaluation import evaluate

    embeddings = build_embeddings(config)
    model = build_chat_model(config)
    # Before the first question, so a model that will not load ends the run here
    # rather than fifteen examples in, having already spent money.
    reranker = build_reranker(config)

    def target(inputs: dict) -> dict:
        result = rag_query(inputs["question"], config, embeddings, model, reranker)
        return {
            "answer": result.answer,
            "chunk_texts": [chunk.page_content for chunk in result.chunks],
        }

    print(
        f"{config.langsmith_dataset} | {config.collection_name} | {config.answerer_model}"
        f" | {_reranking(config)}"
    )
    results = evaluate(
        target,
        data=config.langsmith_dataset,
        evaluators=[evidence, make_judge(_openai(config), config.judge_model)],
        experiment_prefix=config.collection_name,
        # What separates one experiment from another. Without it the comparison
        # view shows two runs and no way to tell what changed between them.
        metadata={
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "top_k": config.top_k,
            # Recorded because the reranker is optional. An experiment that
            # silently ran without it would sit in LangSmith labelled reranked,
            # carrying baseline numbers, with nothing to reveal the difference.
            "reranking": reranker is not None,
            "reranker_model": config.reranker_model,
            "candidate_count": config.candidate_count if reranker else None,
            "embedding_model": config.embedding_model,
            "answerer_model": config.answerer_model,
            "judge_model": config.judge_model,
        },
        max_concurrency=1,
        client=Client(),
    )
    print(f"\n{results}")


def streaming_printer():
    """A printer that prints each piece and remembers when the first arrived."""
    timings = {}

    def show(piece):
        if "first_token" not in timings and piece:
            timings["first_token"] = time.monotonic()
        print(piece, end="", flush=True)

    return show, timings


def ask(config):
    """Answer questions until you stop asking."""
    embeddings = build_embeddings(config)
    model = build_chat_model(config)
    reranker = build_reranker(config)
    print(f"{config.collection_name} | {config.answerer_model} | {_reranking(config)}")
    print("Ask a question, or 'quit' to stop.\n")

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            return

        started = time.monotonic()
        show, timings = streaming_printer()

        print()
        try:
            result = rag_query(question, config, embeddings, model, reranker, show)
        except NoAnswerError as error:
            print(f"\n  {error}\n")
            continue
        finished = time.monotonic()
        print("\n")

        first_token = timings.get("first_token", finished)

        # Printed every time on purpose: when an answer is wrong, this is how
        # you tell whether retrieval found the wrong text or the model misread
        # the right text.
        for i, chunk in enumerate(result.chunks, 1):
            source = Path(chunk.metadata.get("source") or "?").name
            page = chunk.metadata.get("page")
            print(f"  [{i}] {source}  page {page if page is not None else '-'}")

        # Timings are printed because latency here varies a lot: OpenRouter
        # routes to whichever of ~30 providers is serving the model, and they
        # differ. Splitting it out shows whether a slow answer was retrieval,
        # a slow provider, or simply a long answer.
        print(
            f"\n  {first_token - started:.1f}s to first word"
            f" | {finished - started:.1f}s total"
            f" | traced as rag_query\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["ingest", "ask", "golden-set", "evaluate", "benchmark", "verify-corpus"],
    )
    parser.add_argument("--dataset", default=None, help="benchmark: dataset name to build")
    parser.add_argument("--size", type=int, default=1, help="benchmark: chunks per question")
    parser.add_argument("--count", type=int, default=5, help="benchmark: examples to accept")
    parser.add_argument("--attempts", type=int, default=30, help="benchmark: candidates to try")
    parser.add_argument("--seed", type=int, default=0, help="benchmark: grouping seed")
    parser.add_argument(
        "--multi",
        type=int,
        default=0,
        metavar="N",
        help="with golden-set: add N multi-chunk examples instead of generating single-chunk ones",
    )
    args = parser.parse_args()

    load_dotenv(".env")  # third-party libraries read os.environ, not our config
    config = load_config(os.environ)

    if args.command == "verify-corpus":
        verify_corpus(config)
    elif args.command == "ingest":
        ingest(config)
    elif args.command == "golden-set":
        if args.multi:
            golden_set_multi(config, args.multi)
        else:
            golden_set(config)
    elif args.command == "benchmark":
        benchmark(
            config,
            args.dataset or config.langsmith_dataset,
            args.size,
            args.count,
            args.attempts,
            args.seed,
        )
    elif args.command == "evaluate":
        run_evaluation(config)
    else:
        ask(config)


if __name__ == "__main__":
    main()
