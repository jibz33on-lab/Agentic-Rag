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
> `tool_call` and `trace`.

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

## Ambiguous words

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

## Adding a term

Propose it here first, with a one-line definition and a note on what it is *not*.
Ambiguity between two neighbouring terms is the thing worth spending words on.
