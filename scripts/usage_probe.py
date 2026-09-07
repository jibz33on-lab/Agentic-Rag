"""Find out where token and cost information survives, and where it is dropped.

The evaluation design reads `system` metrics — tokens, cost — back off the
LangSmith trace rather than returning them from the answerer. That only works if
the numbers actually make it that far. This probe finds out where they stop.

Three stages, each isolating one place the information could be lost:

    A. OpenRouter, raw HTTP        does the provider send usage and cost at all?
    B. through LangChain           does ChatOpenAI keep it, or drop it the way
                                   it silently drops `reasoning`?
    C. through to LangSmith        is it readable via read_run() after flush()?

Run it from the repo root:

    uv run python scripts/usage_probe.py

Stage C needs LANGSMITH_API_KEY and LANGSMITH_TRACING=true. It uses
load_dotenv() rather than dotenv_values() on purpose: the LangSmith SDK reads
os.environ, and dotenv_values() returns a dict without touching it. That
distinction has already cost this project one silent failure.
"""

import json
import os
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
BASE_URL = "https://openrouter.ai/api/v1"
PROMPT = "In one sentence, what is a vector database?"

MODEL = os.environ.get("ANSWERER_MODEL") or "deepseek/deepseek-v4-flash-0731"

# What we are trying to get back. `usage.include` is an OpenRouter feature, and
# goes through the same extra_body door as `reasoning` does in answerer.py.
USAGE_ON = {"include": True}
REASONING_OFF = {"enabled": False}

rule = "=" * 70


def heading(letter, question):
    print(f"\n{rule}\nSTAGE {letter}  —  {question}\n{rule}")


# ----------------------------------------------------------------- stage A ---
def stage_a():
    """Raw HTTP. Ground truth: whatever OpenRouter puts on the wire."""
    heading("A", "does OpenRouter send usage and cost on a streamed request?")

    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "usage": USAGE_ON,
        "reasoning": REASONING_OFF,
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        },
    )

    usage_payloads = []
    chunks = 0
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                payload = json.loads(line[len("data: ") :])
            except json.JSONDecodeError:
                continue
            chunks += 1
            if payload.get("usage"):
                usage_payloads.append(payload["usage"])

    print(f"  chunks received       {chunks}")
    print(f"  chunks carrying usage {len(usage_payloads)}")
    if usage_payloads:
        print("  the usage object, verbatim:")
        print(json.dumps(usage_payloads[-1], indent=4))
    else:
        print("  NO usage on the wire. Cost cannot reach the trace; stages B and C")
        print("  can only be about tokens.")
    return usage_payloads[-1] if usage_payloads else None


# ----------------------------------------------------------------- stage B ---
def stage_b():
    """Same request through ChatOpenAI. Does LangChain keep what A saw?"""
    heading("B", "does LangChain surface it, or drop it like `reasoning`?")

    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=BASE_URL,
        temperature=0,
        # Required. With an explicit base_url, langchain_openai leaves
        # stream_usage off by default (base.py:1332-1351), so the request never
        # asks for usage and nothing comes back.
        stream_usage=True,
        extra_body={"reasoning": REASONING_OFF, "usage": USAGE_ON},
    )

    usage_metadata = None
    response_metadata = {}
    chunks = 0
    for chunk in model.stream(PROMPT):
        chunks += 1
        if getattr(chunk, "usage_metadata", None):
            usage_metadata = chunk.usage_metadata
        if chunk.response_metadata:
            response_metadata.update(chunk.response_metadata)

    print(f"  chunks received   {chunks}")
    print(f"  usage_metadata    {usage_metadata!r}")
    print(f"  response_metadata {response_metadata!r}")

    if usage_metadata:
        details = usage_metadata.get("input_token_details") or {}
        print(
            f"\n  tokens survive.   in={usage_metadata.get('input_tokens')}"
            f" out={usage_metadata.get('output_tokens')} details={details}"
        )
    else:
        print("\n  tokens do NOT survive LangChain.")

    blob = json.dumps({"u": str(usage_metadata), "r": str(response_metadata)})
    print(f"  the word 'cost' appears in what LangChain gave us: {'cost' in blob}")
    return usage_metadata


# ----------------------------------------------------------------- stage C ---
def stage_c():
    """Through a traced call, then read it back the way trace_metrics will."""
    heading("C", "is it readable from the trace after flush()?")

    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        print("  LANGSMITH_TRACING is not 'true' — skipped.")
        return
    if not os.environ.get("LANGSMITH_API_KEY"):
        print("  LANGSMITH_API_KEY is not set — skipped.")
        return

    from langchain_openai import ChatOpenAI
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree

    model = ChatOpenAI(
        model=MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=BASE_URL,
        temperature=0,
        stream_usage=True,
        extra_body={"reasoning": REASONING_OFF, "usage": USAGE_ON},
    )

    captured = {}

    @traceable(name="usage_probe", run_type="chain")
    def one_call():
        # This is how rag_query will hand its run_id out.
        tree = get_current_run_tree()
        captured["run_id"] = str(tree.id) if tree else None
        started = time.monotonic()
        first_token_at = None
        answer = ""
        for piece in model.stream(PROMPT):
            if piece.content and first_token_at is None:
                first_token_at = time.monotonic() - started
            answer += piece.content
        captured["first_token_at"] = first_token_at
        captured["total"] = time.monotonic() - started
        return {"answer": answer}

    one_call()
    run_id = captured.get("run_id")
    print(f"  run_id from get_current_run_tree()  {run_id}")
    print(
        f"  measured locally: first token {captured['first_token_at']:.2f}s"
        f", total {captured['total']:.2f}s"
    )

    if not run_id:
        print("  no run_id — trace-based system metrics are impossible.")
        return

    client = Client()
    flush_started = time.monotonic()
    client.flush(timeout=30)
    print(f"  flush() took {time.monotonic() - flush_started:.2f}s")

    # The thing the design assumes: readable immediately after flush.
    for attempt in range(1, 4):
        try:
            run = client.read_run(run_id)
            print(f"  read_run() succeeded on attempt {attempt}")
            break
        except Exception as error:
            print(f"  read_run() attempt {attempt} failed: {type(error).__name__}: {error}")
            run = None
            time.sleep(2)

    if run is None:
        print("  the trace was not readable. trace_metrics.py needs a retry policy.")
        return

    for field in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cost",
        "completion_cost",
        "total_cost",
    ):
        print(f"    run.{field:<20} {getattr(run, field, None)!r}")

    duration = None
    if run.end_time and run.start_time:
        duration = (run.end_time - run.start_time).total_seconds()
    print(f"    run duration          {duration!r}s   (compare to local total above)")
    print("    first-token time is NOT a field on the run — only start and end.")


# ----------------------------------------------------------------- stage D ---
def stage_d():
    """Can we keep the cost, and get it into the trace reliably?

    Two things are under test, and they fail independently:

      1. a subclass that grabs `usage` off the raw chunk before
         _create_usage_metadata() whitelists the cost away
      2. carrying that cost into the trace via the traced return value,
         rather than trusting response_metadata to survive
    """
    heading("D", "can a subclass keep the cost, and get it into the trace?")

    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        print("  LANGSMITH_TRACING is not 'true' — skipped.")
        return

    from langchain_openai import ChatOpenAI
    from langsmith import Client, traceable
    from langsmith.run_helpers import get_current_run_tree

    class CostCapturingChatOpenAI(ChatOpenAI):
        """Keeps OpenRouter's `usage`, which LangChain drops on the floor.

        _convert_chunk_to_generation_chunk is the last place the raw provider
        dict exists. It hands `usage` to _create_usage_metadata, which reads
        seven named keys into a fixed TypedDict — `cost` is not one of them.
        """

        last_usage: dict | None = None

        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info
        ):
            usage = chunk.get("usage")
            if usage:
                self.last_usage = dict(usage)
            return super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )

    model = CostCapturingChatOpenAI(
        model=MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=BASE_URL,
        temperature=0,
        stream_usage=True,
        extra_body={"reasoning": REASONING_OFF, "usage": USAGE_ON},
    )

    captured = {}

    @traceable(name="usage_probe_d", run_type="chain")
    def one_call():
        tree = get_current_run_tree()
        captured["run_id"] = str(tree.id) if tree else None
        model.last_usage = None
        answer = "".join(piece.content for piece in model.stream(PROMPT))
        usage = model.last_usage or {}
        # Returned, not stashed. A @traceable's return value is serialised into
        # the trace, so this is the one route we control end to end.
        return {
            "answer": answer,
            "usage": {
                "cost": usage.get("cost"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        }

    result = one_call()

    print("  TEST 1 — did the subclass keep the cost?")
    print(f"    model.last_usage cost    {(model.last_usage or {}).get('cost')!r}")
    print(f"    returned usage           {result['usage']!r}")
    if result["usage"]["cost"] is None:
        print("    FAILED. The override did not capture a cost.")
        return

    run_id = captured.get("run_id")
    print(f"\n  TEST 2 — did it reach the trace?  run_id {run_id}")

    client = Client()
    client.flush(timeout=30)

    # Client().runs is AsyncRunsResource — the new API is async-only, and
    # calling it without awaiting returns a coroutine whose every attribute
    # reads as missing. The sync path is read_run(), deprecated after Jan 2027.
    # Whatever trace_metrics.py does, it must not silently poll a coroutine.
    started = time.monotonic()
    run = None
    attempts = 0
    while run is None and attempts < 30:
        attempts += 1
        candidate = client.read_run(run_id)
        if candidate.end_time is not None:
            run = candidate
            break
        time.sleep(1)
    waited = time.monotonic() - started

    if run is None:
        print(f"    never reported finished within {waited:.0f}s.")
        return

    outputs = run.outputs or {}
    trace_cost = (outputs.get("usage") or {}).get("cost")
    print(f"    finished after {waited:.1f}s of polling ({attempts} reads)")
    print(f"    run.outputs['usage']  {outputs.get('usage')!r}")
    print(f"    run.total_tokens      {run.total_tokens!r}")
    print(f"    run.total_cost        {run.total_cost!r}  (LangSmith's own pricing)")
    print(f"\n    exact OpenRouter cost in the trace: {trace_cost is not None} -> {trace_cost!r}")


if __name__ == "__main__":
    print(f"model  {MODEL}")
    for stage in (stage_a, stage_b, stage_c, stage_d):
        try:
            stage()
        except Exception as error:
            print(f"\n  STAGE FAILED: {type(error).__name__}: {error}")
    print(f"\n{rule}\nWrite the answers into projects/01-basic-rag/investigations/.")
