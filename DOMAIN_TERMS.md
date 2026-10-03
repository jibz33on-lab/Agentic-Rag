# Domain Terms

The shared vocabulary for this repo. These exact words are used in conversation,
code, comments, tests, and docs — by both the human and the AI.

**We use LangChain's names wherever LangChain supplies the thing.** Learning the
real names is part of the point: they are what the docs, the job adverts and the
rest of the field use. We keep our own word only where LangChain has no word for
something, and each of those is flagged below.

If a term is ambiguous or missing, we stop and fix it here before writing more
code.

> **Review status.** The LangChain names are taken from its current documentation.
> `chunk`, `candidate`, `retrieval_signals`, `answerer` and `rag_query` are ours,
> kept deliberately. `golden_example` and `evaluation_run` were settled in the
> evaluation design session, `reranker` and `candidate` in the reranking one, and
> none of those four are drafts. Still AI-proposed drafts: `document`,
> `tool_call`, `trace`, and the four Docker terms under **Shipping it** —
> proposed 2026-09-15 in the containerisation session and not yet read back.
>
> **Project 02.** Which AWS words to adopt was settled by the user on 2026-09-30
> in the project 02 skeleton session: AWS's names for AWS's things, our own terms
> kept where they are shared across both projects, and no abstraction invented to
> make the two agree. The definitions and the *Not:* lines under **AWS-native RAG**
> are AI-drafted and not yet read back, as are the four new entries under
> **Ambiguous words**.

---

## Core data

### `document`
In LangChain, a `Document` is a piece of text plus its metadata. Note that
LangChain uses it for **both** the whole source file and each piece it is split
into — the type does not change when you split.

### `chunk` — *ours*
One piece of a `document` after splitting, sized for retrieval and embedding.

LangChain has no word for this; a split is just another `Document`. We keep
`chunk` because "document" meaning both the whole PDF and one paragraph of it is
genuinely confusing in conversation. In code it will be a `Document` like any
other.

### `candidate` — *ours*
A `chunk` the `vector_store` returned for possible use, before the `reranker`
cuts to `TOP_K`. `CANDIDATE_COUNT` is how many are fetched.

*Not:* a `chunk` the `answerer` sees. Only the surviving `TOP_K` reach the
prompt. The distinction is the point of re-ranking: `evidence_found` is measured
on what the `answerer` received, while the ceiling on it is set by what was a
`candidate`.

---

## The pipeline

### `document_loader`
Reads a source file and produces `Document`s. `PyPDFLoader` for PDFs,
`Docx2txtLoader` for docx. One class per format.

*Not:* it does not split, and it does not decide what to do when a file fails.

### `text_splitter`
Cuts a `Document` into smaller ones. `RecursiveCharacterTextSplitter` is the
default choice, configured with a chunk size and an overlap.

*Not:* it does not embed or store. It sees one `Document` at a time.

### `embedding_model`
Turns text into numbers. Ours is `baai/bge-m3` through OpenRouter, producing 1024
dimensions.

*Not:* it does not decide what counts as similar — the vector store does that.

### `vector_store`
Holds `chunk`s and their vectors, and finds the nearest ones to a query.
`QdrantVectorStore` in our case.

*Not:* it does not interpret what it returns, and it does not know which files have
already been ingested — that is the record manager.

### `record_manager`
Remembers which source files have been ingested and what was in them, so a re-run
can tell a new file from an unchanged one from an edited one. `SQLRecordManager`,
backed by Postgres.

*Not:* it holds no text and no vectors, and it decides nothing — the indexing API
acts on what it reports.

### `indexing`
LangChain's `index()` function: the run that loads, splits, embeds and stores,
using the record manager to skip unchanged files and clean up stale ones.

*Not:* a single call to add documents. It is the whole re-runnable pass.

### `retriever`
Goes from a query to relevant `chunk`s. Usually made with
`vector_store.as_retriever()`, configured with a search type and how many to
return.

*Not:* it does not interpret what it found or decide what happens next.

### `reranker`
Scores each (query, `candidate`) pair *jointly* and reorders by relevance,
keeping the top `TOP_K`. `CrossEncoderReranker` over a local cross-encoder.

*Not:* a `retriever`. It fetches nothing. It only reorders what the `retriever`
returned, so it can never recover a `chunk` the `vector_store` did not hand it —
which is why `CANDIDATE_COUNT` sets a hard ceiling on what re-ranking achieves.

*Not:* the `embedding_model`. That encodes the query and the `chunk` separately
and compares two vectors, which is what makes it cheap enough to run over the
whole collection. A `reranker` reads both texts together, which is why it is
more accurate and why it is only affordable over a handful of `candidate`s.

### `generation`
The step that turns a query plus retrieved `chunk`s into an answer, done by a chat
model with a prompt.

### `answerer` — *ours*
Our name for the component that performs `generation`. LangChain has no single
word for it — it is a chat model plus a prompt, wired together.

*Not:* it does not choose what to retrieve, and does not judge whether the evidence
is good enough. In a plain RAG nothing does. That becomes the `agent`'s job, and
that line is where plain RAG ends and agentic RAG begins.

### `rag_query` — *ours*
One pass from question to answer: `retrieval` and `generation` as a single traced
unit. LangChain has no word for the pair, and the distinction matters here —
it is the unit an `evaluation_run` measures, and the unit a `trace` records.

*Not:* the retriever's search, which is only its first half. Not the `trace`
either — that is the record the pass leaves behind, not the pass.

### `retrieval_signals` — *ours*
What retrieval noticed while fetching, returned alongside the `chunk`s. LangChain
has no equivalent; nothing in the framework reports this.

A fixed set of three:

- **weak match** — the best score was low, so likely nothing here answers the
  query. Defined per retriever, since scores are not comparable across them.
- **source concentration** — how few source files the returned `chunk`s came from.
- **candidate count** — how many `chunk`s were considered before cutting to top-k.

Observations, not judgements. Retrieval reports what it saw; the `agent` decides
what it means. The set is fixed deliberately — adding a field later means editing
every retriever that already exists.

---

## Later, not in project 01

### `agent`
Decides what to do next: which `tool_call` to make, whether the evidence so far is
enough, when to answer. Owns control flow and all interpretation — reading
`retrieval_signals`, noticing when sources disagree, deciding to answer from the
best match while quoting what contradicts it.

*Not:* a retriever. Retrieval fetches when asked; the agent decides.

### `tool_call`
One invocation of a capability by the `agent` — a retrieval, a search, a
calculation — with its arguments and its result. The atomic step recorded in a
`trace`.

---

## Knowing whether it works

### `trace`
The full ordered record of one run: the query, every `tool_call` and result, the
decisions taken, and the final answer. This is what LangSmith captures
automatically when LangChain is used directly.

### `golden_example`
A query paired with its expected answer and a verbatim `quote` — the span of text
the answer should have come from. The fixed reference an `evaluation_run`
measures against.

Evidence is a `quote`, not a `chunk` id and not a page. Ids die the moment
`CHUNK_SIZE` changes, and comparing chunk sizes is the main thing the golden set
exists for. Content survives re-chunking; identifiers do not.

Generated by an LLM from a sampled `chunk`, and carrying a `provenance` of
`generated` until a human has read it, at which point it becomes `accepted`.
What is forbidden is generated **and silently trusted** — not generation. The
provenance is always visible, and the file is committed so that accepting one is
a reviewable change.

*Not:* a test case. Nothing fails because a `golden_example` scores badly; it
produces a number to compare against another number.

### `evaluation_run`
One scoring pass of a configuration against a set of `golden_example`s, producing
comparable numbers. The unit of "did this change help" — meaningless unless the
`golden_example` set is held constant across runs.

---

## Shipping it

**We use Docker's names wherever Docker supplies the thing**, for the same
reason we use LangChain's: they are the words the docs, the job adverts and
every other engineer use. None of these is ours.

### `image`
The built, frozen artifact: a filesystem plus a default command. Built once from
the `Dockerfile`, and unchanging afterwards.

*Not:* a running thing. An `image` runs no code and holds no state. Ours
contains project 01's API and nothing else — no `main.py`, no corpus, no
reranker dependencies.

### `container`
One running instance of an `image`. Several can run from the same one.

*Not:* a virtual machine. It is isolated processes on the host kernel, which is
why the user it runs as is a real decision rather than a formality.

### `build context`
The folder handed to `docker build`. Nothing outside it can be copied into the
`image`, which is why ours is the repo root: `pyproject.toml` and `uv.lock` live
there, and `projects/01-basic-rag/` cannot reach up to them.

*Not:* the folder the `Dockerfile` sits in. Those are set separately.

### `layer`
One frozen slice of filesystem, produced by one `Dockerfile` instruction and
cached. Two consequences we rely on: a file copied into a `layer` stays in the
`image` even if a later instruction deletes it — which is why `.env` must never
be copied — and an unchanged instruction reuses its cached `layer`, which is why
dependencies are installed before the source is copied.

---

---

## AWS-native RAG — project 02

**We use AWS's names wherever AWS supplies the thing**, for the same reason we
use LangChain's and Docker's: they are the words in the docs, the console and the
error messages. Project 02 exists to learn AWS, and a private synonym for
`ingestion_job` would teach the wrong word.

Our own terms — `chunk`, `answerer`, `rag_query`, `evaluation_run` — stay. They
are the spine that lets the two projects be compared: an `evaluation_run`
measures `rag_query`s, and if project 02 called that something else the
comparison would lose its shared noun.

No abstraction is introduced to make the two projects share vocabulary. Where
they differ the words differ, because the differences are the thing being studied.

### `knowledge_base`
Bedrock's managed retrieval resource. It owns chunking, embedding, storage and
search over a set of `data_source`s. Ours is customer-managed, backed by a
`vector_bucket`.

*Not:* a `vector_store`. A `vector_store` is something project 01 constructs and
calls; a `knowledge_base` is a resource that owns its own storage and is
configured rather than driven. It has no single counterpart in project 01 — the
nearest thing is `indexing`, `vector_store` and `retriever` taken together.

### `data_source`
Where a `knowledge_base` gets its `document`s. Ours is an S3 bucket reached
through the S3 connector, which is credential-free.

*Not:* the `document`s, and not the bucket. It is the configured link between the
two, and it carries the chunking strategy.

### `ingestion_job`
One run of a `data_source` being read into its `knowledge_base` — load, chunk,
embed, store. Started with `start-ingestion-job` and polled to completion.

*Not:* instant. A `Retrieve` issued before it finishes returns empty rather than
failing, which is the failure mode most likely to be mistaken for a bug.

*Not:* `indexing`. Both are the re-runnable load-and-store pass, but `indexing`
is a function project 01 calls and waits on in-process, while an `ingestion_job`
is an asynchronous job AWS runs on our behalf.

### `vector_bucket`
The S3 Vectors bucket a `knowledge_base` stores its vectors in. A dedicated
resource addressed by `vectorBucketArn`, not a regular S3 bucket.

*Not:* the S3 bucket holding the `document`s. Two different buckets, and
conflating them is how an IAM policy ends up granting the wrong thing.

*Not:* something we query. Only the `knowledge_base` reads it.

### `Retrieve`
The Bedrock API that returns `chunk`s for a query. Semantic only on a
`vector_bucket`: `overrideSearchType: HYBRID` requires OpenSearch Serverless,
Aurora PostgreSQL or MongoDB Atlas.

*Not:* a `retriever`. There is no object to construct and hold — it is one call.

### `RetrieveAndGenerate`
The Bedrock API that retrieves and answers in a single call, with citations.

*Not:* what we use. Project 02 keeps retrieval and `generation` separate so the
`answerer` and its prompt stay ours and stay comparable with project 01's. It is
named here because it is the obvious thing to reach for, and choosing not to is a
design decision rather than an oversight.

### `foundation_model`
Bedrock's name for a model you invoke — `anthropic.claude-…`,
`amazon.titan-embed-text-v2:0`. Named in `knowledge_base` configuration and in
`Converse` calls.

*Not:* the `answerer`. The `answerer` is a `foundation_model` plus a prompt, as
it has always been.

---

## Ambiguous words

### `service`
Means two things, and both appear in this repo:

1. **A Compose service** — one entry under `services:` in `docker-compose.yml`.
   `qdrant`, `postgres`, `pgadmin` and now `api` are each one. This is our
   default meaning, because it is the one written down in a file.
2. **The thing the API is** — as `designs/api.md` uses it, meaning the
   long-running process that answers `rag_query` over HTTP.

They coincide for `api` and diverge everywhere else: Qdrant is a Compose service
and not ours to call a service in the second sense. Say "the `api` service" when
you mean the Compose entry.

### `index`
Means three different things:

1. **LangChain's `index()`** — the load, split, embed, store pass. This is our
   default meaning, because we call that function.
2. **The structure inside a vector store** that makes search fast — HNSW and
   friends, inside Qdrant.
3. **A plain database lookup table.**

When it is not obviously the first, say which one.

### `document`
Means both a whole source file and one split piece of it, because LangChain uses
one type for both. Say `chunk` when you mean a piece.

### `indexing`
Project 01 only. LangChain's `index()` — see `index` above. Project 02's
equivalent pass is an `ingestion_job`, and the two are deliberately not given the
same name: one is a function we call and wait on in-process, the other is an
asynchronous job AWS runs for us.

### `vector_store`
1. **Project 01** — `QdrantVectorStore`, a LangChain object we construct, call,
   and hand to a `retriever`.
2. **Project 02** — nothing. The `knowledge_base` owns storage, and the
   `vector_bucket` underneath it is never addressed directly.

Say `vector_bucket` for project 02's storage. Do not say `vector_store` about
project 02 at all — there is no such object to point at.

### `retriever`
1. **Project 01** — a LangChain object from `vector_store.as_retriever()`,
   configured with a search type and `TOP_K`.
2. **Project 02** — no such object. Retrieval is a `Retrieve` call taking
   `numberOfResults`.

The asymmetry is worth keeping rather than smoothing over: project 01 holds a
retriever, project 02 makes a request. That difference is a large part of what
the two projects are being compared on.

### `embedding_model`
1. **Project 01** — `baai/bge-m3` through OpenRouter at 1024 dimensions,
   constructed by us and passed where it is needed.
2. **Project 02** — a Bedrock `foundation_model`, Titan Embed Text V2 by
   default, named in `knowledge_base` configuration and never called by us
   directly.

Same idea, different thing, and the vectors are not comparable. A retrieval
number from one project is not a retrieval number from the other, which is why
the benchmark compares answers rather than distances.

## Adding a term

Propose it here first, with a one-line definition and a note on what it is *not*.
Ambiguity between two neighbouring terms is the thing worth spending words on.
