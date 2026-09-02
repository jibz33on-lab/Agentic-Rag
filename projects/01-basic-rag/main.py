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
from langsmith import traceable

sys.path.insert(0, str(Path(__file__).parent / "src"))

from answerer import build_chat_model, stream_answer
from config import load_config
from document_loader import load_documents
from indexing import build_embeddings, index_chunks
from retrieval import retrieve
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


@traceable(name="rag_query", run_type="chain")
def answer_one(question, config, embeddings, model, on_piece):
    """Retrieve, then answer — as one traced unit.

    The decorator is what makes LangSmith record retrieval and generation as
    children of a single query, rather than as two unrelated top-level runs.
    It is the difference between "an LLM call took 26s" and "this question
    took 26s, of which 2s was retrieval".

    on_piece is called with each piece as it arrives, so the caller can print
    a streaming answer without the printing happening in here.
    """
    chunks = retrieve(question, config, embeddings, config.top_k)
    answer = ""
    for piece in stream_answer(question, chunks, model):
        on_piece(piece)
        answer += piece
    return {
        "answer": answer,
        "chunks": [
            {
                "source": chunk.metadata.get("source"),
                "page": chunk.metadata.get("page"),
            }
            for chunk in chunks
        ],
    }


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
    print(f"{config.collection_name} | {config.llm_model}")
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
        result = answer_one(question, config, embeddings, model, show)
        finished = time.monotonic()
        print("\n")

        chunks = result["chunks"]
        first_token = timings.get("first_token", finished)

        # Printed every time on purpose: when an answer is wrong, this is how
        # you tell whether retrieval found the wrong text or the model misread
        # the right text.
        for i, chunk in enumerate(chunks, 1):
            source = Path(chunk.get("source") or "?").name
            page = chunk.get("page")
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
    parser.add_argument("command", choices=["ingest", "ask"])
    args = parser.parse_args()

    load_dotenv(".env")  # third-party libraries read os.environ, not our config
    config = load_config(os.environ)

    if args.command == "ingest":
        ingest(config)
    else:
        ask(config)


if __name__ == "__main__":
    main()
