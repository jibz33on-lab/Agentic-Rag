import pytest
from bedrock_rag.config import load_config
from bedrock_rag.kb_client import ingestion_job_status, retrieve, start_ingestion_job

PARAMETERS = {"knowledge_base_id": "XEIGF4KXHU", "data_source_id": "JTJON9FPWG"}


def a_config(**env: str):
    return load_config(env=env, parameters=PARAMETERS)


class FakeAgent:
    """Stands in for a boto3 `bedrock-agent` client, recording what it was asked."""

    def __init__(self, job: dict | None = None):
        self.job = job or {"ingestionJobId": "JOB1234567", "status": "STARTING"}
        self.calls: list[tuple[str, dict]] = []

    def start_ingestion_job(self, **kwargs):
        self.calls.append(("start_ingestion_job", kwargs))
        return {"ingestionJob": self.job}

    def get_ingestion_job(self, **kwargs):
        self.calls.append(("get_ingestion_job", kwargs))
        return {"ingestionJob": self.job}


class FakeRuntime:
    """Stands in for a boto3 `bedrock-agent-runtime` client."""

    def __init__(self, results: list[dict] | None = None):
        self.results = results if results is not None else []
        self.calls: list[dict] = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return {"retrievalResults": self.results}


def a_result(text: str = "a chunk", uri: str = "s3://bucket/doc.pdf") -> dict:
    return {"content": {"text": text, "type": "TEXT"}, "location": {"s3Location": {"uri": uri}}}


# --- start_ingestion_job ----------------------------------------------------


def test_returns_the_id_of_the_ingestion_job_it_started():
    """main.py has to hold the id to poll status, and the CLI composes the two
    into a blocking `ingest`. Returning the whole response instead would make
    every caller learn Bedrock's envelope."""
    agent = FakeAgent()

    assert start_ingestion_job(a_config(), agent) == "JOB1234567"


def test_starts_the_job_against_the_configured_knowledge_base_and_data_source():
    """Both ids are required and they are easy to transpose, which would start a
    job against a knowledge_base that is not the one under test."""
    agent = FakeAgent()

    start_ingestion_job(a_config(), agent)

    assert agent.calls == [
        ("start_ingestion_job", {"knowledgeBaseId": "XEIGF4KXHU", "dataSourceId": "JTJON9FPWG"})
    ]


# --- ingestion_job_status ---------------------------------------------------


def test_reports_the_statistics_of_a_finished_job():
    """These are the numbers slice 1 exists to record. numberOfNewDocumentsIndexed
    and numberOfModifiedDocumentsIndexed are summed: on a first run everything is
    new, and on a re-run the interesting number is skipped, not the split."""
    agent = FakeAgent(
        {
            "ingestionJobId": "JOB1234567",
            "status": "COMPLETE",
            "statistics": {
                "numberOfDocumentsScanned": 4,
                "numberOfNewDocumentsIndexed": 3,
                "numberOfModifiedDocumentsIndexed": 1,
                "numberOfDocumentsFailed": 0,
                "numberOfDocumentsSkipped": 0,
                "numberOfDocumentsDeleted": 0,
            },
        }
    )

    status = ingestion_job_status("JOB1234567", a_config(), agent)

    assert status.status == "COMPLETE"
    assert status.documents_scanned == 4
    assert status.documents_indexed == 4
    assert status.documents_failed == 0
    assert status.documents_skipped == 0
    assert status.documents_deleted == 0


def test_treats_absent_statistics_as_zero():
    """Every field of IngestionJobStatistics is optional in the API, and so is
    the statistics object itself. A job polled the moment it starts has none of
    them, and a KeyError there would break `ingest` before the run it is meant
    to be reporting on had a chance to fail honestly."""
    agent = FakeAgent({"ingestionJobId": "JOB1234567", "status": "STARTING"})

    status = ingestion_job_status("JOB1234567", a_config(), agent)

    assert status.documents_scanned == 0
    assert status.documents_indexed == 0
    assert status.documents_failed == 0
    assert status.failure_reasons == ()


def test_asks_about_the_job_it_was_given():
    agent = FakeAgent()

    ingestion_job_status("JOB1234567", a_config(), agent)

    assert agent.calls == [
        (
            "get_ingestion_job",
            {
                "knowledgeBaseId": "XEIGF4KXHU",
                "dataSourceId": "JTJON9FPWG",
                "ingestionJobId": "JOB1234567",
            },
        )
    ]


@pytest.mark.parametrize("status", ["STARTING", "IN_PROGRESS", "STOPPING"])
def test_is_not_finished_while_the_job_is_still_running(status):
    """STOPPING counts as running: the job is still moving, and `ingest` polling
    must not read its half-written statistics as a final result."""
    agent = FakeAgent({"ingestionJobId": "JOB1234567", "status": status})

    assert not ingestion_job_status("JOB1234567", a_config(), agent).is_finished


@pytest.mark.parametrize("status", ["COMPLETE", "FAILED", "STOPPED"])
def test_is_finished_once_the_job_reaches_a_terminal_status(status):
    """FAILED and STOPPED are finished too. Polling only for COMPLETE would spin
    forever on a job that is never going to reach it."""
    agent = FakeAgent({"ingestionJobId": "JOB1234567", "status": status})

    assert ingestion_job_status("JOB1234567", a_config(), agent).is_finished


def test_has_failures_when_a_document_failed_even_though_the_job_completed():
    """The trap slice 1 is built around: Bedrock reports COMPLETE over a corpus
    it could not fully read, and an un-ingested file then looks exactly like a
    retrieval-quality problem. This is what makes `ingest` exit non-zero."""
    agent = FakeAgent(
        {
            "ingestionJobId": "JOB1234567",
            "status": "COMPLETE",
            "statistics": {"numberOfDocumentsScanned": 4, "numberOfDocumentsFailed": 1},
            "failureReasons": ["could not parse hybrid-search-fundamentals.pdf"],
        }
    )

    status = ingestion_job_status("JOB1234567", a_config(), agent)

    assert status.has_failures
    assert status.failure_reasons == ("could not parse hybrid-search-fundamentals.pdf",)


def test_has_failures_when_the_job_itself_failed():
    """A job that fails outright may never report a per-document count, so
    counting documents alone would call a total failure a success."""
    agent = FakeAgent({"ingestionJobId": "JOB1234567", "status": "FAILED"})

    assert ingestion_job_status("JOB1234567", a_config(), agent).has_failures


def test_has_no_failures_on_a_clean_run():
    agent = FakeAgent(
        {
            "ingestionJobId": "JOB1234567",
            "status": "COMPLETE",
            "statistics": {"numberOfDocumentsScanned": 4, "numberOfDocumentsFailed": 0},
        }
    )

    assert not ingestion_job_status("JOB1234567", a_config(), agent).has_failures


# --- retrieve ---------------------------------------------------------------


def test_returns_a_chunk_for_each_result():
    runtime = FakeRuntime([a_result("the first chunk", "s3://bucket/system-design.pdf")])

    chunks = retrieve("what is a quorum", a_config(), runtime)

    assert len(chunks) == 1
    assert chunks[0].text == "the first chunk"
    assert chunks[0].source == "s3://bucket/system-design.pdf"


def test_returns_empty_when_nothing_matches():
    """A Retrieve issued before an ingestion_job finishes returns empty rather
    than failing. Whatever reports results has to keep "not finished" apart from
    "nothing found", so this must be an ordinary empty list and not an error."""
    runtime = FakeRuntime([])

    assert retrieve("what is a quorum", a_config(), runtime) == []


def test_asks_for_top_k_results_by_default():
    """TOP_K has one source, so slice 2's retrieval cannot drift from what the
    benchmark was measured at by passing its own number."""
    runtime = FakeRuntime()

    retrieve("what is a quorum", a_config(), runtime)

    assert runtime.calls == [
        {
            "knowledgeBaseId": "XEIGF4KXHU",
            "retrievalQuery": {"text": "what is a quorum"},
            "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 8}},
        }
    ]


def test_asks_for_as_many_results_as_it_is_given():
    """Slice 1's verification samples wider than slice 2 retrieves, which is why
    numberOfResults is a parameter rather than read from config every time."""
    runtime = FakeRuntime()

    retrieve("what is a quorum", a_config(), runtime, number_of_results=25)

    configuration = runtime.calls[0]["retrievalConfiguration"]
    assert configuration["vectorSearchConfiguration"]["numberOfResults"] == 25


def test_leaves_the_source_empty_when_a_result_has_no_location():
    """`location` is optional in the API. The verification command reports which
    documents chunks came from, and losing the whole sample to a KeyError over a
    missing attribution would be a poor trade."""
    runtime = FakeRuntime([{"content": {"text": "a chunk", "type": "TEXT"}}])

    chunks = retrieve("what is a quorum", a_config(), runtime)

    assert chunks[0].text == "a chunk"
    assert chunks[0].source == ""
