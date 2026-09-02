# Design: the skeleton

Designed 2026-09-01. Rewritten 2026-09-02, when the project switched to LangChain.

## Problem

We want to understand the difference between building RAG with **LangChain** and
with **LlamaIndex**, and then go on to agents and multi-agent systems.

To compare two frameworks you need the same problem solved twice. This is that
problem, solved the first way. Project 02 will be the same thing in LlamaIndex,
built in parallel rather than swapped in — each written in its framework's natural
style, so the comparison shows what each is actually like to use.

## Scope

**In**

- LangChain, used **directly**. No wrapper layer of our own.
- Real PDF and docx files
- A terminal command
- Qdrant for vectors, Postgres for the record manager
- OpenRouter for both the embedding model and the chat model
- LangSmith for tracing

**Out**

- Agents. This is plain RAG.
- Evaluation — `golden_example`, `evaluation_run`
- Any frontend
- Fallback providers
- Any abstraction layer over LangChain. If LangChain supplies it, we call it.

## Why no wrapper

The obvious alternative was to put our own components in front of LangChain, so
the LlamaIndex version could swap the insides. We chose not to, for two reasons:

- **LangSmith traces LangChain directly.** Using its objects as intended gives
  full traces without extra work, and tracing is what makes evaluation possible
  later.
- **A parallel build is the better comparison.** Forcing both frameworks into our
  own shape would hide exactly the differences we want to see.

The cost is that project 02 is a rewrite, not a swap. Accepted knowingly.

## The pipeline

| Step | What supplies it |
|---|---|
| load a file | `PyPDFLoader`, `Docx2txtLoader` |
| split it | `RecursiveCharacterTextSplitter` |
| turn text into numbers | OpenRouter embedding model, `baai/bge-m3` |
| hold the vectors | `QdrantVectorStore` |
| remember what was ingested | `SQLRecordManager` on Postgres |
| run the whole ingestion | `index()` |
| find relevant `chunk`s | `vector_store.as_retriever()` |
| write the answer | a chat model with a prompt |

## How indexing works

`index()` does most of it:

```
index(docs, record_manager, vector_store,
      cleanup="incremental", source_id_key="source")
```

What that gives us, without writing it ourselves:

- **Unchanged files are skipped.** It hashes each document (SHA-1 by default) and
  compares against the record manager.
- **Edited files are replaced.** `cleanup="incremental"` deletes the old pieces of
  a document as the new ones land, so an edit never leaves both versions behind.
- **It reports what happened** — added, updated, skipped and deleted counts.

### One collection per settings combination

`index()` hashes file *contents*, not our settings. So changing the chunk size
leaves every file looking unchanged, and the new setting silently never reaches
the store.

We avoid that by giving each combination of settings its own home:

```
chunk size 500,  bge-m3  ->  collection "bge-m3-500",  namespace "bge-m3-500"
chunk size 1000, bge-m3  ->  collection "bge-m3-1000", namespace "bge-m3-1000"
```

Both the Qdrant collection name and the `SQLRecordManager` namespace are built
from the settings rather than hardcoded. Change a setting and you are pointing at
an empty collection, so everything indexes fresh, and nothing is ever mixed.

Two things fall out of this for free. Both versions survive, so chunk sizes can be
compared without re-ingesting between each run. And a change of embedding model
needs a new collection anyway, because the vector size changes and a Qdrant
collection's size is fixed — this scheme already does that.

The model name contains a slash (`baai/bge-m3`), so it needs sanitising before it
can be used in a collection name.

What is still ours:

- **A file that cannot be read must not stop the run.** Loading happens before
  `index()` is called, so the loop over files catches its own errors, records the
  skip, and carries on. LangChain does not do this for us.
- **Printing the retrieved `chunk`s alongside the answer.**

## How a query works

1. You type a question into the terminal.
2. The retriever finds the closest `chunk`s.
3. A chat model turns the question plus those `chunk`s into an answer.
4. The terminal prints the answer **and** the `chunk`s it used.

Printing the `chunk`s is deliberate. If the answer is wrong, you can see whether
retrieval found the wrong text, or found the right text and the model misread it.

## Decisions, and why

| Decision | Why |
|---|---|
| LangChain used directly, no wrapper | LangSmith tracing, and a parallel build compares better than a swap |
| Real PDFs and docx from day one | Working on real data was worth more than an easier start |
| A bad file is skipped, not fatal | One broken PDF should not waste the other nineteen |
| `cleanup="incremental"` | An edited file replaces its old pieces rather than duplicating them |
| Two databases — Qdrant and Postgres | `SQLRecordManager` is SQL-backed, so Postgres was always going to be there |
| `bge-m3` for embeddings | Most cheap models cap input at 512 tokens, which would cap the chunk sizes we can compare |
| One collection and namespace per settings combination | `index()` hashes content, not settings, so a chunk-size change would otherwise be silently ignored |
| No fallback provider | For embeddings it is a correctness risk — two models produce vectors that cannot be compared |
| Config read by hand, not pydantic | Seeing what the validation does before delegating it |

## What LangChain absorbed

Three things we designed by hand on day one turned out to be built in. Worth
recording, because noticing it is part of the comparison:

- content-hash change detection
- delete-before-write when a document changes
- reporting counts at the end of a run

Our reasoning about *why* those matter still holds. We just do not write them.

## Accepted trades

- **Project 02 is a rewrite, not a swap.** The price of using LangChain directly.
- **We learn LangChain's shape, not RAG's shape from scratch.** Deliberate — the
  frameworks are what companies use.

## Open questions

- When to delete an old collection once a comparison is finished. Keeping them is
  the point, but they are not free forever.
- Chunk size and how many `chunk`s to retrieve. Settings to tune.
- Which model does `generation`.

## Models

| Job | Model | Notes |
|---|---|---|
| embedding | `baai/bge-m3` | 1024 dimensions, 8,194 token limit, $0.01/M tokens |
| chat | not chosen yet | 21 free options on OpenRouter, plus paid |

## Setup

All local, via `docker-compose.yml` at the repo root:

- Qdrant — `http://localhost:6333`
- Postgres — `localhost:5432`
- pgAdmin — `http://localhost:5050`, for looking at the record manager's table
- An OpenRouter API key in `.env`
- A LangSmith API key in `.env`, plus `LANGSMITH_TRACING=true` and
  `LANGSMITH_PROJECT=01-basic-rag`. Traces appear at https://smith.langchain.com
