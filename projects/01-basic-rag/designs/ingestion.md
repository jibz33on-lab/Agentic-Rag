# Design: AWS ingestion

Built 2026-09-18, implementing the Option A decision recorded in
[`environments.md`](environments.md).

## Problem

The corpus reached DEV's Qdrant by an act nobody wrote down. The 2026-09-18
investigation reconstructed it from CloudTrail and CloudWatch: a security-group
rule described `"temporary: verification from my laptop"` was open from
2026-09-16T10:22Z to 2026-09-17T05:25Z, and EFS grew from 30,720 to 1,789,952
bytes inside that window.

That is a corpus that exists because one machine, once, could reach a database
it is normally walled off from. It cannot be repeated by anyone else, it cannot
be repeated on a different laptop, and it leaves no record of what was run.

## Scope

**In.** An ingestion path that runs in AWS, reads the corpus from S3, verifies
it, and rebuilds a Qdrant collection outright.

**Out**, deliberately.

- **Postgres, `SQLRecordManager`, and `index()`.** The decision, not an
  omission. See **No indexing state**.
- **The local `ingest` command.** Unchanged, still uses the `record_manager`,
  still the right thing on a development machine.
- **Scheduling.** The task is run by hand. No EventBridge, no Step Functions —
  a corpus that changes a few times a year does not need a scheduler.
- **Replacing the live collection automatically.** The rebuild writes where it
  is told. Promoting a staging collection is a separate, deliberate act.
- **EFS backup.** Explicitly deferred; the vectors are derived data and this
  path is what makes them reproducible.

## Design

### The shape

```
  S3  basic-rag-corpus-222043263320/corpus/
        │   4 documents + corpus.sha256
        ▼
  one-off ECS task   basic-rag-ingest
        │  fetch  →  verify sha256  →  load  →  split  →  embed  →  rebuild
        │
        │  runs with the API's security group, so it reaches
        ▼
  qdrant.basic-rag.local:6333     (Cloud Map, inside the VPC)
```

**No security-group hole, and no laptop.** `basic-rag-qdrant-sg` already admits
`sg-0142fb82d02201526` — the API's group — on 6333. The ingest task runs *with
that same group*, so it reaches Qdrant by exactly the path the API uses and
nothing had to be opened. This is the part worth keeping: the previous corpus
existed because a rule was opened; this one exists because no rule had to be.

### No indexing state

`ingest` calls LangChain's `index()`, which requires a `RecordManager` —
`record_manager` is a required positional parameter with no `None` overload, so
there is no "index without one" mode. This path therefore cannot be a flag on
the old one; it is a different write path.

`rebuild.py` drops the collection, recreates it, and calls
`QdrantVectorStore.add_documents`. No record manager, no Postgres, nothing to
keep in step.

**`build_embeddings` was moved out of `indexing.py` into `embeddings.py`** for
this. `indexing.py` imports `SQLRecordManager` at module level, so importing
anything from it would drag SQLAlchemy and psycopg into the ingestion image.
After the move, "no Postgres in the AWS ingestion path" is a property you check
by reading the imports rather than by tracing a call graph and trusting that
nothing ever calls `index_chunks`.

**What a full rebuild buys.** Incremental indexing is correct only while its
state and the store agree. They can silently disagree — re-ingesting into a
fresh Qdrant while reusing an existing `record_manager` writes **nothing** and
prints `added 0, skipped 126`. It looks like success. A rebuild has no state to
disagree with, which is the property a reproducible path actually needs.

**What it costs**, named and accepted: every run re-embeds all 126 `chunk`s.
Seconds, and cents. At a corpus large enough for that to matter, revisit.

### The manifest is checked before anything is embedded

`corpus.sha256` travels to S3 with the documents, and `fetch_corpus` verifies
the download against it before a single `chunk` is made.

This matters more in AWS than locally. `collection_name` is derived from the
chunking settings and **never** from the corpus, so a swapped document is
embedded into an identically named collection and nothing errors — the
benchmark's verbatim quotes simply stop matching, and it reads as retrieval
getting worse. Verifying first turns that into a loud failure, before the
embedding spend.

Three things fail the check, all deliberately: a changed document, a missing
one, and an **extra** one. An extra file changes the `chunk`s as surely as an
edited one.

### A rebuild of zero chunks is refused

`rebuild_collection` raises rather than proceeding when handed no `chunk`s.
Dropping the collection and writing nothing would leave the API answering
**200 OK with an empty `chunks` array** — this project's signature silent
failure. A loader that skipped every file is the likely cause, and it should
stop the run rather than quietly empty the store.

### The target collection is named at the call site

`open_vector_store` takes an optional `collection_name`. It is an explicit
argument and **deliberately not an environment variable**: a caller naming a
collection is visible where it happens, whereas an env-var override is exactly
the silent mismatch the derived name exists to prevent.

The one caller that passes it is the rebuild, which stages a new collection
beside the live one so the live one is never at risk while a run is verified.

## How to run it

```bash
aws ecs run-task \
  --cluster basic-rag-cluster \
  --task-definition basic-rag-ingest \
  --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={
      subnets=["subnet-0dd4ec73b42b20564"],
      securityGroups=["sg-0142fb82d02201526"],
      assignPublicIp="ENABLED"}' \
  --overrides '{"containerOverrides":[{"name":"ingest","command":[
      "--bucket","basic-rag-corpus-222043263320",
      "--prefix","corpus/",
      "--collection","bge-m3-1000-200-staging"]}]}'
```

`assignPublicIp` is required: the task reaches ECR, SSM, S3 and OpenRouter over
the internet, and there is no NAT gateway.

Drop `--collection` and it writes the collection the settings name — which is
the live one. Passing a staging name is how a run is made safe to verify.

Watch it with:

```bash
aws logs tail /ecs/basic-rag-ingest --follow
```

### Adding or changing a document

1. Put the file in `data/`.
2. Regenerate the manifest: `cd data && shasum -a 256 *.pdf *.docx > corpus.sha256`
   — keeping the header comment lines.
3. `uv run python projects/01-basic-rag/main.py verify-corpus`
4. `aws s3 sync data/ s3://basic-rag-corpus-222043263320/corpus/ --exclude "*" --include "*.pdf" --include "*.docx" --include "corpus.sha256"`
5. Run the task above into a staging collection, verify, then promote.

**The benchmark is tied to the corpus.** `01-basic-rag-benchmark`'s quotes are
verbatim spans of the current `chunk`s, so changing a document invalidates
comparisons against every recorded experiment. That is a real cost, not a
formality.

### Restoring from nothing

If the Qdrant collection or the whole EFS filesystem were lost:

1. Recreate the filesystem and mount targets if needed; point the Qdrant task
   definition at it and force a new deployment.
2. Run the task above, writing the live collection name directly — there is
   nothing to protect.
3. Verify, using the inspection task below.

No laptop, no security-group change, no `data/` folder. **That is the whole
point of this step.**

### Looking inside Qdrant

Qdrant is not reachable from outside the VPC by design, so `basic-rag-qdrant-inspect`
runs an arbitrary Python snippet on the same network path. Revision 1 has
Qdrant only; revision 2 also carries the OpenRouter key, for retrieval checks.

```bash
aws ecs run-task --cluster basic-rag-cluster \
  --task-definition basic-rag-qdrant-inspect:1 --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={subnets=["subnet-0dd4ec73b42b20564"],securityGroups=["sg-0142fb82d02201526"],assignPublicIp="ENABLED"}' \
  --overrides '{"containerOverrides":[{"name":"inspect","command":["<python here>"]}]}'
```

## Interfaces

| File | Change |
|---|---|
| `src/embeddings.py` | **New.** `build_embeddings`, moved out of `indexing.py`. |
| `src/indexing.py` | `build_embeddings` removed. `index_chunks` unchanged. |
| `src/corpus_source.py` | **New.** `fetch_corpus(client, bucket, prefix, destination)`. |
| `src/rebuild.py` | **New.** `rebuild_collection(chunks, config, embeddings, collection_name=None)`. |
| `src/vector_store.py` | `open_vector_store` takes an optional `collection_name`. |
| `main.py` | New `rebuild` command with `--bucket`, `--prefix`, `--collection`. |
| `asgi.py` | Imports `build_embeddings` from its new home. |
| `conftest.py` | New `qdrant_only` fixture — Qdrant without Postgres, and it cleans up. |
| `Dockerfile.ingest` | **New.** Carries `main.py`; entry point is `rebuild`. |
| `pyproject.toml` | `boto3` added. |

## Failure

| What | What happens |
|---|---|
| A document changed, missing, or extra | `CorpusError` before any embedding. Task exits non-zero. |
| No `corpus.sha256` under the prefix | `CorpusError`. Refused rather than trusted. |
| Every document fails to load | `ValueError` from `rebuild_collection` rather than an emptied collection. |
| Qdrant unreachable | Connection error. The collection is untouched — the drop happens after the fetch and verify. |
| OpenRouter rejects the key | Fails during `add_documents`, after the collection was dropped. **The collection is left empty.** This is the one destructive failure mode; run into a staging name and the live collection is unaffected. |

## Done

Verified 2026-09-18 against DEV:

- The task ran to **exit code 0** in 37 seconds and logged
  `57 documents -> 126 chunks`, `wrote 126 chunks to bge-m3-1000-200-staging`.
- The inspection task reported **`bge-m3-1000-200`: 126 points** — the live
  collection, untouched — and **`bge-m3-1000-200-staging`: 126 points**.
- A retrieval parity check for *"What is reciprocal rank fusion?"* returned the
  **same four chunks, same pages, same order** from both collections.
- 111 tests pass; ruff clean.

## Open questions

- **The staging collection still exists.** Promoting it — pointing the API at
  it, or rebuilding the live name — is a deliberate act and has not been done.
- **Provenance of the four documents is still unrecorded.** S3 makes the corpus
  reproducible *from what we have*; it does not make it rebuildable from
  sources. `data/README.md` has the table waiting.
- **The image tag is `ingest-d127e39-wip`**, built from an uncommitted tree. It
  should be rebuilt and tagged from a commit before it is relied on.
- **Ingestion is not in CI.** It is a manual `run-task`. Whether it should be a
  workflow is undecided.
