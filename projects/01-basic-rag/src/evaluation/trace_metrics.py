"""Reads what one rag_query cost, from the trace it left behind.

LangSmith is the source of truth for system metrics. The runner does not keep
its own tally: one number calculated in two places is one number that will
eventually disagree with itself.

Cost is the exception that proves it. LangSmith prices runs from its own model
table, which does not cover the models we reach through OpenRouter, so its cost
fields are always None here. Instead the answerer captures OpenRouter's exact
figure and rag_query.record_cost writes it into the run's metadata — so it is
still read back from the trace, like everything else.
"""

import inspect
import time
from dataclasses import dataclass

DEFAULT_ATTEMPTS = 30
DEFAULT_PAUSE_SECONDS = 1.0


@dataclass(frozen=True)
class SystemMetrics:
    """What one rag_query cost to run.

    `ready` is False when the trace never reported finished. Every other field
    is then None, and the caller counts it as a missing trace rather than a
    system with no latency and no tokens.
    """

    ready: bool
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None


def read_system_metrics(
    client,
    run_id: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    pause: float = DEFAULT_PAUSE_SECONDS,
    sleep=time.sleep,
) -> SystemMetrics:
    """Poll until the run has finished, then read its numbers off the trace.

    Polling, not a single read, because `flush()` does not make a run readable.
    Measured: it returns in 0.00s while the run still has no end_time and zero
    tokens, and completes about five seconds later. A single read would report
    zeros — and zeros are indistinguishable from a genuinely cheap run.

    So the wait is on `end_time`, which is the only thing that separates "not
    ready" from "no data". After `attempts` reads the run is treated as missing
    and the example keeps its retrieval and generation scores.
    """
    for attempt in range(attempts):
        run = _require_sync_run(client, run_id)
        if run.end_time is not None:
            return _metrics_from(run)
        if attempt < attempts - 1:
            sleep(pause)
    return SystemMetrics(ready=False)


def _require_sync_run(client, run_id: str):
    """Fetch a run, refusing a coroutine loudly.

    langsmith's newer runs API is async-only — Client().runs is an
    AsyncRunsResource — and an un-awaited coroutine answers every attribute
    lookup with "missing" instead of raising. A polling loop reading `end_time`
    off one concludes the run never finished, for a run that finished seconds
    ago. The metric disappears and nothing fails, which is the worst shape a
    bug can take here.
    """
    run = client.read_run(run_id)
    if inspect.iscoroutine(run):
        run.close()  # or Python warns about it never being awaited
        raise TypeError(
            f"{type(client).__name__}.read_run returned a coroutine. The async "
            "LangSmith API cannot be used from here — its attributes read as "
            "missing rather than raising, so a trace would look absent."
        )
    return run


def _metrics_from(run) -> SystemMetrics:
    """Read a finished run. Zeros here are real zeros, not absence."""
    metadata = (getattr(run, "extra", None) or {}).get("metadata") or {}
    latency = None
    if run.end_time is not None and run.start_time is not None:
        latency = (run.end_time - run.start_time).total_seconds()
    return SystemMetrics(
        ready=True,
        latency_s=latency,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        total_tokens=run.total_tokens,
        # Ours, not LangSmith's — see the module docstring.
        cost=metadata.get("openrouter_cost"),
    )
