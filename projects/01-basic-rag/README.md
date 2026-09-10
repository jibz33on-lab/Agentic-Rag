# 01 — Basic RAG with LangChain

A plain RAG system built with LangChain, used directly — no wrapper layer of our
own.

This is the first half of a comparison. Project 02 will build the same thing with
LlamaIndex, in parallel rather than as a swap, so the two can be judged on what
each is actually like to use.

Plain RAG — no agents, no evaluation yet.

## Designs

- skeleton — [designs/skeleton.md](designs/skeleton.md)
- evaluation — [designs/evaluation.md](designs/evaluation.md)
- reranking — [designs/reranking.md](designs/reranking.md)
- hybrid search — [designs/hybrid-search.md](designs/hybrid-search.md)

## Investigations

- streaming latency — [investigations/streaming-latency.md](investigations/streaming-latency.md)
- trace usage and cost — [investigations/trace-usage-and-cost.md](investigations/trace-usage-and-cost.md)

## Running it

Start the services and fill in `.env` first (see the repo root README), then run
from the repo root:

```bash
# read data/, split, embed, store. Re-run whenever you add or change a file.
uv run python projects/01-basic-rag/main.py ingest

# ask questions
uv run python projects/01-basic-rag/main.py ask
```

`ingest` is safe to re-run: unchanged files are skipped, edited files replace
their old chunks. Change `CHUNK_SIZE` or `EMBEDDING_MODEL` in `.env` and it
indexes into a different collection, leaving the old one intact for comparison.

Every answer prints the chunks it came from. When an answer is wrong, that tells
you whether retrieval found the wrong text or the model misread the right text.

Traces appear in LangSmith under the project named by `LANGSMITH_PROJECT`.

## The parts

| File | What it does |
|---|---|
| `config.py` | reads and checks settings, derives the collection name |
| `document_loader.py` | PDFs and docx from a folder, skipping what will not read |
| `text_splitter.py` | documents into overlapping chunks |
| `vector_store.py` | opens the Qdrant collection for these settings |
| `indexing.py` | embeds and stores, skipping what is already there |
| `retrieval.py` | question to nearest chunks |
| `answerer.py` | question plus chunks to an answer |
| `rag_query.py` | question to answer, retrieval and generation as one traced unit |
| `main.py` | the terminal command |

## What was learned

- `index()` hashes file contents, not your settings. Change the chunk size and
  every file looks unchanged, so the new setting silently never reaches the
  store. Hence the collection name being built from the settings.
- `cleanup="incremental"` cleans up after every batch of 100, so a file whose
  chunks straddle a batch boundary gets its tail deleted and re-added on every
  run. `scoped_full` cleans up once at the end instead.
- Qdrant point IDs must be an integer or a UUID, so LangChain's suggestion to
  move off SHA-1 hashing cannot be taken here.
- `dotenv_values()` returns a dict and does not touch `os.environ`. LangSmith
  reads `os.environ`, so tracing stays silently off without `load_dotenv()`.
- `SQLRecordManager` lives in a private module of a sunset package, and nothing
  maintained replaces it. The most fragile import in the project.
- The model reasons before answering by a provider default nobody set, and
  LangChain drops the `reasoning` field, so an 18-second wait arrives as chunks
  that look empty. See the latency investigation. Reading the raw HTTP stream
  was the only way to see it.
