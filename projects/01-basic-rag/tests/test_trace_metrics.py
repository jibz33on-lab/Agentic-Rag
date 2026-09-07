from datetime import datetime, timedelta

import pytest
from evaluation.trace_metrics import read_system_metrics

STARTED = datetime(2026, 9, 7, 9, 38, 30)


class FakeRun:
    def __init__(self, *, finished, tokens=(14, 46, 60), cost=9.18e-06, seconds=4.8):
        self.start_time = STARTED
        self.end_time = STARTED + timedelta(seconds=seconds) if finished else None
        self.prompt_tokens, self.completion_tokens, self.total_tokens = tokens
        self.extra = {"metadata": {"openrouter_cost": cost} if cost is not None else {}}


class FakeClient:
    """Hands back a scripted sequence of runs, one per read, then repeats."""

    def __init__(self, *runs):
        self.runs = list(runs)
        self.reads = 0

    def read_run(self, run_id):
        self.reads += 1
        return self.runs[min(self.reads - 1, len(self.runs) - 1)]


class AsyncOnlyClient:
    """Stands in for langsmith's newer API, which is async-only.

    Client().runs is an AsyncRunsResource, so calling it from sync code hands
    back a coroutine rather than a run. Reading `end_time` off that reports
    missing rather than raising, which turns a working trace into a silently
    absent one.
    """

    def read_run(self, run_id):
        async def never_awaited():
            return None

        return never_awaited()


def test_raises_when_the_client_hands_back_a_coroutine():
    with pytest.raises(TypeError, match="coroutine"):
        read_system_metrics(AsyncOnlyClient(), "some-run-id")


def test_returns_the_tokens_latency_and_cost_of_a_finished_run():
    client = FakeClient(FakeRun(finished=True))

    metrics = read_system_metrics(client, "run-id", sleep=lambda _: None)

    assert metrics.ready is True
    assert metrics.prompt_tokens == 14
    assert metrics.completion_tokens == 46
    assert metrics.total_tokens == 60
    assert metrics.latency_s == 4.8
    assert metrics.cost == 9.18e-06


def test_polls_until_the_run_reports_finished():
    """flush() returns before the run is queryable — measured at about five
    seconds. Reading once gets zeros that are indistinguishable from a real
    zero, so the wait is on end_time rather than on a fixed pause."""
    client = FakeClient(FakeRun(finished=False), FakeRun(finished=False), FakeRun(finished=True))

    metrics = read_system_metrics(client, "run-id", sleep=lambda _: None)

    assert metrics.ready is True
    assert client.reads == 3


def test_gives_up_after_the_cap_and_reports_the_trace_missing():
    """An evaluation_run must not stall on one trace. The example still scores
    for retrieval and generation; only its system metrics are absent."""
    client = FakeClient(FakeRun(finished=False))

    metrics = read_system_metrics(client, "run-id", attempts=4, sleep=lambda _: None)

    assert metrics.ready is False
    assert metrics.total_tokens is None
    assert client.reads == 4


def test_reports_a_finished_run_with_no_tokens_as_a_real_zero():
    """Zero tokens on a finished run is data. Zero on an unfinished one is
    absence. Conflating them makes a fast run look like a broken one."""
    client = FakeClient(FakeRun(finished=True, tokens=(0, 0, 0), cost=None))

    metrics = read_system_metrics(client, "run-id", sleep=lambda _: None)

    assert metrics.ready is True
    assert metrics.total_tokens == 0
    assert metrics.cost is None
