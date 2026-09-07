# Design: evaluation

Designed 2026-09-07.

## Problem

Project 01 cannot tell whether a change helped. `CHUNK_SIZE`, `TOP_K`, the
`embedding_model` and the `answerer`'s model are all settings we can change, and
the collection-per-settings scheme deliberately keeps every combination alive so
they can be compared — but nothing compares them. Today "did that help" is
answered by reading a few answers and forming an impression.

## Definition of done

Not "the code runs". This:

> The evaluation system can produce reproducible measurements and detect whether
> changing a critical RAG configuration actually changes retrieval or generation
> quality.

Which makes the acceptance test specific: two `evaluation_run`s at different
`CHUNK_SIZE`, against the same `golden_example` set, producing comparable
numbers. That exercises the riskiest assumption in this design — that quote
matching survives re-chunking. Everything else can pass while the design is
broken; this is where it would show.

## Scope

**In**

- Three separately reported parts: `retrieval`, `generation`, `system`
- A `golden_example` set generated from the corpus, with visible provenance
- LLM-as-judge for `generation`, on a pinned model from a different provider
- Two terminal commands, and our own scoring
- The OpenRouter usage probe (below)

**Out**

- Refusal on questions the corpus genuinely cannot answer. Needs adversarial
  `golden_example`s, which cluster-and-sample cannot produce. Its own session.
- Judge-per-`chunk` retrieval scoring. The upgrade path for project 02.
- Isolating `generation` by injecting the golden `chunk`.
- LangSmith datasets and `evaluate()`. The iteration, not the start.
- Adding `--cov` to CI. Real gap, unrelated to this work.

## The shape

```
                 GOLDEN SET CREATION
                        │
                  OpenAI Generator
                        │
                        ↓
                golden_set.json


                 EVALUATION RUN
                        │
                 ┌──────┴──────┐
                 ↓             ↓
            RAG Answerer     OpenAI Judge
                 │             │
          Model under test     │
                 │             │
             OpenRouter        │
                 └──────┬──────┘
                        ↓
                   LangSmith
                 01-basic-rag-eval
```

Three model roles, because they have opposite requirements. The `answerer` is
the experiment and must vary. The generator and the judge are the apparatus and
must not: a run whose judge differs from the run it is compared against is not a
comparison, it is two measurements taken with different rulers. The generator is
recorded in the golden set, the judge in every `evaluation_run` result, so that a
mismatch is visible rather than silent.

They sit on OpenAI, reached through its SDK directly, while the `answerer` stays
on OpenRouter. Different providers for the experiment and the apparatus removes a
whole class of correlated failure — a provider having a bad afternoon cannot move
both at once.

## The three parts

| part | measures | judge |
|---|---|---|
| `retrieval` | hit rate and MRR against the `chunk` the question was written from | no |
| `generation` | `verdict` (correct / incorrect / declined) and `grounded` | one call |
| `system` | latency, tokens, cost, failure rate — read from the `trace` | no |

`system` is operational only. Behavioural checks were considered and deferred;
groundedness came back into `generation`, where it is checkable against `chunk`s
we already have.

### Why `generation` is reported twice

One `rag_query` per `golden_example` serves both parts. That makes
`generation`'s headline number contaminated: when retrieval misses, the
`answerer` had no chance, and its score drops for a failure that was not its own.

So `generation` is reported **overall** and **conditional on retrieval hitting**.
The conditional number is the attributable one — of the questions where the right
text was in front of it, how often did the `answerer` get the answer right. Its
denominator differs between configurations, so it is always read alongside the
hit rate, never alone. This costs nothing: it is a filter over results we already
have.

### Why the judge returns two fields

Because `verdict` alone points the wrong way. When retrieval misses, the correct
behaviour is refusal — the `PROMPT` demands it — and a correctness-only judge
marks refusal wrong. Crossing `verdict` with `grounded` gives the table the whole
split exists to produce:

| retrieval | verdict | grounded | reading |
|---|---|---|---|
| hit | correct | true | working |
| hit | incorrect | true | the `answerer` misread the right text |
| miss | declined | true | behaving correctly under bad retrieval |
| miss | correct | **false** | answered from its own knowledge — looks like a pass, is a failure |

That last row is the failure that quietly inflates RAG benchmarks, and nothing
else in the design can see it.

## Building the golden set

```
DOCUMENTS → CHUNKING → EMBEDDINGS   ← already done, during `ingest`
                           ↓
              read vectors out of Qdrant
                           ↓
                  K-MEANS (numpy, k=12)
                           ↓
        ┌──────┬──────┬─────────┬──────┐
        │ C1   │ C2   │   ...   │ C12  │
        └──────┴──────┴─────────┴──────┘
           ↓      ↓        ↓       ↓
           5      5       ...      5
           └──────┴────┬───┴───────┘
                       ↓
                  60 chunks
                       ↓
              LLM generates questions
                       ↓
                 Golden Dataset
```

Clustering earns its place on this corpus specifically. The four files are four
distinct topics, and `agentic-systems-mental-model.docx` is roughly 1% of the
text — under uniform or proportional sampling a 60-example set gets zero or one
question from it. Cluster-based sampling gives the smallest document the same
share as any other. The stated reason: represent different parts of the corpus
rather than accidentally over-sample one topic.

Vectors are read back out of Qdrant, not recomputed. This saves ~1000 embedding
calls per rebuild, and guarantees k-means clusters the exact vectors retrieval
searches.

**Rules:**

- k-means hand-rolled on `numpy`, already resolved in the lock file. Seed fixed
  in code, not configurable — a golden set you cannot rebuild identically is not
  a fixed reference, and a tunable seed invites rerolling until the numbers look
  good.
- Five per cluster chosen by **rank-spread**: sort by distance to centroid, take
  five evenly across that order. Not the five nearest — cluster centres are
  dense, and the five closest can be five paraphrases of one paragraph.
- Two junk guards. `chunk`s under 200 characters are dropped before clustering,
  which catches headers and page fragments. And the generator may refuse a
  `chunk` holding no self-contained fact, which generalises to junk we have not
  thought of. Refusals are counted and reported, never silent.
- Refusals are topped up from the cluster's remaining ranked candidates, capped
  at ten per cluster. A cluster that still cannot yield five keeps the gap, and
  the gap is reported.

## How a `golden_example` points at its evidence

By **quote** — the verbatim span the generator used, capped at 200 characters. A
retrieved `chunk` supports it if it contains that span.

This is the load-bearing decision. The alternatives fail the thing we built this
for: `chunk` ids die the moment `CHUNK_SIZE` changes, and `source`/`page` is
blind on the docx, which `Docx2txtLoader` emits as one `Document` with no page at
all. Quotes are content, and re-chunking rearranges content rather than
destroying it.

The 200-character cap is arithmetic, not a rule of thumb: a quote no longer than
`CHUNK_OVERLAP` is guaranteed to sit whole inside at least one `chunk` at any
chunk size at or above the overlap.

**Matching is whitespace-normalised substring.** Models return tidied quotes —
collapsed whitespace, dropped hyphens — and PDF extraction is full of exactly
those artefacts, so exact matching would return zero for everything and look like
terrible retrieval rather than a broken ruler. Normalising kills the common case
without introducing a threshold that would be tempting to tune against our own
results.

**The quote is validated at build time** against the `chunk` it came from. An
example that fails is discarded and counted — the same visible-failure treatment
`guardrails.py` applies to empty answers, moved one step earlier.

**Accepted bias:** a question generated from `chunk` X may be answerable from Y
too, and this scores that a miss. It under-reports absolute quality, equally for
every configuration. The number is a comparator, never a grade.

## Failure policy

```
                 60 examples
                     │
          ┌──────────┴──────────┐
      succeeds               fails
          │                     │
      score it            record failure
          │                     │
          │               don't score it
          └──────────┬──────────┘
                     ↓
              final evaluation
          ┌──────────┴──────────┐
     quality metrics       failure rate
     only completed        all examples
```

A failure is recorded and stepped over, never fatal — the same reasoning as
"one corrupt PDF must not cost you the other files", and forced anyway, since
failure rate is a `system` metric and cannot be measured by aborting on the first
one.

Failures are excluded from the quality denominators and reported as their own
number. Counting them as misses would count them twice, and would make two runs
of the same configuration differ on the provider's mood.

Results are appended as each completes, so a crash at example 47 keeps 47. The
summary is written at the end, and its absence is how you know a run died.

A missing `run_id` — tracing off, or the `trace` unreadable after `flush` — makes
`system` metrics null for that example only. `retrieval` and `generation` still
score; neither needs the `trace`.

```
Judge → parse?
        ├── yes → use it
        └── no  → retry once → parse?
                              ├── yes → use it
                              └── no  → unjudged, excluded
```

Coercing an unparseable judge response to `incorrect` would make a broken judge
look like a bad `answerer`. `unjudged` is reported separately.

## Interfaces

`answer_one` moves out of `main.py` into `src/rag_query.py`, and both `ask` and
`evaluate` call it. The roadmap already says logic belongs in components rather
than in the terminal command; evaluation is the second caller that makes it worth
fixing. Evaluating a reassembled lookalike pipeline would measure a system we do
not ship.

```
rag_query(question, config, embeddings, model, on_piece=None) -> RagQueryResult
RagQueryResult(answer: str, chunks: list[Document], run_id: str | None)
```

`on_piece` becomes optional — evaluation has nothing to print. `chunk`s come back
as LangChain `Document`s, matching the project's "if LangChain supplies it, we
call it" principle, and carrying their text: quote matching needs content, and
`rag_query` is `@traceable`, so full retrieved text lands in the `trace` where a
bad run can be diagnosed without re-running it.

`build_chat_model` returns a `CostCapturingChatOpenAI` — a subclass that keeps
the `usage` dict OpenRouter sends, including its `cost`, which LangChain
otherwise discards. It also clears that state at the start of each request, so a
failed call cannot inherit the previous question's cost. See
[the investigation](../investigations/trace-usage-and-cost.md).

New modules, under `src/evaluation/`:

| module | interface | depends on |
|---|---|---|
| `sampling.py` | vectors + `chunk`s → chosen `chunk`s | numpy |
| `generator.py` | one `chunk` → a `golden_example`, or nothing | OpenAI |
| `golden_set.py` | build, read, write the file, hold provenance | sampling, generator |
| `judge.py` | question, answer, `chunk`s, expected → `verdict`, `grounded`, reason | OpenAI |
| `scoring.py` | results → hit rate, MRR, both `generation` numbers | **nothing** |
| `trace_metrics.py` | `run_id` → latency, tokens, cost | LangSmith |
| `runner.py` | a `golden_example` set → an `evaluation_run` | all of the above |

`scoring.py` having no dependencies is the line worth defending: the failure
policy contains four denominator rules, and rules like that are where quiet
arithmetic bugs live. Pure means they are testable with a list of dicts and no
API key.

A shared helper builds the OpenAI client once, wrapped in `wrap_openai` so the
judge's reasoning is visible in LangSmith. The judge is otherwise the least
inspectable part of the design — it emits a verdict and nothing else — and one
line is a cheap price for the difference between "the judge said incorrect" and
"the judge said incorrect *because* it read the excerpt this way".

Two commands on `main.py`: `golden-set` and `evaluate`. Building costs money, so
it is never automatic.

## Data

One indented JSON file, `evaluation/golden_set.json`, committed:

```
{"meta": {...}, "examples": [...]}
```

`meta` carries `generator_model`, the collection it was built from,
`embedding_model`, `chunk_size`, `chunk_overlap`, seed, `k`, examples per
cluster, and created-at. Every one of those was agreed as recorded, and JSONL has
nowhere to put a header.

Each example: `question`, `expected_answer`, `quote`, `source`, `cluster`,
`provenance`, and the `chunk` id it came from. That id is provenance only — the
fastest way to answer "what text produced this odd question?" — and is never read
by `scoring.py`, because ids do not survive re-chunking.

`provenance` is `generated`, becoming `accepted` when a human has read it. This
is how the `DOMAIN_TERMS.md` line survives contact with an LLM-built set: what is
forbidden is generated-and-silently-trusted, not generated. Indented JSON in git
means acceptance is a reviewable diff.

`evaluation/runs/<timestamp>.json` per `evaluation_run`, git-ignored — outputs,
not references. Each records the judge model, the `answerer` model, the
collection, and every metric above.

## Decisions, and why

| Decision | Why |
|---|---|
| `provenance` on every example | Lets generation and human review coexist without a second term or a later migration |
| `system` is operational only | Behavioural checks need adversarial examples the sampling cannot produce |
| Token and cost captured by a `ChatOpenAI` subclass | LangChain's `_create_usage_metadata` is a whitelist with no slot for cost; overriding the chunk conversion is the only place the raw figure still exists |
| OpenRouter's cost, not a price table | OpenRouter routes across ~30 providers charging differently, so it is the only party that can compute the real figure |
| Evidence identified by quote | The only scheme that survives the `CHUNK_SIZE` comparison this exists for |
| Quote capped at `CHUNK_OVERLAP` | Guarantees the span fits inside one `chunk` at any comparable chunk size |
| Rank-spread sampling | The five nearest a centroid can be five paraphrases |
| Hand-rolled k-means | `numpy` is already resolved; `scikit-learn` is 30 MB in a repo-wide environment for one function |
| Judge on a different provider, pinned | A judge that varies with the experiment is not a judge |
| Failures excluded, reported separately | Counting them in the quality metrics counts them twice |
| Our own scoring before LangSmith's | The metrics are new; coupling them to another API before they have settled ties two uncertainties together |

## Accepted trades

- **The numbers are comparators, not grades.** Single-`chunk` synthetic examples
  under-report absolute quality. Constant across configurations, so rankings hold.
- **`generation`'s conditional denominator moves** between configurations. It is
  meaningless without the hit rate beside it.
- **Evaluation depends on LangSmith being reachable** for `system` metrics. The
  other two parts degrade rather than fail.
- **Traces get fatter**, carrying full retrieved text on every query.
- **Cost depends on two private LangChain methods.**
  `_convert_chunk_to_generation_chunk` and `_stream` are both underscore-prefixed
  and can change without warning. The failure is silent — cost simply becomes
  `None` — which is why two tests guard it rather than a comment.

## Open questions

- When to promote `golden_example`s from `generated` to `accepted`, and whether
  that is a command or hand-editing.
- `build_chat_model` hardcodes OpenRouter's base URL, so the `answerer` cannot
  yet be pointed at another provider.
- CI runs `uv run pytest` without `--cov`, so the `fail_under = 80` floor is
  documented but never enforced. Out of scope here, worth fixing.
- Whether project 02 forces the move to judge-per-`chunk` retrieval scoring, and
  whether the numbers from before that change remain meaningful.
- Whether `FIRST_TOKEN_TIME` is populated for streamed runs. It exists on the
  async API and is untested; left out rather than assumed.
- ~~Whether `trace_metrics.py` is still needed for tokens and cost.~~
  **Settled: it is.** LangSmith stays the source of truth for `system` metrics.
  Reading them back keeps `runner.py` simple and avoids the same number being
  calculated and held in two places. The cost exception is already handled —
  the `answerer` captures OpenRouter's exact figure and `record_cost` writes it
  into the `trace`, because LangSmith does not price these models.

## Vocabulary

`DOMAIN_TERMS.md` changes as part of this work: `rag_query` added,
`golden_example` amended for `provenance` and quote-based evidence, and both it
and `evaluation_run` lose their AI-proposed-draft status.

## Config

New: `ANSWERER_MODEL` (renamed from `LLM_MODEL`), `GENERATOR_MODEL`,
`JUDGE_MODEL`, `OPENAI_API_KEY` (renamed from `OPEN_AI_API_KEY`, matching what
the SDK reads), `EVAL_CLUSTERS`, `EVAL_EXAMPLES_PER_CLUSTER`,
`LANGSMITH_EVAL_PROJECT`.

`OPENAI_API_KEY` is checked when the evaluation commands run, not in
`load_config` — `ingest` and `ask` never touch OpenAI, and must keep working for
anyone who has not set up a second provider. This is deliberately inconsistent
with how `OPENROUTER_API_KEY` is handled, and wants a comment saying so.

Also absorbed: `openai` and `langsmith` declared in `pyproject.toml`, both
currently transitive and both about to be imported directly;
`evaluation/runs/` git-ignored.

## The probe — done

`scripts/usage_probe.py`, written up in
[investigations/trace-usage-and-cost.md](../investigations/trace-usage-and-cost.md).

- OpenRouter **does** send the cost. LangChain **drops** it —
  `_create_usage_metadata` reads seven named keys and `cost` is not one.
- A ten-line subclass recovers it exactly. Measured: `9.18e-06` on a request.
- It reaches the trace when the traced function **returns** it. Attaching to
  `response_metadata` does not survive.
- `flush()` does not mean the run is readable. Tokens land about **5 seconds**
  later; poll on `end_time`.
- The replacement for the deprecated `read_run()` is **async-only**, and an
  un-awaited coroutine reports every attribute as missing rather than raising.
  `trace_metrics.py` raises on one instead.

Two assumptions this overturns are recorded in
[evaluation-logic.md](evaluation-logic.md) §10.
