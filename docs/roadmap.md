# Roadmap

Where this is heading, and why. Kept short and rewritten freely — this records
intent, not commitments.

## Where we are

Project 01 answers questions over four documents, is evaluated on LangSmith
against a 25-question benchmark, and runs on AWS ECS behind an ALB. 118 tests,
all merged to `main`.

**The shipped configuration is `TOP_K=8` with the `v1` prompt**, and it answers
every benchmark question correctly: `correct` **1.000**, `grounded` **1.000**,
`evidence_found` **0.880**. Both are the committed defaults and both are set on
the ECS task definition.

**Retrieval is still the open problem**, just a smaller one. Three questions out
of twenty-five never get all the evidence they need, all of them multi-chunk.
Three separate attempts to rank the required chunks higher have failed — see
**The retrieval direction** below.

**What it costs.** 45,656 prompt tokens and $0.00635 per 25 questions, against
22,592 and $0.00195 for the original `TOP_K=4` baseline. Accuracy here was
bought with tokens, not with better ranking.

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

**Reranking was built, measured and switched off** — see the section below and
[`designs/reranking.md`](../projects/01-basic-rag/designs/reranking.md). The code
stays, defaulted off via an empty `RERANKER_MODEL`.

**Prompt selection was built, and `v1` is live.** Prompts are named, live in
`src/prompts.py`, and are chosen by `ANSWERER_PROMPT`. The selected name is
recorded on every experiment, so two prompt runs can be told apart. See
[`designs/answerer-prompt.md`](../projects/01-basic-rag/designs/answerer-prompt.md)
and [`designs/answerer-prompt-v1.md`](../projects/01-basic-rag/designs/answerer-prompt-v1.md).

## The retrieval direction

**Hybrid search is not next, and was never built.** A step 0 probe on 2026-09-10
predicted it would make things worse and the paid run was never justified. See
the section below.

Three interventions have now tried to rank the required chunks higher, and
`evidence_rank_reciprocal` has read about 0.46 every time:

| Intervention | `evidence_rank_reciprocal` |
|---|---|
| `TOP_K` 1 → 8, an eight-fold widening | 0.32 → 0.50 |
| Cross-encoder `reranker` | 0.46 → 0.463 |
| Hybrid RRF fusion (predicted) | 0.463 → 0.450 |

A wider net, a semantic re-scorer and a non-semantic lexical retriever all fail.
Ranking is not the lever.

**Where the failures actually are.** Measured on the `v1` run at `TOP_K=4`,
`evidence_found` by how many chunks a question needs. This table is what
motivated `TOP_K=8`; the section below has the post-change numbers:

| required chunks | questions | `evidence_found` | `evidence_recall` |
|---|---|---|---|
| 1 | 10 | 1.00 | 1.00 |
| 2 | 5 | 0.80 | 0.90 |
| 3 | 6 | 0.50 | 0.72 |
| 4 | 4 | **0.00** | 0.62 |

Single-chunk questions are perfect. Four-chunk questions never succeed. That is
arithmetic before it is relevance: `TOP_K=4` returns four chunks, so a
four-chunk question needs all four slots to be exactly right, and one wrong
chunk scores zero. Each cell is small — the 0.00 is 0 of 4 — so read the trend,
not the individual numbers.

**Neither remaining lever depends on ranking:**

- ~~**`TOP_K=8`.**~~ Done 2026-09-28 and shipped. `evidence_found` 0.680 →
  **0.880**, `correct` 0.960 → **1.000**. See the section below.
- **A larger `CHUNK_SIZE`.** Still untried. Turns four-chunk questions into
  two-chunk ones, attacking the arithmetic rather than the ranking. Needs a
  re-ingest into a new collection, so it is not a one-line experiment. Keep
  `CHUNK_OVERLAP` at 200 or above, or the 200-character golden quotes stop being
  guaranteed to sit inside one chunk.

**Both buy evidence with tokens**, and `TOP_K=8` proved it: +85% prompt tokens
for +5 questions. Better ranking would have been free; nothing has delivered it.

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

## Reranking experiment — 2026-09-10

`CANDIDATE_COUNT=20` fetched, `BAAI/bge-reranker-base` scoring, best `TOP_K=4`
passed on. Same dataset, same collection, same answerer as the TOP_K runs.

| Metric | baseline | reranked | bar | |
|---|---|---|---|---|
| `evidence_found` | 0.680 | 0.720 | ≥ 0.780 | **fail** |
| `correct` | 0.880 | 0.840 | ≥ 0.880 | **fail** |
| `grounded` | 1.000 | 0.960 | 1.000 | **fail** |
| `correct_given_evidence` | 0.941 | 1.000 | — | improved |
| `evidence_rank_reciprocal` | 0.46 | 0.463 | — | unchanged |
| prompt tokens | 22,592 | 23,772 | — | +5% |
| latency P50 | 5.10s | 6.49s | — | +27% |

**A trade, not an absence of effect.** Reranking gained evidence on four
questions the `vector_store` had missed (2, 8, 19, 22) and lost it on three it
had (10, 13, 18). Net one question in twenty-five.

**`evidence_rank_reciprocal` did not move.** That is the same signal that ruled
out a larger `TOP_K`, where it went only 0.32 → 0.50 across an eight-fold
widening. A cross-encoder reading question and chunk together also fails to rank
the required chunks higher — two relevance mechanisms, one blind spot. A
cross-encoder is still semantic, so it inherits `bge-m3`'s weakness rather than
correcting it. Hence hybrid search.

The criteria were fixed before the run and were not revised after it.

A **baseline gate** ran first, reranking off on the new code, and reproduced the
recorded baseline row for row — `evidence_found` 0.680 with the same eight
misses, and 22,592 prompt tokens exactly. That is what makes the +0.04 above
reranking's own effect rather than the refactor's.

| Run | experiment | session |
|---|---|---|
| gate, no reranker | `bge-m3-1000-200-c098116f` | `e41de0eb-df69-427c-a21c-a0d72fc577d9` |
| reranked | `bge-m3-1000-200-487d661a` | `caa4adf5-48af-4e53-886d-7b64c645af0f` |

## Hybrid search — 2026-09-10 — predicted, not run

BM25 alongside vectors, fused with RRF. A **step 0 probe** computed what fusion
would produce from real retrieval output, without calling a model. It predicted
a regression, so the paid evaluation was never justified and `fusion.py` was
never written.

| Metric | baseline | predicted hybrid | bar | |
|---|---|---|---|---|
| `evidence_found` | 0.680 | **0.640** | ≥ 0.780 | fail |
| `evidence_rank_reciprocal` | 0.463 | 0.450 | — | unchanged |

Two questions fixed, three broken.

**Why it regresses.** The two top-20 lists overlapped on every question (mean
11.5, min 6), so only `chunk`s both retrievers agreed on reached the top 4. A
`chunk` at vector rank 1 but absent from BM25's list scores `1/61 = 0.0164`,
below every consensus `chunk` at `2/80 = 0.0250`. RRF punishes evidence only one
retriever finds — whichever one that is. On this corpus vector search is the one
with more to lose.

Full reasoning and the per-question tables:
[`designs/hybrid-search.md`](../projects/01-basic-rag/designs/hybrid-search.md).

## Answerer prompt selection — 2026-09-26

`ANSWERER_PROMPT` now names which of the `answerer`'s prompts to run, and the
name is recorded on the experiment. `baseline` is the prompt every row above was
measured with, and its text is frozen. See
[`designs/answerer-prompt.md`](../projects/01-basic-rag/designs/answerer-prompt.md).

A sanity `evaluation_run` at the shipped configuration confirmed the plumbing did
not change the baseline. **Prompt tokens came back at exactly 22,592**, matching
the `TOP_K=4` row — the rendered prompt is byte-identical, which is the only part
of this that can be checked deterministically. Metadata carried
`answerer_prompt: baseline`.

| Metric | recorded | sanity run | |
|---|---|---|---|
| `evidence_found` | 0.680 | 0.680 | exact |
| `evidence_recall` | 0.853 | 0.853 | exact |
| `evidence_rank_reciprocal` | 0.46 | 0.463 | exact |
| `grounded` | 1.000 | 1.000 | exact |
| `correct` | 0.880 | 0.840 | −1 question |
| `correct_given_evidence` | 0.941 | 1.000 | +1 of 17 |

Every deterministic number is identical. The two that moved are both judged, and
they moved in opposite directions: the evidence-found set went 16/17 correct to
17/17, the evidence-missing set 6/8 to 4/8. Net one question. `temperature=0`
through OpenRouter routes across ~30 providers and is not bit-reproducible, so
row-for-row reproduction was deliberately not a pass condition.

Experiment `bge-m3-1000-200-b9037d76`, session
`f233f7b2-7cce-4b12-9996-7b60e817efe4`. Cost $0.00195.

**These numbers were counted from the API, not read off the UI** — see the loose
end below. Worth knowing when doing it again: `openrouter_cost` sits on the
`rag_query` run, which is a child of the root `evaluate()` creates, so summing
root runs alone reports zero.

**`v1` does not exist yet.** The registry ships with `baseline` only. Prompt work
comes after the eight `evidence_found` misses have been read.

## v1 answerer prompt — 2026-09-26

The first prompt experiment. Retrieval frozen at `TOP_K=4`, vector search, no
reranker; only the prompt changed. `v1` adds a role, a goal, a procedure for
partial evidence, plain language and bullet structure, keeping both of
`baseline`'s evidence rules verbatim.

| Metric | baseline | v1 | |
|---|---|---|---|
| `correct` | 0.840 | **0.960** | +3 questions |
| `grounded` | 1.000 | 1.000 | held |
| `answered_blind` | 0.000 | 0.000 | held |
| `correct_given_evidence` | 1.000 | 1.000 | held |
| `evidence_found` | 0.680 | 0.680 | identical |
| `evidence_recall` | 0.853 | 0.853 | identical |
| `evidence_rank_reciprocal` | 0.463 | 0.463 | identical |
| prompt tokens | 22,592 | 24,669 | +9% |
| completion tokens | 3,429 | 7,741 | **+126%** |
| latency P50 | 4.00s | **10.62s** | +166% |
| cost | $0.00195 | $0.00366 | +88% |
| answers with bullets | 9/25 | 25/25 | |
| answers citing `[n]` | 0/25 | 8/25 | |

All three retrieval metrics are identical, which is what proves the change was
generation-only.

**What moved it.** Three questions flipped from flat refusals to structured
partial answers. `baseline` said "I cannot answer the question about how
LangGraph can be used to design an AI assistant for loan officers"; `v1` said "I
can only answer part of your question. Here is what the documents cover and what
they do not". The judge rules the first `declined`, which scores 0, and the
second `correct`. The partial-evidence procedure is what did it.

**It was not predicted.** The baseline analysis read `correct_given_evidence`
1.000 as proof that generation had no headroom left, and said so repeatedly. That
metric only covers the 17 questions with complete evidence; the eight with
partial evidence were never in its denominator, and that is exactly where the
headroom was.

**The costs are real.** 2.7x latency and 1.9x cost for +3 questions. Five
techniques landed in one version deliberately, so the honest attribution is "v1
did this", not "the role did this".

**Citations moved without being asked for**, 0/25 to 8/25, almost certainly from
the goal line's "in a form they can check against the source documents". A future
citation experiment must be read against 8/25, not 0.

| Run | experiment | session |
|---|---|---|
| baseline, on current code | `bge-m3-1000-200-b9037d76` | `f233f7b2-7cce-4b12-9996-7b60e817efe4` |
| v1 | `bge-m3-1000-200-b71093db` | `f72923af-7c61-4977-a7b7-f3b6e5dfa701` |

**`v1` is live in production** on task definition `basic-rag-api:11`, deployed
before being benchmarked, deliberately. `baseline` remains
`DEFAULT_ANSWERER_PROMPT`, so local runs and the benchmark use `baseline` unless
`ANSWERER_PROMPT` says otherwise.

**Production is not traced.** The task definition carries no `LANGSMITH_API_KEY`
or `LANGSMITH_TRACING`, so `@traceable` is inert there and `run_id` comes back
None. Every number in this file was measured locally.

## TOP_K=8 — 2026-09-28 — shipped

`TOP_K` 4 → 8 with the `v1` prompt. Nothing else changed: same collection, same
`embedding_model`, no `reranker`, same dataset, same judge. No re-ingest was
needed — `TOP_K` is not part of the collection name.

| Metric | `TOP_K=4` | `TOP_K=8` | |
|---|---|---|---|
| `evidence_found` | 0.680 | **0.880** | 17 → 22 questions |
| `evidence_recall` | 0.853 | 0.953 | |
| `evidence_rank_reciprocal` | 0.463 | 0.498 | barely moved, as ever |
| `correct` | 0.960 | **1.000** | 25 of 25 |
| `grounded` | 1.000 | 1.000 | held |
| `answered_blind` | 0.000 | 0.000 | held |
| `correct_given_evidence` | 1.000 | 1.000 | now over 22 questions, not 17 |
| prompt tokens | 24,669 | 45,656 | +85% |
| completion tokens | 7,741 | 8,750 | +13% |
| cost | $0.00366 | $0.00635 | +73% |
| latency P50 | 10.62s | **7.68s** | −28% |

**Every question is answered correctly**, including the three that still lack
complete evidence. `v1`'s partial-evidence procedure answers the covered part
and says what is missing, and the judge rules that correct. The prompt work and
the retrieval work compound: neither reached 1.000 alone.

**Latency fell, which was not predicted.** The prompt grew 85% and answers got
*faster*. The likely cause is less hedging — with more evidence the model spends
fewer tokens explaining what it could not cover, and completion tokens rose only
13% while prompt tokens rose 85%. Output dominates generation time. Treat as
provisional until it reproduces; one run cannot separate this from OpenRouter
routing variance.

**The three questions still missing evidence**, all multi-chunk:

| needs | `evidence_recall` | question |
|---|---|---|
| 3 quotes | 0.67 | building a stateful agent workflow in LangGraph |
| 3 quotes | 0.67 | LangGraph for a loan-officer assistant |
| 4 quotes | 0.50 | Reflexion-based RAG pipeline |

**A worked example of why it helped.** On the Adaptive RAG question, three of
four required quotes sat at ranks 1, 3 and 4 — and the fourth at **rank 5**, one
position outside the old cut. `TOP_K=8` reached it and the question went
`evidence_found` 0 → 1. That was predicted from the rankings before the run, and
it is the whole mechanism: the chunks were always there, just below the line.

**On the 90% target.** 0.880 is one question short of 0.90, and on 25 examples
one question is 4 points — well inside the noise that moved `correct` by a whole
question between two runs of an identical prompt. Certifying 90% needs a larger
benchmark, not a better number.

| Run | experiment | session |
|---|---|---|
| v1 at `TOP_K=4` | `bge-m3-1000-200-b71093db` | `f72923af-7c61-4977-a7b7-f3b6e5dfa701` |
| v1 at `TOP_K=8` | `bge-m3-1000-200-46660a3c` | `666e29ee-5adc-40c6-a50a-1338ce2ebec8` |

Shipped the same day: task definition `basic-rag-api:13`, and the committed
defaults in `config.py` moved to match, so a fresh clone runs what production
runs.

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
- **`evaluate` prints no scores.** `main.py:246` does `print(f"\n{results}")`, and
  the LangSmith SDK's `ExperimentResults` renders as `<ExperimentResults ...>` —
  the run finishes and the terminal says nothing about how it went. Every number
  in this file was therefore read off the LangSmith UI, whose column headers gave
  wrong aggregates on three separate occasions, each time on a just-finished run
  (see the note under the TOP_K table). Printing the feedback aggregates locally
  would remove that whole class of misreading. A small fix worth more than it
  costs.
- **Qdrant holds ~300 stray collections.** Names like `4c11638c4776-1000-200`,
  left behind by test fixtures that create a collection and never drop it.
  Harmless — `bge-m3-1000-200` is unaffected — but it makes the collection
  list unreadable, which is exactly where you look when a container answers
  200 from the wrong place. Found while verifying the container.
- **The corpus sources were never written down.** The manifest can verify a
  corpus but not rebuild one, so a fresh clone still needs the four files handed
  to it. Closing this means finding where each came from; `data/README.md` has
  the table waiting.
- ~~**Generation is not the bottleneck.**~~ Half right, and the wrong half cost
  time. `correct_given_evidence` 1.000 only covers the questions where every
  required chunk was retrieved. It said nothing about the eight where evidence
  was partial, and that is where `v1` found three questions by answering the
  covered part instead of refusing outright. Retrieval is still the larger
  problem; generation was not finished.

## Ideas backlog

- ~~**Hybrid search.**~~ Dropped 2026-09-10. Step 0 predicted a regression; see
  the hybrid search section above.
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
| 2026-09-10 | Built reranking, TDD, twelve tests. Baseline gate reproduced 0.680 exactly, so the refactor is inert. Reranked run: `evidence_found` 0.720 against a bar of 0.780, `correct` 0.840 against 0.880. Switched off; hybrid search is next. |
| 2026-09-14 | HTTP API designed and built: `POST /query`, everything expensive constructed once in `asgi.py`, one error shape with a `request_id`. `src/` unchanged. |
| 2026-09-15 | Containerised the API in a `grill-me` session. Single-stage image from `uv.lock`, non-root, API only — no `main.py`, no corpus, no reranker. Added as the `api` Compose service, reaching Qdrant by name. Verified manually: five checks, and host and container retrieve the same four chunks for the same question. |
