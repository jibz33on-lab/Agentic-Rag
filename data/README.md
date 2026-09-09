# The corpus

Four third-party documents. Project 01 ingests them, and
`01-basic-rag-benchmark` was written from the chunks they produce.

**The files are not in this repo.** They are third-party material, so this
folder commits what it can honestly commit: their names, their hashes, and a
check that says loudly when what you have is not what the recorded numbers were
measured on.

| File | Type | Size | Pages |
|---|---|---|---|
| `system-design-fundamentals.pdf` | PDF | 962 KB | 20 |
| `complete-langgraph-tutorial-from-beginner-to-advanced.pdf` | PDF | 820 KB | 15 |
| `hybrid-search-fundamentals.pdf` | PDF | 547 KB | 21 |
| `agentic-systems-mental-model.docx` | docx | 22 KB | — |

Hashes are in [`corpus.sha256`](corpus.sha256).

> **Sources are unrecorded.** These were collected before this manifest existed
> and their origins were not written down. Until they are, a clone cannot
> rebuild the corpus — only verify one it was given. If you know where a file
> came from, add it to the table.

## Why this matters more than it looks

`Config.collection_name` is `bge-m3-1000-200` — derived from the embedding model
and the chunking settings, and **not** from the corpus. Change a document and
re-ingest, and the new chunks land in an identically named collection. Nothing
errors. The benchmark's quotes are verbatim spans of the old chunks, so they
stop matching, `evidence_found` drops, and it reads as retrieval getting worse.

That is the failure this folder exists to make visible.

## Checking it

```
uv run python projects/01-basic-rag/main.py verify-corpus
```

Prints one line per file — `ok`, `changed`, `missing` or `untracked` — and exits
non-zero unless every file matches. `untracked` counts as a failure: an extra
document changes the chunks as surely as an edited one.

Without this repo's code, `shasum -a 256 -c data/corpus.sha256` does the same
for the first three cases.
