"""Terminal entry point: ingest the data folder, then ask it questions.

    uv run python projects/01-basic-rag/main.py ingest
    uv run python projects/01-basic-rag/main.py ask

Run from the repo root, so that DATA_FOLDER and .env resolve.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

from answerer import answer_question, build_chat_model
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

        chunks = retrieve(question, config, embeddings, config.top_k)
        print(f"\n{answer_question(question, chunks, model)}\n")

        # Printed every time on purpose: when an answer is wrong, this is how
        # you tell whether retrieval found the wrong text or the model misread
        # the right text.
        for i, chunk in enumerate(chunks, 1):
            source = Path(chunk.metadata.get("source", "?")).name
            page = chunk.metadata.get("page", "-")
            print(f"  [{i}] {source}  page {page}")
        print()


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
