# Design: the container

Designed 2026-09-15, in a `grill-me` session.

## Problem

The API exists but only one machine can run it. Starting it means
`uv run uvicorn asgi:app --app-dir projects/01-basic-rag`, from the repo root,
on a Mac that already has uv, a resolved `.venv`, a `.env` and a Python 3.12 —
four things that are true here and nowhere else.

An `image` changes the requirement from *be this machine* to *have Docker*.
That is the whole of what this step adds. It is the second piece of deployment
work, after the API itself, and it is deliberately the local half: build it, run
it, prove it answers, understand every line. Nothing about AWS is decided here.

`designs/api.md` predicted this step and set an expectation worth answering
honestly. It observed that `asgi.py` needs a `sys.path.insert` line because
"uvicorn's `--app-dir` reaches the file but not the package beside it... without
the line the server dies at import on `No module named 'answerer'` while every
test still passes", and concluded: "The environment differed, not the code —
which is the plainest argument for containerising this that the project has
produced so far."

**Containerising does not remove that line.** The import path is a layout
problem in the code, and fixing it is its own decision. What the `image` removes
is the *variance*: the runtime environment is now built the same way every time,
so that class of bug becomes "always works or never works, and you find out at
`docker compose up`" rather than "works on my machine".

## Scope

**In.** A `Dockerfile`, a `.dockerignore`, an `api` service in the root
`docker-compose.yml`, and a documented way to check it works.

**Out**, deliberately.

- **`ingest`, `evaluate` and the rest of `main.py`.** The `image` runs the API
  and nothing else. Ingest stays a host command for the whole of this step.
- **The corpus.** `data/` is untracked, so a fresh clone builds an `image` with
  no documents in it. That is an ingest problem, and ingest is not in the
  `image`. See **Failure** for why it does not block anything here.
- **`/health` and `/ready`.** `designs/api.md` deferred them until an
  orchestrator existed. One still does not: the API opens no connection at
  startup, so there is nothing for a readiness probe to report that
  "the process is running" does not already say.
- **ECS, Fargate, ALB, registries, and production secret handling.**
- **Multi-stage builds.** Worth roughly 40 MB and a doubling of the concepts in
  the file. Deferred on purpose, not overlooked.
- **Automated `image` tests, and building the `image` in CI.** Verification for
  this step is manual and written down. See **Done**.
- **Any change to Python.** Not one line of `api.py`, `asgi.py` or `src/`.

## Design

### The `image` runs the API, and only the API

A `container` runs one long-lived process. `main.py` offers four commands and
`asgi.py` offers a server; the `image`'s default command is the server.

What this rules out, accepted knowingly: **the `image` is not self-sufficient.**
It cannot build its own index. The chunks it answers from were put into Qdrant
by a host-side `ingest`, and if that never happened it will answer questions
about nothing. Making it self-sufficient means putting the corpus somewhere a
`container` can read, which is the decision the AWS step exists to make.

### It reaches Qdrant by name, not by address

`QDRANT_URL=http://localhost:6333` is correct on the host and wrong inside a
`container`, because a `container`'s `localhost` is itself. It would find
nothing listening and fail with connection refused.

So the API becomes a **Compose service** named `api`, on the network Compose
already gives `qdrant`, `postgres` and `pgadmin`, and reaches Qdrant at
`http://qdrant:6333` — the service's name, resolved by Docker.

The alternative was `host.docker.internal`, a Docker Desktop hostname meaning
"the Mac outside". It was rejected for teaching something that has to be
unlearned: it **does not exist on Linux or in ECS**, whereas "address another
service by its name" is exactly what happens there too.

**`QDRANT_URL` now has two correct values on one machine** — `localhost:6333`
for the host's `ingest`, `qdrant:6333` for the `api` service. That conflict is
real and is resolved in the next section rather than avoided.

### Configuration arrives at run time, from `.env`, with one override

```yaml
env_file: .env
environment:
  QDRANT_URL: http://qdrant:6333
```

`env_file` hands the whole of `.env` to the `container`; `environment` overrides
the single variable whose correct value differs inside. `.env` itself is
unchanged and still right for the host.

**`.env` is never copied into the `image`.** Anything copied in survives in a
`layer` even if a later instruction deletes it, so the key would travel with
every copy of the artifact — and a key baked at build time means rotating it
requires a rebuild. Secrets are a run-time input.

No code change is needed for this. `asgi.py` calls `load_dotenv(".env")`, which
does not overwrite variables that are already set. With no `.env` in the
`image`, the call finds nothing, does nothing, and the values Docker supplied
stand.

**The whole file rather than a named subset, which is not this repo's usual
taste.** The argument is the failure mode. Almost every setting in `config.py`
has a default, and `EMBEDDING_MODEL`, `CHUNK_SIZE` and `CHUNK_OVERLAP` build
`collection_name`. A hand-maintained list that falls one variable behind does
not crash — it points the `container` at a *different, empty* collection and
answers 200 with plausible English. Silent and wrong beats nothing, so the
inclusive option wins.

The cost, named and accepted: the `api` service receives `OPENAI_API_KEY` and
`PGADMIN_PASSWORD`, which it has no use for. Least privilege is an AWS-step
concern, where secrets are injected per task and listing them is unavoidable
anyway.

### Dependencies come from `uv.lock`, without the dev group or the rerank extra

`uv sync --frozen --no-dev`. `--frozen` uses the lockfile exactly rather than
re-resolving, so the `container` holds the same versions this Mac does —
reproducibility being most of what an `image` is for. Exporting a
`requirements.txt` and using pip was rejected for adding a generated file that
nothing forces you to regenerate.

`--no-dev` leaves out pytest, pytest-cov and ruff. The rerank extra is not
installed, which leaves out `sentence-transformers` and **torch, roughly 2 GB**.

**The `image` therefore cannot rerank.** With `RERANKER_MODEL` empty — the
shipped configuration, measured and switched off — nothing notices. Set it, and
`asgi.py` calls `build_reranker` at import, which imports `sentence-transformers`,
which is not there: the `container` dies at startup on `No module named
'sentence_transformers'`. That is the fail-fast `designs/api.md` asks for, but
the message names a missing module rather than an `image` built without an
extra, so it is called out in a `Dockerfile` comment and in `.env.example`.

### The `image` holds the files the API runs, and no others

`pyproject.toml` and `uv.lock` from the repo root; `asgi.py`, `api.py` and
`src/` from `projects/01-basic-rag/`. Not `main.py`, `conftest.py`, `tests/`,
`designs/`, `investigations/`, `scripts/`, `docs/`, or any other project.

The `build context` is forced to the repo root, because nothing inside
`projects/01-basic-rag/` can reach up to the lockfile.

**Explicit copying is safe here because forgetting fails loudly.** A missed file
kills the `container` at startup with `No module named ...`. That is the
opposite of the configuration case above, where the inclusive option won
precisely because *its* failure was silent — the two decisions look
contradictory and are not: the question each time is whether a mistake announces
itself.

The cost: a new module outside `src/`, or a project 02, means editing the
`Dockerfile`. The crash says so.

A `.dockerignore` keeps `.env`, `.venv`, `.git`, `data/`, `.ruff_cache` and
`__pycache__` out of the `build context`. `.env` is there as a second line of
defence behind "we never copy it". `.venv` is there because a virtualenv built
on macOS is both broken and large inside a Linux `image`.

### The layout inside the `image` mirrors the repo

`WORKDIR /app`, with the manifests at `/app/` and the application at
`/app/projects/01-basic-rag/`. The command is what you would type on the host,
minus `uv run` and `--reload`:

```
uvicorn asgi:app --app-dir projects/01-basic-rag --host 0.0.0.0 --port 8000
```

Flattening everything to `/app/` would shorten that, and was rejected for
introducing exactly the thing this step exists to remove. The bug quoted at the
top was a *difference between two environments*; a rearranged copy is a new one,
and "works in the `container`" would stop being evidence about the host.

`--host 0.0.0.0` is not optional. Uvicorn defaults to `127.0.0.1`, which inside
a `container` means reachable only from inside that `container` — the logs say
`Uvicorn running` and the browser says connection refused.

Dependencies are installed before the source is copied, so that editing
`api.py` reuses the cached dependency `layer` instead of reinstalling LangChain.

### It runs as an unprivileged user

Docker runs as `root` by default, and a `container` is isolated processes on the
host kernel rather than a virtual machine, so uid 0 inside is uid 0 outside.
The API reads its own files and makes outbound calls; it needs none of that.

Two lines now, a confusing retrofit later — adding `USER` to a working `image`
produces `Permission denied` with no hint of the cause. Nothing here writes at
run time. The one thing that would have (`sentence-transformers` downloading
models into a cache) is absent for an unrelated reason.

## Interfaces

| File | Change |
|---|---|
| new — `projects/01-basic-rag/Dockerfile` | builds the `image` for the `api` service |
| new — `.dockerignore`, at the repo root | keeps `.env`, `.venv`, `.git`, `data/` and caches out of the `build context` |
| `docker-compose.yml` | gains an `api` service: builds from the root `build context`, publishes 8000, `env_file: .env`, `QDRANT_URL` overridden, no `restart:` |
| `.env.example` | a note that the `image` carries no reranker dependencies |
| `projects/01-basic-rag/README.md` | how to run it in Docker, and how to check it worked |
| `DOMAIN_TERMS.md` | `image`, `container`, `build context`, `layer`; `service` added to the ambiguous list |
| everything in `src/`, `api.py`, `asgi.py` | **unchanged** |

The `Dockerfile` lives beside the code it builds, while the `build context` is
the repo root. Those are set separately, and Compose says so in two fields.

## Failure

**A missing `OPENROUTER_API_KEY`** raises in `load_config` at import, uvicorn
exits, and the `container` exits with it. Intended: `designs/api.md` wants a bad
configuration to refuse to go live.

**No `restart:` policy**, unlike the other three services. They are
infrastructure that should stay up; the API is the thing under change, and
during this step most failures will be ours. A stopped `container` holds a
readable traceback still; a crash loop scrolls it away. The AWS step will want
the opposite, and that is fine — it is a different environment.

**Qdrant being down does not stop the API starting.** `open_vector_store` is
called inside `retrieve` (`retrieval.py:36`), per request, so nothing connects
at import. The `container` comes up healthy and the first query fails with a
500. `depends_on:` would not help — plain `depends_on` waits for the other
`container` to *start*, not to be ready — and is not needed, so it is not used.

**An empty or missing collection does not fail at all**, and this is the
dangerous one. Qdrant does not error on a collection with nothing in it.
Retrieval returns no chunks, the `answerer` truthfully says the context does not
contain the answer, and the response is **200 OK with plausible English**. Every
route to this ends in a `collection_name` mismatch: a setting that reached the
`container` differently from the host, or a corpus that was never ingested. It
is the reason **Done** is not just a status code.

## Done

Manual and written down, not automated. This step adds no Python, so there is
nothing for pytest to assert against; testing the `image` means building it and
running a `container`, which is a different kind of test and belongs with the CI
work. The existing 84 tests must still pass — they test the code, which is
unchanged.

Five checks, in order:

1. `docker compose up -d --build` brings the `api` service up and it stays up.
2. `http://localhost:8000/docs` loads — the port is published and uvicorn is
   listening on the right interface.
3. `POST /query` with a question returns **200** in the shape `designs/api.md`
   documents: `answer`, `chunks`, `request_id`.
4. `POST {}` returns **422**, confirming the validation path survived the move.
5. **The parity check.** A question whose answer is known from
   `01-basic-rag-benchmark` returns a **non-empty `chunks` array naming the
   expected source file**. Optionally the same question through
   `main.py ask` on the host, comparing sources.

Check 5 is the one that matters. Checks 1–4 pass just as happily against an
empty collection.

## Open questions

- **Where the corpus lives in production.** Deferred here with a reason: `data/`
  is only read by `ingest`, and `ingest` is not in the `image`. It becomes real
  when Qdrant is no longer a `container` on this laptop with data already in it.
- **Whether `ingest` should ever run in a `container`.** It would make indexing
  reproducible too, and it forces the corpus question above.
- **Multi-stage build**, for a smaller `image` without uv and its caches.
- **Building the `image` in CI**, and whatever automated check goes with it.
- **The `sys.path.insert` in `asgi.py`** is still there. Containerising removed
  the variance around it, not the line. Fixing it properly means deciding how
  `src/` is imported, which touches `main.py` and `conftest.py` too.
- **`restart:` and `/health`** both arrive with the AWS step, together, because
  the thing that restarts the task is the thing that needs to ask whether it is
  well.
