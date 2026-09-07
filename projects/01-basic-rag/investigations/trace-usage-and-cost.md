# Investigation: what usage information reaches the trace

Conducted 2026-09-07, before implementing evaluation. Everything below was
measured with `scripts/usage_probe.py`. Where something is inferred rather than
observed, it says so.

## 1. Executive summary

The evaluation design reads `system` metrics off the LangSmith `trace` rather
than returning them from the `answerer`, so that `stream_answer`'s interface
stays still. This probe asked whether the numbers actually get that far.

**Tokens do. Cost does not — but it can be recovered exactly, and the recovery
was measured working end to end.**

- OpenRouter sends both. `usage: {"include": true}` produces a `usage` object
  carrying `prompt_tokens`, `completion_tokens` **and** `cost`, plus a
  `cost_details` breakdown.
- LangChain keeps the tokens and **silently drops the cost** — the same failure
  mode as `reasoning` in the latency investigation. The word "cost" does not
  appear anywhere in what `ChatOpenAI` hands back.
- LangSmith therefore has no cost either, and cannot compute its own, because it
  does not price `deepseek/deepseek-v4-flash-0731`. `total_cost`, `prompt_cost`
  and `completion_cost` are all `None`.
- OpenRouter's generation id, which would allow fetching the true cost from
  their API afterwards, is **not** surfaced by LangChain and is not in the
  trace. The stored message id is LangChain's own `lc_run--…`.

**The recovery works.** A ten-line subclass overriding
`_convert_chunk_to_generation_chunk` keeps the raw `usage` dict before LangChain
normalises it away; the traced function returns the cost in its own result, and
it is readable from the trace. Measured: `cost: 9.18e-06` in
`run.outputs["usage"]["cost"]`. See §7.

A second finding, unrelated to cost and more likely to bite: **`flush()` does not
make a run readable.** It returned in 0.00s, and the run read immediately after
had `end_time = None` and `total_tokens = 0`. Polling with `read_run()` showed
the run completes **about 5 seconds later** — ready on the second read.

## 2. Method

Three stages, each isolating one place the information could be lost.

| stage | what it does | isolates |
|---|---|---|
| A | raw HTTP to OpenRouter, streamed | what the provider puts on the wire |
| B | the same request through `ChatOpenAI` | what LangChain keeps |
| C | a `@traceable` call, then `flush()` and read back | what LangSmith stores |

Model: `deepseek/deepseek-v4-flash-0731`. Reasoning off, temperature 0, one
short fixed prompt.

## 3. Stage A — OpenRouter sends everything

One chunk of 52 carried a `usage` object:

```json
{
    "prompt_tokens": 14,
    "completion_tokens": 50,
    "total_tokens": 64,
    "cost": 8.7e-06,
    "cost_details": {
        "upstream_inference_cost": 8.7e-06,
        "upstream_inference_prompt_cost": 7e-07,
        "upstream_inference_completions_cost": 8e-06
    },
    "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
    "completion_tokens_details": {"reasoning_tokens": 0}
}
```

Two things worth noting beyond the headline. `cached_tokens` is there, which
matters if prompt caching is ever used — the same 4 KB of excerpts go out on
every query. And `reasoning_tokens` is there, which is the number the latency
investigation had to infer by reading the raw stream.

## 4. Stage B — LangChain keeps the tokens and drops the cost

```
usage_metadata    {'input_tokens': 14, 'output_tokens': 48, 'total_tokens': 62,
                   'input_token_details': {'audio': 0, 'cache_read': 0, 'cache_creation': 0},
                   'output_token_details': {'audio': 0, 'reasoning': 0}}
response_metadata {'model_provider': 'openai', 'finish_reason': 'stop',
                   'model_name': 'deepseek/deepseek-v4-flash-0731'}

the word 'cost' appears in what LangChain gave us: False
```

`usage_metadata` is LangChain's normalised shape. It has slots for token details
it understands — audio, cache, reasoning — and no slot for a provider-specific
cost field, so the field is discarded rather than passed through.

`stream_usage=True` is **required** to get even this far. With an explicit
`base_url`, `langchain_openai` leaves it off by default
(`chat_models/base.py:1332-1351`), on the reasoning that many non-OpenAI
endpoints do not support streaming usage. OpenRouter does.

Note the token counts differ from stage A (48 vs 50 completion tokens). These
are separate requests, and the model does not produce an identical answer twice
despite `temperature=0`. That is worth remembering when reading any single-run
number from this pipeline.

## 5. Stage C — the trace has tokens, eventually, and never cost

Read immediately after `flush()`:

```
flush() took 0.00s
read_run() succeeded on attempt 1
  run.prompt_tokens     0
  run.completion_tokens 0
  run.total_tokens      0
  run.total_cost        None
  run duration          None      <- end_time was not set yet
```

The same run, re-read about a minute later:

```
PARENT (the @traceable chain run)
  end_time          2026-09-07 08:53:37.243725+00:00
  total_tokens      60
  total_cost        None

CHILDREN
  - ChatOpenAI  type=llm
      tokens        p=14 c=46 t=60
      cost          total=None prompt=None
```

So the run **is** readable straight away — it just is not yet *finished* from the
server's point of view. `flush()` returning in 0.00s did not mean the data had
landed; it meant the local queue was empty. Reading a run and getting zeros is
indistinguishable, at the call site, from a run that genuinely used no tokens.

Token totals aggregate onto the parent chain run as well as the child `llm` run,
so `trace_metrics.py` can read the parent and does not need to walk children.

`llm_output`, `generation_info` and the stored `response_metadata` are all empty,
and the message id is `lc_run--01a07b12-…` — LangChain's, not OpenRouter's. There
is no id with which to ask OpenRouter what a request actually cost.

## 6. Consequences for the design

| # | assumption from `evaluation-logic.md` | verdict |
|---|---|---|
| 4 | OpenRouter cost reaches the `trace` unaided | **false** — dropped by LangChain. Recoverable, see §7 |
| 3 | `read_run` returns usage shortly after `flush` | **false.** Returns zeros; ready ~5s later. Poll on `end_time` |
| 6 | first-token time is recoverable from the `trace` | **unresolved** — see below |
| — | tokens reach the `trace` at all | **true**, on both parent and child |

**What `trace_metrics.py` must do:**

- Poll rather than trust `flush()`. Read until `end_time` is set — measured at
  about 5 seconds, ready on the second read. Treat a run still unfinished at the
  cap as a missing trace and increment `traces_missing`.
- Read the parent run. Children add a round trip for the same numbers.
- Distinguish `total_tokens == 0` **with** `end_time` set (a real zero) from the
  same without it (not ready). Otherwise a fast run and an unfinished one look
  identical.

**The sync/async trap.** `read_run()` and `list_runs()` are deprecated (removed
after 31 January 2027), but their replacements are **async-only**:
`Client().runs` is an `AsyncRunsResource`. Calling `client.runs.retrieve(...)`
from sync code returns a **coroutine**, and every attribute read off it — 
`end_time`, `total_tokens` — silently reports as missing rather than raising.
That cost this investigation a false negative: a polling loop reported "never
finished" for a run that had finished, because it was inspecting a coroutine.

So the choice for `trace_metrics.py` is the deprecated sync call, or going async.
Whichever, **it must fail loudly if handed a coroutine**, because the failure
mode is a metric that quietly reads as absent.

**First-token time** is not on the object `read_run()` returns, but
`FIRST_TOKEN_TIME` and `LATENCY_SECONDS` *are* valid `selects` values on the new
async API. Whether they are populated for a streamed run is untested. The claim
"first-token time is not available" would be wrong; "not available on the sync
API we are currently using" is accurate.

## 7. Stage D — recovering the cost

`_create_usage_metadata` (`base.py:4339`) is a whitelist. It reads seven named
keys — `prompt_tokens`, `completion_tokens`, `total_tokens`, and the audio, cache
and reasoning sub-counts — into a fixed `UsageMetadata` TypedDict. `cost` is not
one of them, so there is no flag to set and nothing to configure. The only fix is
to read the raw dict before that function runs.

`_convert_chunk_to_generation_chunk` (`base.py:1510`) is the last place it
exists. A subclass overriding it keeps the dict:

```python
class CostCapturingChatOpenAI(ChatOpenAI):
    last_usage: dict | None = None

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        usage = chunk.get("usage")
        if usage:
            self.last_usage = dict(usage)
        return super()._convert_chunk_to_generation_chunk(...)
```

Getting it into the trace was tested separately, because attaching to
`response_metadata` and hoping was the obvious approach and the stored
`response_metadata` had come back empty in stage C. Instead the traced function
**returns** the cost, and a `@traceable`'s return value is serialised into the
trace by construction:

```
run.outputs = {
  "answer": "A vector database is a specialized database that ...",
  "usage": {"completion_tokens": 53, "cost": 9.18e-06, "prompt_tokens": 14}
}
```

Measured over three runs: `2.25e-05`, `1.33e-05`, `9.18e-06`. `run.total_cost`
stayed `None` throughout — that is LangSmith's own pricing, which does not cover
this model. Ours is in `outputs`.

**Why this is worth the fragility.** OpenRouter routes this model across ~30
providers charging different prices, so the cost of a request depends on which
one served it. A price table cannot know that. OpenRouter's figure is not an
estimate of the cost — it is the cost.

**The fragility is real.** `_convert_chunk_to_generation_chunk` is private. An
upgrade can change its signature or stop calling it, and the failure is silent:
cost becomes `None` and the column quietly empties. This needs a test that fails
when cost stops surviving, so a LangChain upgrade breaks the build rather than
the data.

## 8. Open

- Whether `FIRST_TOKEN_TIME` is populated for streamed runs on the async API.
- Prompt caching is visible in stage A's `cached_tokens` and currently unused.
  Every query resends the same excerpt-shaped prompt. Worth its own look later.
