# Design: the HTTP API

Designed 2026-09-14, in a `grill-me` session.

## Problem

`rag_query` is a Python function. To call it you must already be a Python
process holding a `Config`, an `Embeddings` client, a `BaseChatModel` and a
`reranker` — objects in memory. Today two callers satisfy that: `main.py ask`
and an `evaluation_run`.

A browser cannot. Nothing written outside Python can reach a Python function,
and the expensive clients cannot be rebuilt per caller anyway.

An HTTP API changes the requirement from *be this process* to *send this process
a message*. That is the whole of what this step adds. It is the first piece of
deployment work: an `ALB` needs something to route to, a container needs a
long-running process, and a `rag_query` invoked from a terminal is neither.

## Scope

**In.** One route, `POST /query`, and the tests that prove it.

**Out**, deliberately.

- **`/health` and `/ready`.** They exist to answer an orchestrator, and there is
  no orchestrator yet. They arrive with the deployment step that needs them.
- **`/ingest`.** Long-running mutation does not belong in a request path — an
  `ALB`'s default idle timeout is 60s and ingest would hold a worker for the
  whole run. Batch work gets its own task later.
- **Streaming.** Recorded below as a decision, not an omission.
- **Auth, CORS, rate limiting.** Nothing is exposed to a network yet. They land
  with the first deploy, not before.
- **Any change to `retrieval.py`, `answerer.py`, `rag_query.py` or `config.py`.**

## Design

### The caller is a web UI, so a person is waiting

Not a script and not a third party. That settles two things: the contract can
change later, because we own both ends — and latency is visible to a human,
because someone is watching a screen.

### One whole answer, not a stream

Recorded latency is **P50 5.10s**, so this costs a person five seconds of blank
screen. Accepted, because the response stays a single JSON object: a request
either succeeds or fails, never half of each.

Streaming requires committing `200 OK` *before* the answer is known to finish,
which makes a mid-stream failure unrepresentable in the status code. That is a
second design problem and it gets its own route later.

It is not deferred for cost of change. `rag_query` already takes `on_piece` and
`answerer.py` already streams — `main.py ask` uses it. Streaming later is a new
route, not a rewrite.

### The request carries only the question

```json
{ "question": "..." }
```

No `top_k`, no model name, no filters. **Configuration is an implementation
decision, not user intent.**

`TOP_K=4` was chosen by measurement — `correct` peaks there, and `TOP_K=20`
costs 104,635 prompt tokens against 22,592. A client that can set `top_k` can
multiply the bill from a browser console, and the benchmark stops describing
what is actually running.

### The response carries the answer, its evidence, and an id

```json
{ "answer": "...", "chunks": [ { "text": "...", "source": "...", "page": 1 } ],
  "request_id": "..." }
```

`chunks` because an answer without its evidence cannot be checked. The judge
scores `grounded` by asking whether the answer is supported by the excerpts;
a UI that cannot show them asks the person to trust the model instead. The costs
are named and accepted: roughly 3 KB per response, and chunk text reaching the
browser — which would need authorisation in a multi-user system over material
that is not ours.

`request_id` is **ours**, generated here, not the LangSmith `run_id`. Returning
`run_id` would put an internal identifier and our observability vendor into a
browser. The opaque id is what a person quotes when reporting a bad answer, and
what maps to the trace in our logs.

It maps to nothing yet — structured logging does not exist. Generated now
anyway, because adding a response field is cheap in code and expensive in
coordination: by the time logging lands, the frontend exists too, and a UI with
nowhere to show the id means revisiting both sides.

### Everything expensive is built once, at startup

`config`, `embeddings`, `model` and `reranker` are constructed when the process
starts and reused by every request.

The argument is failure, not speed. `build_reranker` raises when
`RERANKER_MODEL` is set but unloadable. Built per request, that is a 500 on
every call from a server that looks healthy. Built at startup, the process never
comes up — and a bad deploy refuses to go live rather than replacing a working
one. **Fail fast, where it is cheap.**

### Stateless

Holding those four is not state. They are derived from the environment,
identical on every instance, and rebuildable at any moment. The test is whether
anything would be lost if this process died and a fresh one took over. For
`embeddings`, no. For a dict of each user's last question, yes — and that is
what makes something stateful. Shared state, when it is needed, belongs in an
external store.

### What the status code means

A status code is a machine-readable instruction about what to do next. Clients
retry 5xx and not 4xx; monitoring alerts on 5xx and not 4xx.

| Case | Code |
|---|---|
| `question` missing, or present and empty | 4xx |
| Qdrant unreachable | 5xx |
| OpenRouter rate-limits us | 503, with `Retry-After` |
| `NoAnswerError` — the model wrote nothing | 5xx |
| The model declines *in words* | **200** |

The last two rows are one distinction and it is easy to get backwards. **A
decline is an answer; an empty string is the absence of one.** `guardrails.py`
says so outright — "this is not the model saying it does not know" — and lists
its causes as a rate limit, a provider error, or the model stopping. Those are
malfunctions. Score them 200 and real provider failures land in the metrics as
successful queries while users watch a blank screen.

## Interfaces

| Module | Change |
|---|---|
| new — `api.py`, beside `main.py` | translates HTTP into calls on the pipeline |
| new — `asgi.py`, beside `main.py` | builds the real pipeline and hands it to the app |
| `pyproject.toml` | `fastapi`, `uvicorn[standard]` |
| everything in `src/` | **unchanged** |

`api.py` sits beside `main.py` because they are the same kind of thing. `main.py`
translates terminal commands into pipeline calls; `api.py` translates HTTP
requests. Neither is pipeline code, and `src/` is where the pipeline lives.

**`asgi.py` is separate from `api.py` because everything in it happens at import
time.** Reading `.env` and constructing the embedding client, the chat model and
the reranker are side effects, and `api.py` must stay importable without them —
every test imports it, and none should need a key or a running Qdrant. So
`api.py` holds the shape of the service and `asgi.py` holds one way of filling it
in: `create_app(build_answer_question(config, embeddings, model, reranker))`.

`asgi.py` carries the same `sys.path.insert(..., "src")` line `main.py` does.
uvicorn's `--app-dir` reaches the file but not the package beside it, `conftest.py`
supplies it only for tests, and without the line the server dies at import on
`No module named 'answerer'` while every test still passes. The environment
differed, not the code — which is the plainest argument for containerising this
that the project has produced so far.

`rag_query`'s signature does not change. Its only optional parameter, `on_piece`,
exists so a caller can print a streaming answer without the printing happening
inside — the terminal passes one, the API passes nothing. **The pipeline never
learns that HTTP exists**, which is also why an `evaluation_run` still measures
the system we ship rather than a lookalike.

## Failure

`NoAnswerError` is raised in `answerer.py:126`, inside the pipeline, and caught
by `main.py:327` for the terminal. The API catches it too. The pipeline decides
what counts as a failure; each caller decides how to present one.

As built, every response carries one shape:

| Case | Status | `code` |
|---|---|---|
| `question` missing | 422 | `invalid_request` |
| `question` empty or whitespace | 400 | `bad_request` |
| unknown path | 404 | `not_found` |
| `NoAnswerError` | 502 | `no_answer` |
| anything else | 500 | `internal_error` |

**502 for an empty answer, not 500.** Nothing in our code broke; something we
depend on returned nothing.

**500 says nothing else.** An exception message is written for whoever reads the
logs — a dead Qdrant names a host and a port, a database error can carry a
query. The client gets a fixed sentence and the `request_id`; Starlette
re-raises after the handler, so the traceback still reaches the server log.

**The handler is registered on Starlette's `HTTPException`, not FastAPI's
subclass.** FastAPI's inherits from it, so one registration catches ours *and*
the ones Starlette raises itself — the 404 for an unknown path included.
Registered on the subclass, that 404 answers in the default shape, which is the
inconsistency the handler exists to remove.

**`request_id` is assigned by middleware, not in the route.** A validation
failure is answered before the route is called at all, so an id generated there
would be missing from exactly the responses that most need one. Middleware runs
first; the route and every handler read the same value.

## Done

Fake `embeddings` and a fake `model` — no Qdrant, no OpenRouter, no cost, runs
in CI. Three behaviours:

1. `POST {"question": "..."}` returns 200 and the documented shape.
2. The fake model's known string appears in `answer`. Shape proves the contract;
   the known string proves the route actually called the pipeline.
3. `POST {}` returns 422, and `POST {"question": ""}` returns 4xx.

Those are two different causes. A missing field is Pydantic's to reject for
free. An empty string is a valid `str` and reaches the pipeline unless
`question` carries an explicit minimum length.

A real end-to-end test comes later, following the `services` and
`live_openrouter_config` fixtures, which skip rather than fail when nothing is
running.

Swagger and Hoppscotch are manual verification, not tests. They tell you it
works; only pytest tells CI.

## Open questions

- **`request_id` is not in `DOMAIN_TERMS.md`.** It is a new word for a new
  thing, and the vocabulary has no entry for it. Propose before writing it in.
- ~~**`def` or `async def` for the route.**~~ Settled `def`. `rag_query` is
  synchronous, and FastAPI runs a plain `def` route in a thread pool. An
  `async def` route calling it would block the event loop for the whole of every
  question — one slow user, everybody waits.
- ~~**`page` is 0-indexed and the contract does not say so.**~~ Fixed.
  `as_evidence` adds one, so the contract promises the page a person would turn
  to rather than `PyPDFLoader`'s index. Found in a live response, which returned
  `"page": 20` for a chunk whose own text reads `Page 21`. Fixed here rather than
  in the client because a 0-based index is the loader's detail, and every future
  client would otherwise have to know — and be silently wrong until it did.
  `None` survives untouched for a source with no pages.
- **`source` carries the ingest path.** A live response returned
  `data/hybrid-search-fundamentals.pdf`. Same question as `page`: translate here,
  or let clients strip it.
- **An OpenRouter rate limit answers 500, not the 503 with `Retry-After` this
  document specifies.** It falls into the generic handler. Closing it means
  `api.py` importing `openai` to recognise the exception, which is a coupling
  worth deciding rather than drifting into.
- **The streaming route.** `POST /query/stream`, once a UI exists to show it.
- **Authorisation over `chunks`.** Returning document text is safe for a corpus
  that is ours and a single user. Neither stays true forever.
