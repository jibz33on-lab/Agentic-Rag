"""Terminal entry point: ingest the corpus, then check what actually landed.

    uv run python projects/02-bedrock-rag/main.py ingest
    uv run python projects/02-bedrock-rag/main.py verify-chunks

Run from the repo root, so that .env resolves. Both commands need AWS
credentials and an applied infra/core: the knowledge_base and data_source ids
are read from SSM at the paths Terraform publishes them to.

Composition only. The decisions live in the components -- `is_finished` and
`has_failures` on IngestionJobStatus, and the character lengths in
chunk_report -- which is why those are tested and this is not.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

from bedrock_rag.chunk_report import summarise_chunks
from bedrock_rag.config import DEFAULT_REGION, load_config
from bedrock_rag.kb_client import ingestion_job_status, retrieve, start_ingestion_job
from bedrock_rag.parameters import load_parameters

# Bedrock ingestion of a handful of PDFs runs in minutes, so this is slow enough
# not to hammer the API and quick enough that the terminal still looks alive.
POLL_SECONDS = 15

# One query per document in the corpus, so a sample spans all four and a file
# that never appears in `sources` is visibly missing rather than merely unlucky.
# A first guess, written before any ingestion_job has run -- worth revising once
# there is real retrieval to look at.
DEFAULT_QUERIES = (
    "system design fundamentals",
    "langgraph agents and graphs",
    "hybrid search and keyword retrieval",
    "a mental model for agentic systems",
)

# Project 01's CHUNK_SIZE, which maxTokens: 250 is a translation of. Printed
# beside the measured median so the comparison is on screen rather than in
# someone's head.
PROJECT_01_CHUNK_SIZE = 1000


def ingest(config, agent):
    """Start an ingestion_job, wait for it, and report what it did.

    Exits non-zero when any document failed. Bedrock reports a job COMPLETE over
    documents it could not read, so a corpus that is quietly short would
    otherwise look exactly like a retrieval-quality problem three slices later.
    """
    job_id = start_ingestion_job(config, agent)
    print(f"started ingestion_job {job_id}")

    status = ingestion_job_status(job_id, config, agent)
    while not status.is_finished:
        print(f"  {status.status} ...")
        time.sleep(POLL_SECONDS)
        status = ingestion_job_status(job_id, config, agent)

    print(f"\n{status.status}")
    print(f"  scanned  {status.documents_scanned}")
    print(f"  indexed  {status.documents_indexed}")
    print(f"  skipped  {status.documents_skipped}")
    print(f"  deleted  {status.documents_deleted}")
    print(f"  failed   {status.documents_failed}")

    if status.has_failures:
        for reason in status.failure_reasons:
            print(f"    {reason}")
        raise SystemExit(
            f"\ningestion_job {job_id} did not ingest the whole corpus. Retrieval "
            "measured against it would be measuring a corpus that is missing "
            "documents, not a pipeline."
        )


def verify_chunks(config, runtime, queries, number_of_results):
    """Sample stored chunks and report their character lengths and sources.

    Not the read path -- no answerer, no prompt, no trace. Its whole job is to
    confirm documents are retrievable and to check the token-to-character
    translation after the fact, which designs/skeleton.md asks for rather than
    trusting the estimate.
    """
    chunks = []
    for query in queries:
        found = retrieve(query, config, runtime, number_of_results=number_of_results)
        print(f"  {len(found):>3} chunks for {query!r}")
        chunks.extend(found)

    summary = summarise_chunks(chunks)

    if summary.count == 0:
        raise SystemExit(
            "\nno chunks returned. A Retrieve before an ingestion_job finishes "
            "returns empty rather than failing, so check the job completed "
            "before reading this as a retrieval problem."
        )

    print(f"\n{summary.count} chunks sampled, character lengths:")
    print(f"  shortest {summary.shortest}")
    print(f"  median   {summary.median}   (project 01 chunks at {PROJECT_01_CHUNK_SIZE})")
    print(f"  longest  {summary.longest}")

    print(f"\n{len(summary.sources)} documents represented:")
    for source in summary.sources:
        print(f"  {source}")
    print(
        "\nA sample, not the population: these are the chunks that ranked highest "
        "for the queries asked. Enough to check the translation, not to describe "
        "the corpus."
    )


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ingest", "verify-chunks"])
    parser.add_argument(
        "--results",
        type=int,
        default=25,
        help="verify-chunks: chunks to request per query. Wider than TOP_K on "
        "purpose -- this is a sample, not the retrieval the answerer sees.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        default=None,
        help="verify-chunks: a query to sample with. Repeatable. Defaults to one "
        "per document in the corpus.",
    )
    args = parser.parse_args()

    # The SSM client cannot read its region from config, because config is built
    # from what this client fetches. Same resolution order, one step earlier.
    region = os.environ.get("AWS_REGION") or DEFAULT_REGION
    config = load_config(os.environ, load_parameters(boto3.client("ssm", region_name=region)))

    if args.command == "ingest":
        ingest(config, boto3.client("bedrock-agent", region_name=config.region))
    else:
        verify_chunks(
            config,
            boto3.client("bedrock-agent-runtime", region_name=config.region),
            args.queries or DEFAULT_QUERIES,
            args.results,
        )


if __name__ == "__main__":
    main()
