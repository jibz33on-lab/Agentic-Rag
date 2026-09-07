# Design: evaluation

Designed 2026-09-07. Revised the same day around a LangSmith-centred
architecture — see [What was removed](#what-was-removed-and-why).

## Problem

Project 01 cannot tell whether a change helped. `CHUNK_SIZE`, `TOP_K`, the
`embedding_model`, the prompt and the `answerer`'s model are all things we can
change, and the collection-per-settings scheme deliberately keeps every
combination alive so they can be compared — but nothing compares them. Today
"did that help" is answered by reading a few answers and forming an impression.

## Principle

> Our code provides the RAG system and only the custom evaluation logic that
> LangSmith cannot provide. LangSmith is the central evaluation workspace for
> the golden dataset, experiments, traces, scores, system metrics, aggregation,
> repetitions and experiment comparison. Minimize custom evaluation
> infrastructure.

The first version of this design ignored that and specified seven modules of our
own. Most of them reimplemented a product we already pay for and already trace
into.

## Definition of done

Not "the code runs". This:

> The evaluation system can produce reproducible measurements and detect whether
> changing a critical RAG configuration actually changes retrieval or generation
> quality.

Which makes the acceptance test specific: two experiments at different
`CHUNK_SIZE`, against the same LangSmith Dataset, comparable in LangSmith. That
exercises the riskiest assumption here — that quote matching survives
re-chunking. Everything else can pass while the design is broken.

## The workflow

```
Golden Dataset in LangSmith
        ↓
      evaluate()
        ↓
      our RAG code  (rag_query)
        ↓
     LangSmith traces
        ↓
     our evaluators
        ↓
   evaluation results
        ↓
  LangSmith Experiment
        ↓
   compare experiments
```

The dataset stays fixed. The RAG implementation changes — chunk size, overlap,
top-k, retrieval strategy, hybrid versus vector, reranking, embedding model,
prompt, answer model, temperature, query rewriting — and each configuration is a
new experiment against the same references.

## Who owns what

| LangSmith | ours |
|---|---|
| the golden dataset, its examples and versions | generating those examples from our corpus |
| running the evaluation (`evaluate()`) | `rag_query`, the target under test |
| experiments, traces, tokens, latency | evidence matching against our corpus |
| score aggregation | the judge, and two conditional summary scores |
| repetitions (`num_repetitions`) | capturing OpenRouter's cost |
| error handling | |
| comparison (`evaluate_comparative`, `evaluate_existing`) | |
| the UI for all of it | |

Two capabilities worth naming because the first design could not do either:
**`num_repetitions`** runs each example several times, which is how judge
stability actually gets measured; **`evaluate_existing`** re-scores a finished
experiment with a different judge *without re-running the pipeline*.

## The golden dataset

**A LangSmith Dataset is the source of truth.** Not a JSON file in the repo, and
not both.

LangSmith cannot invent corpus-specific questions from our PDFs, so a local
builder samples the corpus, generates examples and pushes them once. After that,
the dataset lives in LangSmith and is edited there.

Each example carries what our evaluators need:

| field | why |
|---|---|
| `question` | the input |
| `expected_answer` | what correctness is judged against |
| `quote` | the verbatim span the answer should have come from |
| `source` | which document |
| `page` | where in it, when the loader supplies one |

**Evidence is a quote, not a `chunk` id and not a page.** Ids die the moment
`CHUNK_SIZE` changes, and comparing chunk sizes is the main thing this exists
for. Content survives re-chunking; identifiers do not. `Docx2txtLoader` also
emits one `Document` with no page at all, so any page-based scheme is blind on a
quarter of the corpus.

The quote is capped at 200 characters, matching `CHUNK_OVERLAP`. That is
arithmetic rather than a rule of thumb: a span no longer than the overlap is
guaranteed to sit whole inside at least one `chunk` at any chunk size at or above
the overlap.

## Sampling

Deterministic random with a fixed seed, constrained so all four documents are
represented. **20 examples.** That is the whole design.

The earlier proposal — 12 clusters of 5 — was written against an assumed corpus
of about a thousand chunks. The corpus is **126**:

```
hybrid-search-fundamentals.pdf    40
system-design-fundamentals.pdf    36
agentic-systems-mental-model.docx 25
complete-langgraph-tutorial.pdf   25
```

Sixty examples would have been 48% of it and clusters would have averaged ten
chunks, so the selection machinery would have been ceremony. At this size a
seeded sample with one coverage constraint gives the same practical result and
can be read in ten lines.

The seed is fixed in code, not configurable: a set you cannot rebuild identically
is not a fixed reference, and a tunable seed invites rerolling until the numbers
look better.

This is not a statistically perfect benchmark and is not trying to be. It is
enough to tell whether a configuration change moved the numbers.

The three hand-written examples already validated against real chunk text are
part of the initial dataset.

## The evaluators

```
question → rag_query → retrieved chunks + answer → evaluators → EvaluationResult
```

Per example:

- **evidence** — does any retrieved `chunk` contain the example's `quote`?
  Whitespace-normalised substring, NFKC-folded. Models return tidied quotes and
  PDF extraction is full of artefacts, so exact matching would score zero for
  everything and look like terrible retrieval rather than a broken ruler. This is
  ours because nobody else knows what counts as evidence in this corpus.
- **correctness** — the judge rules `correct` / `incorrect` / `declined` against
  `expected_answer`. `declined` is never scored correct: refusing when the
  excerpts do not contain the answer is what the prompt demands, and marking it
  wrong would point the metric backwards.
- **groundedness** — is every claim traceable to the excerpts the `answerer`
  actually received? The judge does not see the `quote`, deliberately: it must
  rule on the evidence the `answerer` had, not on evidence it may never have been
  given.

The two conditional numbers need no aggregation code of our own. LangSmith
averages each feedback key over the runs that carry it, so a conditional is
expressed by **emitting the score only for the examples it applies to**:

- **`correct_given_evidence`** — emitted only when evidence was found. Its mean
  is therefore correctness among the questions where the right text was in front
  of the `answerer`, and the key's count is the size of that denominator, which
  moves between configurations.
- **`answered_blind`** — emitted only when evidence was *not* found. Scored 1
  when the answer was nonetheless judged correct and not grounded: the model
  answered from its own knowledge. It reads as a pass and is a failure, and no
  unconditional average can see it.

Summary evaluators were specified here in an earlier draft and are not needed.
They receive runs and examples but not the feedback the judge produced, so they
could not have computed these anyway.

## Cost

```
OpenRouter provides the actual cost
        ↓
LangChain drops it
        ↓
our answerer preserves it
        ↓
the LangSmith trace receives it
```

An adapter for a provider and framework limitation, not a metrics system.
`_create_usage_metadata` reads seven named keys into a fixed `UsageMetadata` and
`cost` is not one of them, so there is nothing to configure.
`CostCapturingChatOpenAI` takes it from the raw chunk and `record_cost` writes it
to the run's metadata, because LangSmith's own pricing does not cover models
reached through OpenRouter. Measured working end to end. See
[the investigation](../investigations/trace-usage-and-cost.md).

## The models

Three roles with opposite requirements. The `answerer` is the experiment and must
vary. The generator and judge are the apparatus and must not — a run scored by a
different judge is not a comparison, it is two measurements taken with different
rulers.

| role | model | where |
|---|---|---|
| `answerer` | `ANSWERER_MODEL` | OpenRouter, varies |
| generator | `gpt-4.1-2025-04-14` | OpenAI, pinned |
| judge | `gpt-4o-2024-11-20` | OpenAI, pinned |

Dated snapshots, not floating aliases: an alias can be repointed, which would
change the apparatus without anything appearing to change. Different provider
from the `answerer`, so one provider having a bad day cannot move both the
experiment and the ruler at once.

## What was removed, and why

The first version specified our own dataset format, runner, metrics reader and
aggregation. All of it duplicated LangSmith.

| removed | replaced by |
|---|---|
| `evaluation/trace_metrics.py`, `SystemMetrics` | `evaluate()` records each run; the UI shows tokens and latency |
| trace polling on `end_time` | nothing to poll — we no longer read runs back |
| the coroutine guard | existed only because we read runs manually |
| `runner.py` | `evaluate()` |
| `evaluation/runs/*.json` | Experiments |
| `golden_set.json` as source of truth | a LangSmith Dataset |
| `summarise()` and its reported numbers | score aggregation, plus two summary evaluators |
| a custom evaluation CLI | a thin script that calls `evaluate()` |

`scoring.py`'s quote matching survives as the evidence evaluator. Its four
denominator rules mostly become free — a failed target run produces no scores, so
it drops out of the averages — except the two conditionals above, which are
genuinely ours.

**None of this is replaced with another framework of our own.** Where LangSmith
can do it, LangSmith does it.

## Decisions that still stand

| decision | why |
|---|---|
| evidence identified by quote | the only scheme that survives the `CHUNK_SIZE` comparison this exists for |
| quote capped at `CHUNK_OVERLAP` | guarantees the span fits inside one `chunk` at any comparable chunk size |
| judge on a pinned model, different provider | a judge that varies with the experiment is not a judge |
| the judge never sees the `quote` | groundedness must be judged on the evidence the `answerer` received |
| `declined` is not `incorrect` | refusing under bad retrieval is the behaviour the prompt asks for |
| cost captured from OpenRouter | it knows which provider served the request; no price table of ours could |

## Accepted trades

- **The dataset lives in a SaaS.** The repo alone can no longer rebuild or re-run
  an evaluation, and accepting a generated example is a UI action rather than a
  reviewable diff. Chosen knowingly, for a single source of truth.
- **The numbers are comparators, not grades.** Questions generated from a single
  `chunk` under-report absolute quality, equally for every configuration, so
  rankings hold and absolute values do not.
- **Cost depends on a private LangChain method.** Its failure is silent, which is
  why two tests guard it.

## Open questions

- The sampling strategy, above.
- Whether `evaluate()`'s `error_handling` excludes failed runs from score
  averages as expected, or whether that needs handling.
- Whether refusal on questions the corpus genuinely cannot answer deserves its
  own adversarial examples. Its own session.
