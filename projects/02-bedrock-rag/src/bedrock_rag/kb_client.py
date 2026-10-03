"""The calls this project makes against its `knowledge_base`.

Two AWS clients, deliberately not one. `ingestion_job` operations are control
plane and live on `bedrock-agent`; `Retrieve` is data plane and lives on
`bedrock-agent-runtime`. Both are passed in rather than built here, so tests
hand over a stand-in and nothing constructs a client as a side effect of import.

Nothing boto3-shaped leaves this module. Callers get `Chunk` and
`IngestionJobStatus`, so `main.py` never has to learn Bedrock's envelopes to
print a number.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bedrock_rag.config import Config

# A job in one of these is not going to move again. Polling only for COMPLETE
# would spin forever on a job that failed or was stopped.
_TERMINAL_STATUSES = frozenset({"COMPLETE", "FAILED", "STOPPED"})


@dataclass(frozen=True)
class Chunk:
    """One `chunk` as `Retrieve` returned it."""

    text: str
    # Empty when Bedrock omitted `location`, which the API permits. Attribution
    # is worth losing; the sample it came with is not.
    source: str


@dataclass(frozen=True)
class IngestionJobStatus:
    """What one `ingestion_job` has done so far."""

    status: str
    documents_scanned: int
    # New plus modified. On a first run everything is new, and on a re-run the
    # interesting number is documents_skipped -- see the open question about
    # what it counts in designs/ingestion_job.md.
    documents_indexed: int
    documents_failed: int
    documents_skipped: int
    documents_deleted: int
    failure_reasons: tuple[str, ...]

    @property
    def is_finished(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @property
    def has_failures(self) -> bool:
        """Whether this run is one to stop on.

        Both halves are load-bearing. Bedrock reports COMPLETE over documents it
        silently skipped, so the count catches a corpus that is quietly short;
        and a job that fails outright may never report a per-document count, so
        the status catches the total failure the count would miss.
        """
        return self.documents_failed > 0 or self.status == "FAILED"


def start_ingestion_job(config: Config, agent: Any) -> str:
    """Start a run and return its id, without waiting for it.

    `start` and `status` are separate from the outset: the CLI composes them
    into a blocking `ingest`, and the API in slice 7 will start a job and return
    its id with status as a second endpoint. One component, two callers.
    """
    response = agent.start_ingestion_job(
        knowledgeBaseId=config.knowledge_base_id,
        dataSourceId=config.data_source_id,
    )
    return response["ingestionJob"]["ingestionJobId"]


def ingestion_job_status(job_id: str, config: Config, agent: Any) -> IngestionJobStatus:
    """Report where a run has got to, and what it has done."""
    job = agent.get_ingestion_job(
        knowledgeBaseId=config.knowledge_base_id,
        dataSourceId=config.data_source_id,
        ingestionJobId=job_id,
    )["ingestionJob"]

    # Every statistic is optional in the API, and so is the statistics object.
    # A job polled the moment it starts carries none of them.
    statistics: Mapping[str, int] = job.get("statistics", {})

    return IngestionJobStatus(
        status=job["status"],
        documents_scanned=statistics.get("numberOfDocumentsScanned", 0),
        documents_indexed=(
            statistics.get("numberOfNewDocumentsIndexed", 0)
            + statistics.get("numberOfModifiedDocumentsIndexed", 0)
        ),
        documents_failed=statistics.get("numberOfDocumentsFailed", 0),
        documents_skipped=statistics.get("numberOfDocumentsSkipped", 0),
        documents_deleted=statistics.get("numberOfDocumentsDeleted", 0),
        failure_reasons=tuple(job.get("failureReasons", ())),
    )


def retrieve(
    query: str,
    config: Config,
    runtime: Any,
    number_of_results: int | None = None,
) -> list[Chunk]:
    """Return the `chunk`s Bedrock ranks highest for `query`.

    `number_of_results` is a parameter because slice 1's verification samples
    wider than slice 2 retrieves. It defaults to `TOP_K` so the path that feeds
    the `answerer` still has exactly one source for that number, and cannot
    drift from what the benchmark was measured at.

    An empty list is an ordinary answer, not an error: a `Retrieve` issued
    before an `ingestion_job` finishes returns nothing. Callers must keep "not
    finished" apart from "nothing found" -- this function cannot tell them apart.
    """
    response = runtime.retrieve(
        knowledgeBaseId=config.knowledge_base_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": config.top_k if number_of_results is None else number_of_results
            }
        },
    )

    return [
        Chunk(
            text=result["content"].get("text", ""),
            source=result.get("location", {}).get("s3Location", {}).get("uri", ""),
        )
        for result in response["retrievalResults"]
    ]
