# The `ingestion_job` and its verification

Design session, 2026-10-03. Covers slice 1. Refines `skeleton.md`, which still
owns the slices 1–3 overview.

## Problem

Slice 1 stands up the AWS-native write path: `document`s in S3, a
`knowledge_base` over a `vector_bucket`, and an `ingestion_job` that chunks,
embeds and stores. The write path is not the hard part — proving it did what it
claims is. Bedrock reports an `ingestion_job` successful while silently skipping
`document`s it could not handle, so an unverified write path makes every number
in slices 2 and 3 untrustworthy without ever looking wrong.

## Scope

**In:** the `infra/core` root module (document bucket, `vector_bucket` and its
index, the service role, the `knowledge_base`, the `data_source`, the SSM
parameters); `parameters.py`, `config.py`, `kb_client.py` and `main.py`;
`ingestion_job` statistics on every run with a non-zero exit on failures; and a
sampled `chunk` character distribution compared against project 01's.

**Out, to slice 2:** the read path proper — the `answerer`, the `v1` prompt,
`rag_query`, and LangSmith tracing. Slice 1 calls `Retrieve` only to verify
storage.

**Out, to slice 3:** the 25-question benchmark and any retrieval-quality claim.

**Out, to its own experiment after slice 3:** Contextual Retrieval through a
`POST_CHUNKING` transformation Lambda. See Open questions.

**Out permanently:** `RetrieveAndGenerate`, per `skeleton.md`.

## Design

### Two kinds of bucket

The `document`s live in an ordinary S3 bucket. The embeddings live in a
`vector_bucket`, which is an S3 Vectors resource and not an S3 bucket at all,
with its own index resource underneath it. Conflating the two is the first
mistake available in this slice, and the vocabulary in `DOMAIN_TERMS.md` exists
to stop it.

### The resource graph

Seven resources in `infra/core`, in dependency order: the document bucket; the
`vector_bucket`; its index; the service role with three attached policies; the
`knowledge_base`, binding the `embedding_model` to the index; the `data_source`,
binding the document bucket to the chunking strategy; and two SSM parameters
carrying the `knowledge_base` and `data_source` ids at committed paths.

The role is four things rather than one: a trust policy for
`bedrock.amazonaws.com` carrying `aws:SourceAccount` and `aws:SourceArn`
conditions, `bedrock:InvokeModel` scoped to the Titan `embedding_model` ARN, S3
read on the document bucket, and the `s3vectors` read/write set scoped to the
index ARN. IAM is eventually consistent, so the first apply may fail to assume a
role it created seconds earlier; that is a retry, not a bug.

### What is immutable

Nearly every meaningful argument replaces its resource rather than updating it:

| Change | What is replaced |
|---|---|
| chunking strategy, `maxTokens`, `overlapPercentage` | the `data_source` |
| `embedding_model` or its dimension | the whole `knowledge_base` |
| index dimension, distance metric, data type | the index |
| the index's non-filterable metadata keys | the index |

`skeleton.md` already treats the first two as the point — Terraform forcing a
replacement rather than letting configuration drift, the property
`collection_name` gives project 01. The index-level rows are new, and sharper,
because the index sits underneath the `knowledge_base`.

### The one setting that will fail quietly if it is wrong

The index must declare `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` as
**non-filterable** metadata keys.

Bedrock writes the `chunk` text itself into per-vector metadata. S3 Vectors caps
*filterable* metadata at 2048 bytes per vector, and an index created with no
metadata configuration makes every key filterable. At `maxTokens: 250` a `chunk`
is roughly 1000 characters, so this rejects most of the corpus rather than an
unlucky tail. Declaring the keys non-filterable removes them from the budget and
changes nothing otherwise — they are still stored and still returned.

It is immutable after index creation, and it presents exactly as the failure this
slice exists to catch: an `ingestion_job` that reports success over an
incomplete corpus.

### `dataDeletionPolicy` is set explicitly

With `RETAIN`, replacing a `data_source` — which Terraform does on any chunking
change — leaves the old vectors in the index beside the new ones. One index per
`knowledge_base` means `Retrieve` would then return two generations of `chunk`s
with no way to tell them apart. Left to a default this is a trap; written down it
is a decision.

### Ingestion is not a resource

Terraform builds the pipe; `start_ingestion_job` is a runtime call. That
asymmetry is the whole reason `kb_client.py` exists in a slice that is otherwise
infrastructure, and it is why `ingest` is a command rather than an `apply`.

### The verification `Retrieve`

Slice 1 calls `Retrieve` — with no `answerer`, no `v1` prompt, no `rag_query` and
no `trace` — to sample stored `chunk`s, confirm `document`s are indexed, and
measure `chunk` character lengths.

The alternative was reading vectors through the `s3vectors` API and pulling text
out of `AMAZON_BEDROCK_TEXT`. That was rejected: it keeps slice 1 free of
`bedrock-agent-runtime` at the cost of throwaway code against a second API,
whereas a bare `Retrieve` is the first caller of an interface slice 2 needs
anyway. Nothing built here is scaffolding.

**The distribution is a sample, not the population.** Retrieved `chunk`s are
whatever ranked highest for the queries asked, so the lengths are biased by the
query set. That is enough to check whether 250 tokens really landed near project
01's 1000 characters, which is all `skeleton.md` asks. It is not "project 02's
chunk distribution", and must not be quoted later as if it were.

### A Managed Knowledge Base was considered and rejected

AWS now offers a managed `knowledge_base` where Bedrock owns the vector store
outright — no `vector_bucket`, no index, no storage configuration — and it is the
current default recommendation for new RAG work. It would delete most of this
slice.

It is refused for the reason project 02 exists: the premise is that the work
moves into Terraform and IAM, and a managed store hides precisely the service
role, the index configuration and the storage binding this project is here to
learn. The trade is deliberate rather than unexamined.

## Interfaces

- **`parameters.py`** — `load_parameters(ssm) -> Mapping[str, str]`, returning the
  `knowledge_base` and `data_source` ids under plain keys. The boto3 SSM client is
  passed in rather than built inside, so a test can hand over a stand-in and no
  caller is forced to reach AWS. One `get_parameters` call covers both paths,
  because it reports absent names instead of raising: a fresh clone with no stack
  deployed gets one error listing everything it needs, rather than fixing one path
  and rediscovering the next.

  **It is the only module that touches SSM, and that is load-bearing rather than
  tidiness.** It keeps the committed path constants in one place, so there is
  exactly one definition of `/bedrock-rag/knowledge-base-id` in the codebase. It
  is also what makes "config does no I/O" checkable by reading imports — a
  property `config`'s own tests assert, by parsing its imports and failing on
  anything that could reach the network.

- **`config.py`** — `load_config(env, parameters) -> Config`, pure, with the two
  sources kept apart.

  `skeleton.md` sketches `load_config(env: Mapping)`. Two arguments instead,
  because environment variables and SSM values are not interchangeable and each
  error should name its real source: `TOP_K` names a variable you can export, a
  missing id names an SSM path you cannot. Folding the ids into `env` would mean
  either inventing variable names for AWS-generated ids — so a missing id would
  report `KNOWLEDGE_BASE_ID is missing`, pointing at something nobody is supposed
  to set when the real fix is to apply `infra/core` — or having `main.py` merge
  the two mappings first, which is a caller setting up state before it can call.

  Every requirement that sentence in `skeleton.md` states is still met: project
  01's shape (frozen dataclass, `DEFAULT_*` constants, `ValueError` naming the
  variable), purity, pure tests, and raising on a missing value naming the path —
  that last from `parameters.py`, one module earlier than the sketch anticipated.
  `skeleton.md` is left as written. It is the architectural sketch, not a
  specification, and the slices refine it rather than rewrite it.

  `Config` carries no `chunk_size` or `chunk_overlap`. Project 01's does, because
  its own code splits the text; here the `knowledge_base` splits it and those
  settings live in `infra/core` as Terraform variables. The absence is the managed
  pipeline showing up in the shape of the code.

  **Both modules live in `src/bedrock_rag/`, not directly in `src/`.** Project 01
  already puts a top-level `config` on `sys.path`, both projects run in one pytest
  session against one `.venv`, and the first `config` imported wins for the whole
  run — so flat modules here meant project 02's tests silently importing project
  01's `config`. The skeleton names `main`, `answerer` and `rag_query` for this
  project too, and project 01 has all three; this was not a near miss.

- **`kb_client.py`** — `start` and `status` as separate operations from the
  outset, plus `Retrieve`. **`numberOfResults` is a parameter, not a constant:**
  verification wants a wider sample across several queries, slice 2 wants exactly
  8 to match project 01's shipped `TOP_K=8`. The 8 becomes a committed default in
  `config`, the shape `DEFAULT_TOP_K` already has.
- **`main.py`** — `ingest`, composing `start` and `status` into a blocking
  command, recording the `ingestion_job` statistics on every run and exiting
  non-zero when `numberOfDocumentsFailed > 0` with `failureReasons` printed. The
  verification is a **separate command**, not folded into `ingest`: one
  component, two callers, mirroring `verify-corpus` in project 01. Folding it in
  would make every ingestion pay for a retrieval it may not want.

No new entry in `DOMAIN_TERMS.md`. `Retrieve`, `chunk` and `ingestion_job`
already cover this; a verification `Retrieve` is a use of an existing term, not a
new concept.

## Open questions

- **What `numberOfDocumentsSkipped` counts** — unchanged files on a re-run, or
  only problem files. Carried over from `skeleton.md`; the first real
  `ingestion_job` answers it. Observed, not gated on, until then.
- **The verification command's name.** Its shape is settled, its name is not.
- **Hierarchical chunking is partly closed by the storage choice.**
  `skeleton.md` queues it as a future one-variable experiment, but AWS does not
  recommend it with a `vector_bucket`: combined parent and child token counts
  past roughly 8000 hit the same metadata size limits as the non-filterable keys
  above. Recorded here so the experiment is not designed twice.
- **Contextual Retrieval, sequenced.** A `POST_CHUNKING` transformation Lambda is
  the AWS-native hook — Bedrock chunks, writes batches to an intermediate bucket,
  calls the Lambda, embeds what it returns. It is deferred until after slice 3
  for three reasons, each worth keeping: before slice 3 there is no measured
  baseline to compare against, so it could only produce an impression; two
  `data_source`s in one `knowledge_base` share one index, so the experiment needs
  its **own** `knowledge_base` to leave the baseline intact; and a meaningful
  share of the published benefit comes from pairing contextual `chunk`s with
  keyword search, which S3 Vectors cannot do — making the real experiment a 2×2
  with the hybrid spike rather than a single run. Its context prompt also needs a
  frozen name in the prompt registry, since an LLM-written `chunk` is not
  reproducible the way `FIXED_SIZE` is.
