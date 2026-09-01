# Design: the skeleton

Agreed in a design session on 2026-09-01.

## Problem

We want to understand how a RAG system fits together. So we build the thinnest
possible version of every part and wire it end to end.

The goal is to *see* the whole shape working. It is not to make any single part
good. That comes after, one component at a time.

## Scope

**In**

- The seven components listed below
- Real PDF and docx files, from the start
- A terminal command
- Qdrant for `chunk`s, Postgres for the `ingestion_ledger`
- OpenRouter for both the LLM and the embedding model

**Out**

- The `agent`. This is plain RAG. Agentic RAG comes later.
- Evaluation — `golden_example`, `evaluation_run`, `trace`
- Any frontend
- Fallback providers

## The seven components

| # | Component | What it does |
|---|-----------|--------------|
| 1 | `document_loader` | reads one PDF or docx → a `document` |
| 2 | `chunking_strategy` | cuts a `document` into `chunk`s |
| 3 | `embedding_strategy` | turns a `chunk` into numbers |
| 4 | `chunk_store` | holds `chunk`s, finds similar ones, deletes by `document` |
| 5 | `ingestion_ledger` | remembers which files are already done |
| 6 | `retrieval_strategy` | query → ranked `chunk`s + `retrieval_signals` |
| 7 | `answerer` | query + `chunk`s → an answer |

Components 1–5 are run by the `ingestion_job`.

## How ingestion works

For each file in the folder:

1. Hash the file. Look it up in the `ingestion_ledger`.
2. Decide what to do:
   - not in the ledger → **new**, ingest it
   - same hash, same settings → **unchanged**, skip it
   - different hash, or different settings → **stale**, ingest it again
3. To ingest: delete any existing `chunk`s for that `document` first, then load,
   split, embed and store.
4. If the file cannot be read, record it as skipped and move to the next one.
   One bad file never stops the run.
5. At the end, report what was written and what was skipped.

Settings means the chunk size and the embedding model. They are stored in the
ledger next to the hash. Change either one and everything is re-ingested — which
is what keeps comparisons honest.

## How a query works

1. You type a question into the terminal.
2. The `retrieval_strategy` finds the closest `chunk`s.
3. The `answerer` turns the question plus those `chunk`s into an answer.
4. The terminal prints the answer **and** the `chunk`s it used.

Printing the `chunk`s is deliberate. If the answer is wrong, you can see whether
retrieval found the wrong text, or found the right text and the `answerer` misread
it. Without that you cannot tell which of the seven components failed.

## Decisions, and why

| Decision | Why |
|---|---|
| Real PDFs and docx from day one | Accepted that ingestion gets deep before anything else exists |
| A bad file is skipped, not fatal | The run can be left alone; one broken PDF does not waste the other 19 |
| Re-runs are incremental | Re-embedding everything each time is slow and costs money |
| Changed files are detected by content, not name | An edited file under the same name would otherwise be invisible |
| Old `chunk`s are deleted before new ones are written | Otherwise an edit leaves both versions in the store |
| Settings changes also trigger re-ingestion | Otherwise you compare new settings against chunks built with the old ones, and never notice |
| Two databases | Qdrant for vectors, Postgres for the ledger |
| No fallback provider | For embeddings it is a correctness risk, not just extra work — two models produce vectors that cannot be compared |

## Accepted trades

- **Ingestion is much deeper than everything else.** Real file parsing, skip-and-
  report and incremental state all sit in one component while retrieval and the
  `answerer` stay thin. Chosen knowingly.
- **No single transaction across the two databases.** Instead, re-ingesting always
  deletes first, so a run that dies halfway is cleaned up by the next one.
- **`chunk_store` and `ingestion_ledger` stay separate components**, even though
  both are storage. Merging them would weld us to this pair of databases.

## Open questions

- Chunk size and how many `chunk`s to retrieve. Settings to tune, not decisions to
  make cold.
- What exactly the `ingestion_ledger` table holds beyond file, hash and settings.
- Whether to warn before a settings change re-ingests a large corpus. Not needed
  while the corpus is small.

## Setup needed before code

Not design decisions, just things to install. All run locally via
`docker-compose.yml` at the repo root:

- Qdrant — `http://localhost:6333`
- Postgres — `localhost:5432`
- pgAdmin — `http://localhost:5050`, for looking at the ledger table
- An OpenRouter API key in `.env`

Only OpenRouter needs an account. The rest are open source containers.
