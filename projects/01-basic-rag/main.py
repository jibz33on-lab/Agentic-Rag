"""Terminal entry point: ingest the data folder, then ask it questions.

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
from document_loader import load_documents
from evaluation.evaluators import evidence, make_judge
from evaluation.golden_dataset import (
    GOLDEN_EXAMPLES,
    choose_chunks,
    make_generator,
    push,
    read_chunks,
)
from guardrails import NoAnswerError
from indexing import build_embeddings, index_chunks
from rag_query import rag_query
from text_splitter import split_documents


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


def run_evaluation(config):
    """One experiment: the dataset, unchanged, against this configuration."""
    from langsmith import Client
    from langsmith.evaluation import evaluate

    embeddings = build_embeddings(config)
    model = build_chat_model(config)

    def target(inputs: dict) -> dict:
        result = rag_query(inputs["question"], config, embeddings, model)
        return {
            "answer": result.answer,
            "chunk_texts": [chunk.page_content for chunk in result.chunks],
        }

    print(f"{config.langsmith_dataset} | {config.collection_name} | {config.answerer_model}")
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
    print(f"{config.collection_name} | {config.answerer_model}")
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
            result = rag_query(question, config, embeddings, model, show)
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
    parser.add_argument("command", choices=["ingest", "ask", "golden-set", "evaluate"])
    args = parser.parse_args()

    load_dotenv(".env")  # third-party libraries read os.environ, not our config
    config = load_config(os.environ)

    if args.command == "ingest":
        ingest(config)
    elif args.command == "golden-set":
        golden_set(config)
    elif args.command == "evaluate":
        run_evaluation(config)
    else:
        ask(config)


if __name__ == "__main__":
    main()
