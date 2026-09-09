# Design: reranking

Designed 2026-09-09, in a `grill-me` session.

## Problem

`TOP_K` was measured at 1, 2, 4 and 8 and settled at 4. Widening it did not fix
retrieval — it only cast a wider net. `evidence_rank_reciprocal` moved 0.32 to
0.50 across an eight-fold widening, so the required `chunk`s were not being
ranked higher, merely caught. At `TOP_K=4` the `answerer` receives every
required `chunk` for only 17 of 25 `golden_example`s.

The `embedding_model` encodes the query and each `chunk` separately and compares
two vectors. That is what makes it cheap enough to run over the whole
collection, and it is also why it is imprecise. A `reranker` reads the query and
the `chunk` together, which is far more accurate and far too expensive to run
over everything — but affordable over twenty `candidate`s.

## Definition of done

Not "re-ranking is implemented". This:

> Re-ranking is kept only if it improves retrieval on the benchmark by a margin
> larger than the benchmark can produce by chance.

Concretely, against `01-basic-rag-benchmark`, `TOP_K=4`, collection
`bge-m3-1000-200`:

| Criterion | Bar |
|---|---|
| `evidence_found` | ≥ 0.780 (a gain of at least 0.10 over 0.680) |
| `correct` | ≥ 0.880 — must not regress |
| `grounded` | 1.000 — must hold |

A gain under 0.10 does not count as evidence for keeping the `reranker`. The
benchmark is 25 examples, so one example is four percentage points; a smaller
move is one or two questions changing their minds, not a result. Detecting
effects below that needs more `golden_example`s, not a bolder reading of these.

### The baseline gate

Before any re-ranked number is trusted, the new code must run with re-ranking
**off** and reproduce `evidence_found` 0.680 and `correct` 0.880 exactly.

The baseline was measured by code that had no `reranker` in it. Without this
gate, a re-ranked result is being compared against a different codebase, and any
difference is attributable to two changes rather than one. This is the reason
the `reranker` is optional at all.

### The prediction, recorded before the run

At `TOP_K=4`: `evidence_found` 0.680 is 17 of 25, `correct` 0.880 is 22 of 25,
and `correct_given_evidence` is 1.000 — so all 17 examples with complete
evidence were answered correctly, and 5 of the remaining 8 were answered
correctly anyway on partial evidence. A 62.5% hit rate without full evidence.

That gives `correct ≈ E + (1 − E) × 0.625`:

| If `evidence_found` reaches | predicted `correct` |
|---|---|
| 0.80 | ~0.925 |
| 0.85 | ~0.944 |
| 0.88 | ~0.955 |

The sharp version. `TOP_K=8` reached `evidence_found` 0.880 but `correct` of
only 0.880, and it was the sole setting where `grounded` and
`correct_given_evidence` fell below 1.000 — more context distracted the
`answerer` rather than informing it. Re-ranking should reach a comparable
evidence level at `TOP_K=4`, without that distraction, and so land near 0.95
while costing what `TOP_K=4` costs.

If evidence rises to 0.88 and `correct` still comes back at 0.880, the
distraction explanation was wrong and something more interesting is happening.
Written down beforehand so it is a prediction rather than a story told
afterwards.

## Step 0: measure the ceiling first

**Before any code is written**, run one `evaluation_run` at `TOP_K=20` with no
`reranker`, on the existing code.

A `reranker` can only reorder what the `vector_store` returned. `evidence_found`
at 20 `candidate`s is therefore the hard ceiling on this entire feature —
flawless re-ranking cannot exceed it. That number is unknown, and it costs about
a cent to learn:

| Outcome | Reading |
|---|---|
| ~0.95+ | Ample headroom. Re-ranking is the right lever, 20 is a good count. |
| ~0.90 | Modest headroom. Perfect re-ranking caps `correct` near 0.90. |
| barely above 0.880 | The required `chunk`s are not in the `candidate` set at all. No `reranker` fixes that — this is a hybrid-search result, and the work redirects. |

The third outcome is why this runs first. **This is a gate, not a formality**:
if the ceiling is low, the correct outcome of this design is to defer re-ranking
and do hybrid search instead.

### Result, 2026-09-09 — the gate passes

Experiment `bge-m3-1000-200-c849dc0d`, session
`fd809e8d-4022-46cb-a9ec-601b37e7de23`.

| Metric | TOP_K=20 | TOP_K=4 baseline |
|---|---|---|
| `evidence_found` | **0.960** | 0.680 |
| `evidence_recall` | 0.990 | 0.853 |
| `correct` | **0.960** | 0.880 |
| `correct_given_evidence` | 0.958 | 1.000 |
| `grounded` | 0.960 | 1.000 |
| `evidence_rank_reciprocal` | ≈0.50 | 0.46 |
| prompt tokens | 104,635 | 22,592 |

**The ceiling is 0.960**, the first of the three outcomes above. Twenty-four of
25 questions have every required `chunk` inside the top 20, so re-ranking's task
is purely to lift them into the top 4. One question is unreachable at
`CANDIDATE_COUNT=20` — a four-`chunk` question that gets to `evidence_recall`
0.75. Re-ranking proceeds.

**Two things the design did not predict.**

`correct` at 20 is 0.960 — *higher* than at 4 or 8. Twenty `chunk`s did not
distract the `answerer`. The distraction effect is real but small: one question
had its evidence at rank 1 and still came back wrong and ungrounded, which is
what pulls `correct_given_evidence` and `grounded` to 0.960. Several other
questions were fixed. So the prediction that a wide `TOP_K` degrades answers was
too strong; it degrades a little and helps more.

That sharpens the target rather than weakening it. Brute force already reaches
0.960, at 4.6x the prompt tokens. **Re-ranking's job is to reach TOP_K=20's
accuracy at TOP_K=4's prompt cost.**

The formula predicted `correct ≈ 0.985` at `evidence_found` 0.960; the actual is
0.960. Close, and low rather than high, because the 62.5% partial-evidence rate
does not account for a question that had complete evidence and was still
answered wrongly.

**The success criteria above were not revised after this run.** 0.880 remains the
bar to beat and 0.960 is recorded as the reference ceiling to be judged against.
Moving a bar after seeing the data is how an experiment stops being one.

**A note on reading LangSmith.** This run's column headers showed `1.00 AVG` for
`correct`, `evidence_found`, `evidence_recall` and `grounded` while those columns
visibly contained `0.00` cells — stale aggregates on a just-finished experiment.
Every figure above was counted by hand from all 25 rows. The `TOP_K=4` run was
re-verified the same way and its headers are accurate, including `grounded`
1.000 with no zero in any row, so the recorded baseline stands.

## Scope

**In.**

- A `reranker` component: `BAAI/bge-reranker-base`, a local cross-encoder run
  through LangChain's `HuggingFaceCrossEncoder` and `CrossEncoderReranker`.
- Fetching `CANDIDATE_COUNT` `candidate`s and cutting to `TOP_K` after scoring.
- Two new settings, `RERANKER_MODEL` and `CANDIDATE_COUNT`, both recorded in
  `evaluation_run` metadata along with whether re-ranking was on.
- Failing at startup when `RERANKER_MODEL` is set but unusable.
- A warning at build time when `CHUNK_SIZE` approaches the model's token limit.

**Out**, deliberately.

- **`retrieval_signals`.** This feature creates a real candidate count for the
  first time, and the `reranker`'s scores would feed the weak-match signal — but
  implementing it means `retrieve()` returning something other than
  `list[Document]`, which ripples into `rag_query`, the evaluation target and
  the evaluators. That is a second and larger interface change in the same
  commit. `DOMAIN_TERMS.md` says the signals exist for the `agent` to read, and
  the `agent` is project 02+. A channel with no reader is speculative
  generality. Deferred, at the honest price of touching `retrieval.py` twice.
- **Re-tuning `TOP_K`.** Stays 4, so the comparison against the recorded
  experiments is apples to apples. If re-ranking makes fewer `chunk`s as good,
  that is a separate cost investigation.
- **Hybrid search and query decomposition.** Separate backlog items. This
  experiment is partly what tells you whether they matter more.
- **Changing the `golden_example` set, the prompt or the `answerer`.** An
  `evaluation_run` is meaningless unless the set is held constant.
- **User-facing re-rank scores in `ask`, and model caching or warming.**

## Design

```
question
  ↓  embed                     bge-m3, unchanged
  ↓  vector_store search       CANDIDATE_COUNT (20) candidates
  ↓  reranker                  scores 20 (query, chunk) pairs jointly
  ↓  cut to TOP_K              4 chunks
  ↓  build_prompt              unchanged
  ↓  answerer                  unchanged
answer
```

Nothing about `indexing` changes, so `collection_name` stays `bge-m3-1000-200`
and no re-ingest is needed. That is what keeps the result comparable to the four
recorded `TOP_K` experiments.

**The `reranker` is optional.** `RERANKER_MODEL` unset means today's behaviour,
and `retrieve()` then fetches `TOP_K` directly. This exists to serve the
baseline gate above, and it is also what lets `ask` work on a machine that has
never downloaded the model.

Because it is optional, `evaluation_run` metadata **must** record whether
re-ranking was on. An experiment that silently ran without it would be labelled
re-ranked and carry baseline numbers — the failure this project has now hit
three times, in the saturated `golden_example` set, in corpus drift, and here.

## Interfaces

New module, `reranker.py`:

```
build_reranker(config) -> CrossEncoderReranker | None
```

`None` when `RERANKER_MODEL` is unset. Raises when it is set and the model
cannot be loaded. Warns when `CHUNK_SIZE` approaches the model's token limit,
read from the loaded model rather than hardcoded — the limit belongs to the
model, and `RERANKER_MODEL` is a knob, so a constant would be wrong the moment
it is turned.

Two existing signatures widen by one parameter:

```
retrieve(query, config, embeddings, reranker, k)
rag_query(question, config, embeddings, model, reranker, on_piece)
```

This mirrors how `embeddings` and the chat model already work: expensive objects
are built once in `main.py` and passed down. `bge-reranker-base` is 1.1 GB and
takes seconds to load, so it cannot be built per query.

The alternative — hiding the `reranker` behind a module-level cache so no
signature changes — was rejected. It buys a simpler interface with invisible
mutable state, and it contradicts the explicit-injection pattern already chosen
for the other two components. Bundling all three components into one object was
also considered and deferred: it is the right move when a third component
actually forces it, not pre-emptively on the strength of two.

`config.py` gains `reranker_model` and `candidate_count`, and validates
`CANDIDATE_COUNT > TOP_K` — below that the `reranker` has nothing to choose
between, and that should fail at load rather than at runtime.

**The rule is conditional on `RERANKER_MODEL` being set.** Enforcing it
unconditionally would have made step 0 impossible: the ceiling run needs
`TOP_K=20` against a default `CANDIDATE_COUNT` of 20, and `20 > 20` is false. With
re-ranking off, `candidate_count` is unused and has no business constraining
`TOP_K`. Found while writing the first test, and settled before it was written.

## Failure

**A `reranker` that cannot be loaded fails at startup**, in `build_reranker`,
matching `_openai(config)` in `main.py`, which already raises before a run
begins rather than mid-way through.

Silent fallback to vector order was explicitly rejected. It would let an
`evaluation_run` complete, be labelled re-ranked, and report the baseline —
producing the conclusion "re-ranking does nothing" from a system that never ran
it. Failing loudly costs a few seconds of startup; the alternative costs a wrong
conclusion.

**Truncation warns rather than fails.** `bge-reranker-base` reads 512 tokens.
Question plus `chunk` at `CHUNK_SIZE=1000` is roughly 270, with room. Past about
1800 characters the model scores a prefix and returns a confident number, which
would read as "larger chunks hurt retrieval" during a future chunk-size
experiment. A warning is enough: truncation degrades a ranking, it does not
corrupt an answer, and at a large `CHUNK_SIZE` it might be an acceptable trade.

## Open questions

- **Is `CANDIDATE_COUNT=20` right?** Chosen as a reasonable start, not measured.
  Step 0 gives the first evidence. Revisited only if results justify it.
- **Whether one run is enough.** The `answerer` is at temperature 0 and the
  `reranker` is deterministic, so a single run should be stable, but this has not
  been checked. LangSmith supports repetitions if the numbers look noisy.
- **Whether `evidence_rank_reciprocal` should be normalised by chunk count**,
  still open from the evaluation design. It matters more here: it is the metric
  that most directly shows whether the `reranker` is ranking required `chunk`s
  higher rather than merely including them.
