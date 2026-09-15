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
- the HTTP API — [designs/api.md](designs/api.md)
- the container — [designs/containerisation.md](designs/containerisation.md)

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

### In Docker

The API also runs as a container. See
[designs/containerisation.md](designs/containerisation.md) for why each decision
went the way it did.

```bash
# from the repo root
docker compose up -d --build api     # build the image and start the api service
docker compose logs -f api           # watch it
docker compose down                  # stop everything, keeping data
```

Then open `http://localhost:8000/docs`.

**The container does not ingest.** It answers from whatever is already in
Qdrant, and `ingest` is still a host command. Run it before the first query on a
fresh Qdrant:

```bash
uv run python projects/01-basic-rag/main.py ingest
```

**The image carries no reranker.** `sentence-transformers` and torch are left
out deliberately, because `RERANKER_MODEL` ships empty. Set it and the container
dies at startup on `No module named 'sentence_transformers'`. See the note in
`.env.example`.

**`QDRANT_URL` is overridden in `docker-compose.yml`**, to `http://qdrant:6333`.
`.env` keeps `localhost:6333`, which is what host-side commands need — a
container's `localhost` is itself, not your machine.

### Checking it worked

Five checks, and the last is the one that matters. A container pointed at an
empty collection passes the first four.

```bash
# 1. it starts and stays up
docker compose ps api

# 2. it is reachable through the published port
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/docs      # 200

# 3. a real query returns the documented shape
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is reciprocal rank fusion?"}' | python3 -m json.tool

# 4. validation still rejects what it should
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' -d '{}'                            # 422
```

**5. The parity check.** In the response from step 3, `chunks` must be
**non-empty and name the source you expect** — for that question,
`data/hybrid-search-fundamentals.pdf`.

This is not a formality. Qdrant does not error on an empty collection: retrieval
returns nothing, the `answerer` truthfully says the context does not contain the
answer, and the response is **200 OK with plausible English**. Every route to
that ends in a `collection_name` mismatch — a setting that reached the container
differently from the host, or a corpus that was never ingested. An empty
`chunks` array is the only visible symptom.

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
