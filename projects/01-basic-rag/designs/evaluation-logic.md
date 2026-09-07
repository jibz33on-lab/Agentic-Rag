# Design: evaluation logic

Designed 2026-09-07. Companion to [evaluation.md](evaluation.md).

`evaluation.md` records what we decided and why. This records **how** — the
algorithms, the contracts between modules, the exact arithmetic of each metric,
and the shape of every prompt and file.

> **Status: provisional.** This was written before the walking skeleton ran.
> Anything marked **[skeleton]** is an assumption the first end-to-end run is
> expected to confirm or correct. Read the last section before treating any of it
> as settled.

---

## 1. Quote matching (`scoring.py`)

The one piece of arithmetic the whole `retrieval` metric rests on.

**The agreed rule:** normalise both sides, then substring.

```
normalise(text):
    1. Unicode NFKC          — collapses ligatures: "ﬁ" -> "fi"
    2. all whitespace runs   -> a single space
    3. strip leading/trailing
```

```
supports(chunk, quote) := normalise(quote) in normalise(chunk.page_content)
```

Case is **preserved**. Quotes are meant to be verbatim, and lowercasing buys
tolerance we have no evidence we need while hiding a generator that is
paraphrasing rather than copying — which is a fault we want visible.

### Known hazard: hyphenation **[skeleton]**

PDF extraction breaks words across lines: `informa-\ntion`. After whitespace
collapse that is `informa- tion`, while the generator will write `information`.
That is a false miss, and it is not rare in these documents.

De-hyphenating is lossy in the other direction — `state-of-\nthe-art` collapses
to `state-of- the-art`, and stripping `"- "` yields `state-ofthe-art`, which no
longer matches the legitimately hyphenated `state-of-the-art`.

**The escalation, if the skeleton shows this biting:** compare on an
*alphanumeric skeleton* — lowercase, strip everything that is not a letter or
digit, then substring. That absorbs hyphenation, ligatures, whitespace and case
in one rule. For spans of ~200 characters the false-positive risk is negligible.

This is **not** adopted now. It is a wider rule than the one agreed, and adopting
it pre-emptively would be changing a decision on a hazard we have not yet
observed. The skeleton decides.

---

## 2. Clustering (`sampling.py`)

### Vectors

Read from Qdrant by scroll with `with_vectors=True`. **L2-normalised to unit
length before clustering.** The collection uses `Distance.COSINE`, and Euclidean
k-means over unit vectors is equivalent to spherical k-means over cosine — so
this makes the clustering agree with the geometry retrieval actually searches.
Skipping the normalisation would cluster by a different notion of "near" than the
retriever uses, which is a subtle way to sample the wrong thing.

### Filtering

`chunk`s whose `page_content` is under **200 characters** are dropped before
clustering. Headers, page numbers and fragments. Applied before, not after, so
they cannot pull a centroid.

### The algorithm

```
SEED = 0                     # fixed in code, never configurable
MAX_ITERATIONS = 50

1. init      k centroids by k-means++ , seeded
2. assign    each vector to its nearest centroid (Euclidean, unit vectors)
3. recentre  centroid := mean of members, re-normalised to unit length
4. repeat    2-3 until assignments are unchanged, or MAX_ITERATIONS
```

**Empty clusters** are the one edge case that must be handled deterministically:
if a centroid ends a round with no members, it takes the single point currently
furthest from its own centroid. Ties break on the lower index. Without this the
run either divides by zero or silently returns fewer than `k` clusters, and a
missing cluster means a missing slice of the corpus with nothing saying so.

**Re-normalising the mean** at step 3 keeps centroids on the unit sphere, so
distances stay comparable across iterations.

---

## 3. Selection within a cluster (`sampling.py`)

Order each cluster's members ascending by distance to centroid. Rank 0 is the
most typical `chunk`; the last rank is the most peripheral.

**Five primary slots**, evenly spaced across that ranking:

```
slot(i) = round(i * (n - 1) / 4)     for i in 0..4,   n = cluster size
```

so a 200-member cluster picks ranks 0, 50, 100, 149, 199.

**On rejection** — the `chunk` is refused by the generator, or its quote fails
validation — the slot walks outward to its nearest unused member: `slot+1`,
`slot-1`, `slot+2`, `slot-2`, and so on, skipping anything already tried. The
substitute is therefore drawn from the same region of the ranking, which is what
preserves the spread. Naively taking "the next ten in rank order" would collapse
all five picks into the cluster's core the moment refusals started.

**Cap: ten generator calls per cluster.** When the cap is reached the cluster
yields whatever it accepted — three, or four, or none — and the gap is recorded
in the run's report rather than quietly reducing the set size.

Clusters smaller than five yield at most `n`, and that too is a reported gap.

---

## 4. The generator contract (`generator.py`)

**In:** one `chunk`'s text and its `source`.
**Out:** a `golden_example`, or a refusal.

Structured output, so a malformed response is a client error rather than a
parsing problem:

```
{ "usable": true,
  "question": str,
  "expected_answer": str,
  "quote": str }          # <= 200 characters, copied verbatim

{ "usable": false,
  "reason": str }
```

### Prompt rules

The prompt must demand, and the doc must record why each rule is there:

1. **Answerable from this excerpt alone.** Otherwise the `golden_example` tests
   the corpus, not retrieval.
2. **Self-contained.** No "according to the text", no "in this document", no
   pronoun without a referent. `retrieval` embeds the question on its own — a
   question that only makes sense beside its source `chunk` cannot be retrieved
   by anything, and would score zero for every configuration equally. This is the
   single most likely way to generate a set that measures nothing. **[skeleton]**
3. **Specific enough to retrieve.** The question should carry the distinctive
   nouns of its subject. "What are the three stages?" is unanswerable by search;
   "What are the three stages of the hybrid retrieval pipeline?" is.
4. **The quote is copied, not written.** Verbatim, contiguous, ≤200 characters,
   and containing the evidence for the answer.
5. **Refuse** when the excerpt is a table of contents, a header, a reference
   list, a code fragment without prose, or otherwise holds no self-contained
   fact. Refusal is a correct outcome, not a failure.

### Validation, after the call

Every one of these rejects the example and increments a counted reason:

- `usable` is false → `refused`
- quote is empty, or over 200 characters → `quote_invalid`
- `normalise(quote) not in normalise(chunk)` → `quote_not_found`
- question or expected_answer empty → `incomplete`

Reasons are counted per cluster and printed at the end of a build. A build where
`quote_not_found` dominates means the generator is paraphrasing, and that is a
prompt problem, not a retrieval problem — the counts are what let you tell.

---

## 5. The judge contract (`judge.py`)

**In:** the question, the `expected_answer`, the `answer` produced, and the
excerpts the `answerer` was actually given.
**Out:**

```
{ "verdict": "correct" | "incorrect" | "declined",
  "grounded": bool,
  "reason": str }          # <= 300 characters
```

**The judge does not see the quote.** This is deliberate and load-bearing:
`grounded` asks whether the answer stayed inside *the excerpts the `answerer`
received*. Showing the judge the golden quote would have it check against
evidence the `answerer` may never have been given, which is a different question
and would make the `miss + correct + not grounded` row unreachable — the one row
that catches the model answering from its own knowledge.

**Definitions given to the judge, verbatim in the prompt:**

- `correct` — conveys the same facts as the expected answer. Wording may differ.
- `declined` — states the excerpts do not contain the answer. This is a *correct
  behaviour*, not a wrong answer, and must not be scored as one.
- `incorrect` — anything else, including a partially right answer that asserts
  something false.
- `grounded` — every factual claim is supported by the excerpts shown. An answer
  that is right but unsupported is **not** grounded.

**Settings:** temperature 0. Model pinned by `JUDGE_MODEL`.

**On unparseable output:** retry once, identical request. Still unparseable →
record `unjudged` with the raw text kept in the run file for inspection, and
exclude the example from every `generation` denominator.

---

## 6. The arithmetic (`scoring.py`)

The module with no dependencies, and the one most worth getting exactly right.

Let `E` be every `golden_example` attempted.

```
completed  = E where rag_query returned without raising
failed     = E - completed
judged     = completed where the judge returned a parseable verdict
unjudged   = completed - judged
```

### Reported reliability

```
failure_rate  = |failed|   / |E|
unjudged_rate = |unjudged| / |completed|
```

Both are reported beside the quality numbers, never folded into them. A run with
eight failures is a run to distrust, not a run that scores badly.

### Retrieval — over `completed`

```
hit(e)      = 1 if any retrieved chunk supports e.quote else 0
rank(e)     = 1-based position of the first supporting chunk, else none
hit_rate    = mean over completed of hit(e)
mrr         = mean over completed of (1 / rank(e)), counting a miss as 0
```

Both over `completed`, not `judged` — retrieval does not need a judge, so a
judge failure must not shrink retrieval's denominator.

### Generation — over `judged`

```
accuracy_overall     = |judged and verdict == correct| / |judged|

conditional_set      = judged and hit(e) == 1
accuracy_conditional = |conditional_set and verdict == correct| / |conditional_set|

grounded_rate        = |judged and grounded| / |judged|
declined_rate        = |judged and verdict == declined| / |judged|
```

`declined` is **not** counted as correct. It is correct *behaviour*, which is a
different thing, and it is visible through `declined_rate` and the diagnostic
counts below.

`accuracy_conditional` is emitted alongside `|conditional_set|`. Its denominator
moves between configurations — a configuration that retrieves better has more
examples in it — so the size travels with the number, always.

### The diagnostic counts

The four rows of the table in `evaluation.md`, as raw counts over `judged`:

```
working          = hit and correct and grounded
misread          = hit and incorrect
correct_refusal  = miss and declined
answered_blind   = miss and correct and not grounded
```

`answered_blind` is the headline warning. A configuration where it rises has an
`answerer` leaning on its own knowledge, and its `accuracy_overall` is
flattering it. It is reported as a count, not a rate, because at 60 examples a
rate implies a precision it does not have.

### System — over `completed` with a readable `trace`

```
latency_p50, latency_mean       seconds, end to end
first_token_p50                 seconds  [skeleton]
prompt_tokens, completion_tokens   sums and means
cost_total, cost_mean           [skeleton — see the probe]
traces_missing                  count of completed examples with no readable trace
```

`traces_missing` is reported so that a `system` section computed from 41 of 60
examples cannot be mistaken for one computed from all of them.

---

## 7. Reading the trace (`trace_metrics.py`)

**Measured, not assumed** — see
[the investigation](../investigations/trace-usage-and-cost.md).

**Cost is recovered, not estimated.** `build_chat_model` returns a
`CostCapturingChatOpenAI` that keeps OpenRouter's `usage` dict — cost included —
before LangChain's whitelist discards it, and clears it at the start of each
request so a failure cannot inherit the last question's figure. For the cost to
reach the trace it must be **returned** by the traced function; attaching it to
`response_metadata` does not survive.

**`flush()` is not a barrier.** It returned in 0.00s while the run still had
`end_time = None` and `total_tokens = 0`. The run completes about **5 seconds**
later. So:

```
client.flush(timeout=...)
poll read_run(run_id) until end_time is not None      # ~5s, second read
```

- Treat `end_time is None` as *not ready*, never as *no data*. Without that,
  a fast run and an unfinished one are indistinguishable.
- Give up after a cap and increment `traces_missing`.

**The coroutine guard.** `read_run()` and `list_runs()` are deprecated (removed
after 31 January 2027), but their replacements are **async-only**:
`Client().runs` is an `AsyncRunsResource`. Called from sync code it returns a
coroutine, and `coroutine.end_time` reports *missing* rather than raising — a
polling loop then declares "never finished" for a run that finished seconds
before. `read_system_metrics` raises `TypeError` when handed one, and closes it
so Python does not merely warn.

Sequencing is unchanged: quality results are appended as each example completes,
then one `flush()` and a single pass fills in `system` metrics. A crash loses
only the `system` half, which LangSmith still holds.

## 8. File shapes

### `evaluation/golden_set.json` — committed

```json
{
  "meta": {
    "generator_model": "...",
    "judge_model_at_build": null,
    "collection_name": "bge-m3-1000-200",
    "embedding_model": "baai/bge-m3",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "clusters": 12,
    "examples_per_cluster": 5,
    "seed": 0,
    "created_at": "2026-09-07T00:00:00Z",
    "gaps": [{"cluster": 7, "accepted": 3, "reasons": {"refused": 5, "quote_not_found": 2}}]
  },
  "examples": [
    {
      "question": "...",
      "expected_answer": "...",
      "quote": "...",
      "source": "data/hybrid-search-fundamentals.pdf",
      "cluster": 0,
      "chunk_id": "…",
      "provenance": "generated"
    }
  ]
}
```

`chunk_id` is provenance only — the fastest way to find the text behind an odd
question. `scoring.py` never reads it, because ids do not survive re-chunking.

`gaps` lives in `meta` rather than being inferable from a short `examples` list,
so that "this cluster produced nothing" is a fact in the file rather than an
absence someone has to notice.

### `evaluation/runs/<timestamp>.json` — git-ignored

```json
{
  "meta": {
    "answerer_model": "...", "judge_model": "...",
    "collection_name": "...", "top_k": 4,
    "golden_set_created_at": "...", "golden_set_size": 60,
    "started_at": "...", "finished_at": "..."
  },
  "results": [
    {
      "question": "...",
      "status": "completed" | "failed" | "unjudged",
      "error": null,
      "hit": true, "rank": 2,
      "verdict": "correct", "grounded": true, "judge_reason": "...",
      "retrieved": [{"source": "...", "page": 3}],
      "run_id": "...",
      "latency_s": 4.1, "prompt_tokens": 1820, "completion_tokens": 96, "cost": null
    }
  ],
  "summary": { }
}
```

`results` is appended as the run proceeds; `summary` is written last. **A file
with results and no summary is a run that died** — which is how you tell, and why
the summary is not written first.

`golden_set_created_at` is copied in so that two run files can be checked for
having measured the same set. Comparing runs against different golden sets is the
mistake `DOMAIN_TERMS.md` warns about, and this is what makes it detectable.

---

## 9. Runner sequencing (`runner.py`)

```
load golden_set.json
open runs/<timestamp>.json for appending

for each golden_example:
    try:
        result = rag_query(question, ..., on_piece=None)
    except Exception as error:
        append {status: "failed", error: str(error)};  continue

    hit, rank   = score_retrieval(result.chunks, example.quote)
    verdict     = judge(example, result)          # retry once inside
    append {status: "completed" | "unjudged", ...}

flush()
for each appended result with a run_id:
    fill in system metrics

write summary
print the report
```

**Sequential, not concurrent.** Sixty examples at a few seconds each is a couple
of minutes, and concurrency would buy that back at the cost of rate-limit
handling, interleaved traces and non-deterministic ordering in the output file.
Not worth it at this size. Revisit if the set grows past a few hundred.

---

## 10. What the skeleton is expected to settle

Everything marked **[skeleton]**, gathered:

| # | Assumption | What we do if it is wrong |
|---|---|---|
| 1 | Whitespace-normalised matching survives PDF hyphenation | Escalate to the alphanumeric-skeleton rule in §1 |
| 2 | Generated questions are self-contained enough to be retrievable | Rewrite the generator prompt; possibly show it neighbouring `chunk`s for context |
| 3 | ~~`read_run` returns usage shortly after `flush`~~ | **Settled: false.** Ready ~5s later; poll on `end_time`. Guard against coroutines |
| 4 | ~~OpenRouter cost reaches the `trace`~~ | **Settled: false unaided, true with the subclass.** Cost is exact |
| 5 | The judge's structured output is stable at temperature 0 | Tighten the schema, or add a second retry |
| 6 | First-token time is recoverable from the `trace` | **Open.** `FIRST_TOKEN_TIME` exists on the async API, untested for streamed runs |

3 and 4 are answered — the probe did both, and 4 came out better than the
fallback allowed for. The walking skeleton now only needs to answer **2** (are
generated questions retrievable) and **5** (is the judge's structured output
stable). **1** needs real generated quotes, so the first true `golden-set` build
settles it. **6** is deferred deliberately rather than assumed either way.

## Open questions

- Whether `expected_answer` should be graded at all, or whether `grounded` plus
  a rubric against the excerpts is the more honest target. Grading against
  another model's answer inherits that model's mistakes.
- Whether `accuracy_conditional`'s moving denominator should be reported as a
  confidence interval rather than a bare fraction at n≈40.
- Whether refusals should be resampled from a *different* cluster once one is
  exhausted, rather than accepting the gap.
