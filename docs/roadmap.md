# Roadmap

Where this is heading, and why. Kept short and rewritten freely — this records
intent, not commitments.

## Where we are

Project 01 has evaluation, built on LangSmith. Branch
`feat/evaluation-foundations`, four commits, 64 tests, not yet pushed or merged.

**Read first:** [`projects/01-basic-rag/designs/evaluation.md`](../projects/01-basic-rag/designs/evaluation.md)
for the architecture and the decisions behind it, and
[`investigations/trace-usage-and-cost.md`](../projects/01-basic-rag/investigations/trace-usage-and-cost.md)
for what the probe found. The commit messages carry their own reasoning.

**LangSmith owns the evaluation.** Datasets, experiments, traces, tokens,
latency, score aggregation, comparison. Ours is only what it cannot supply:
corpus-specific evidence matching, the judge, generating the examples, and an
adapter that recovers OpenRouter's cost after LangChain discards it. An earlier
draft specified seven modules of our own; most of it duplicated the product and
was deleted.

**Two datasets.** `01-basic-rag-benchmark` is live — 25 examples, 10
single-chunk plus 5/6/4 needing two, three and four chunks.
`01-basic-rag-golden` (21) is superseded; its questions were all written from a
single chunk, so retrieval found them at rank 1 every time and every metric sat
at 1.000. A benchmark with no headroom cannot detect an improvement.

**Next: reranking**, inside `retrieval.py`. Retrieve wide, rerank with a
cross-encoder, keep the top few. It needs no new index and no ingest change, and
`rag_query`, the evaluators and the dataset all stay as they are — so the result
is directly comparable to the four TOP_K experiments below. Hybrid search is the
other candidate and is the larger change, because a keyword index reaches back
into ingest.

## TOP_K experiments — 2026-09-08

All four against `01-basic-rag-benchmark`, changing only `TOP_K`.

| TOP_K | evidence_found | evidence_recall | correct | grounded | prompt tokens | cost |
|---|---|---|---|---|---|---|
| 1 | 0.320 | 0.507 | 0.640 | 1.000 | 7,411 | $0.00128 |
| 2 | 0.520 | 0.750 | 0.800 | 1.000 | 12,250 | $0.00193 |
| 4 | 0.680 | 0.853 | **0.880** | 1.000 | 22,592 | $0.00291 |
| 8 | 0.880 | 0.953 | 0.880 | 0.960 | 43,581 | $0.00460 |
| 20 | 0.960 | 0.990 | 0.960 | 0.960 | 104,635 | — |

`TOP_K` stays at **4** for the shipped configuration. Correctness peaks there
among 1/2/4/8, and `TOP_K=8` costs 58% more for the same answers.

**The `TOP_K=20` row is a ceiling measurement, not a candidate setting.** It was
run on 2026-09-09 as step 0 of the reranking design — see
[`designs/reranking.md`](../projects/01-basic-rag/designs/reranking.md). A
`reranker` can only reorder what the `vector_store` returned, so
`evidence_found` at 20 `candidate`s is the hard ceiling on what re-ranking can
achieve. It is **0.960**: 24 of 25 questions have every required `chunk` inside
the top 20, and re-ranking's whole job is pulling them into the top 4. Only one
question is out of reach at this `CANDIDATE_COUNT` — a four-`chunk` question
that reaches `evidence_recall` 0.75.

Two results there were not predicted. `correct` at 20 is **0.960**, higher than
at 4 or 8 — twenty `chunk`s did not distract the `answerer`, they helped it. The
distraction effect is real but small: exactly one question had its evidence at
rank 1 and still came back wrong and ungrounded, against several that were fixed.
So re-ranking's target is no longer "beat 0.880"; it is **reach TOP_K=20's
accuracy at TOP_K=4's prompt cost**, which is 104,635 tokens against 22,592, a
factor of 4.6.

The success criteria in the design were fixed before this run and were
deliberately **not** revised after seeing it. 0.880 stays the baseline to beat;
0.960 is the reference ceiling to be judged against.

`evidence_rank_reciprocal` at 20 is ≈0.50 by hand count. Cost is unrecorded: the
LangSmith cost column is empty for OpenRouter models by design, and the earlier
rows' figures came from `openrouter_cost` in the trace metadata, which was not
read for this run.

> **Reading these numbers from LangSmith.** The `TOP_K=20` run's column headers
> reported `1.00 AVG` for `correct`, `evidence_found`, `evidence_recall` and
> `grounded` while those same columns visibly contained `0.00` cells — stale
> aggregates on a just-finished experiment. Every figure in the row above was
> counted by hand from all 25 rows instead. The `TOP_K=4` run was re-checked the
> same way and its headers are accurate (`correct` 0.88, `evidence_found` 0.68,
> `evidence_recall` 0.85, and `grounded` genuinely 1.000 with no zero in any of
> its 25 rows), so the earlier four rows are trustworthy. Check a header against
> its rows before recording it.

**Why a bigger `TOP_K` is the wrong lever.** `evidence_rank_reciprocal` moved
only 0.32 → 0.50 across an eight-fold widening. The required chunks are not
being ranked higher; they are being caught by a wider net. Hence reranking.

Experiments, under organisation `418b2cd4-5deb-4a57-8883-6818ec404713`, dataset
`e1113dfe-35b1-4080-b989-e6b7e3a3f30e`:

| TOP_K | experiment | session |
|---|---|---|
| 1 | `bge-m3-1000-200-45e73f1f` | `3687c292-e1fb-4561-9317-e223318f5fde` |
| 2 | `bge-m3-1000-200-9abbcad2` | `914d086d-1c9f-4281-a63e-3a15bf0d2be6` |
| 4 | `bge-m3-1000-200-3fa1e704` | `4d2aedeb-99c6-43df-826f-9810f539ee69` |
| 8 | `bge-m3-1000-200-8a38809d` | `9abbc6b1-100b-4e9c-8a84-d4c1d1ec527b` |
| 20 | `bge-m3-1000-200-c849dc0d` | `fd809e8d-4022-46cb-a9ec-601b37e7de23` |

URL: `https://smith.langchain.com/o/<org>/datasets/<dataset>/compare?selectedSessions=<session>`

## Loose ends

- ~~**Committed defaults still name the old dataset.**~~ Fixed 2026-09-09.
  `config.py:14` and `.env.example:48` now say `01-basic-rag-benchmark`, and
  `test_config.py:120` — which the original note missed — asserts it.
- ~~**`data/` is untracked and not ignored.**~~ Fixed 2026-09-09. The documents
  are third-party, so they stay out of a public repo; `data/README.md` and
  `data/corpus.sha256` describe them instead, and
  `main.py verify-corpus` checks a folder against the manifest, exiting
  non-zero on a changed, missing or extra file. The old `.gitignore` rule was
  `data/raw/`, which matched nothing.
- **The corpus sources were never written down.** The manifest can verify a
  corpus but not rebuild one, so a fresh clone still needs the four files handed
  to it. Closing this means finding where each came from; `data/README.md` has
  the table waiting.
- **Generation is not the bottleneck.** `correct_given_evidence` was 1.000 at
  `TOP_K` 1, 2 and 4 — whenever retrieval delivered every required chunk, the
  answer was right. Work retrieval, not the prompt.

## Ideas backlog

- **Hybrid search.** BM25 alongside vectors, fused with RRF. Several required
  quotes carry distinctive tokens — `EnsembleRetriever`, `RRF`, `429` — that
  keyword search finds instantly and embeddings blur. Needs a keyword index, so
  it touches ingest.
- **Query decomposition.** The multi-chunk questions are effectively multi-hop.
  Even at `TOP_K=8`, three-chunk questions only reach 0.667 `evidence_found`.
- **Refusal on unanswerable questions.** Needs adversarial examples that
  sample-and-generate cannot produce. Its own design session.
- **The same thing in LlamaIndex.** Project 02, built in parallel rather than
  swapped in, so each framework is written in its own natural style. The
  benchmark and evaluators transfer; only the target changes.
- **Agentic RAG.** Add the `agent`, `tool_call`s and a `trace` on top of 01.
- **Multi-agent work in a separate repo**, plugged into this one to solve a real
  business problem. Early and unconfirmed.
- **Frontend and backend repos** wrapping this later. The reason project 01 keeps
  its logic in components rather than inside the terminal command.

## Open questions

- Which vector store to standardise on. Project 01 uses Qdrant; whatever is
  chosen has to delete by `document`.
- Whether the benchmark should carry deliberately hard single-chunk questions.
  All ten currently score 1.000 at every `TOP_K` above 1, so that population no
  longer discriminates.
- Whether `evidence_rank_reciprocal` should be normalised by chunk count. A
  three-chunk question caps at 0.333 and a four-chunk at 0.25, so the dataset
  mean is not comparable across datasets with different mixes. Group by
  `chunk_count` in the UI for now.

## Log

| Date | Note |
|------|------|
| 2026-09-01 | Repo created: monorepo layout, uv + ruff + pytest, CI on push and PR. |
| 2026-09-01 | Project 01 designed: a plain RAG skeleton, seven thin components end to end. |
| 2026-09-02 | Switched 01 to LangChain used directly. Purpose is now comparing frameworks, so vocabulary moved to LangChain's names. |
| 2026-09-07 | Evaluation designed and built. Probe found OpenRouter's cost is discarded by LangChain and recoverable; `flush()` does not make a trace readable. |
| 2026-09-08 | Rebuilt around LangSmith as the evaluation workspace; deleted our runner, metrics reader and aggregation. Added multi-chunk examples and the 25-example benchmark. Ran TOP_K 1/2/4/8. |
| 2026-09-09 | Closed the two loose ends: defaults point at the benchmark, and the corpus is described by a committed manifest that `verify-corpus` checks. |
| 2026-09-09 | Designed reranking in a grill-me session. Step 0 ceiling run at `TOP_K=20`: `evidence_found` 0.960, so the gate passes and the work proceeds. |
