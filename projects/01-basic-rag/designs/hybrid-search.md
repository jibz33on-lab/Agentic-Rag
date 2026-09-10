# Design: hybrid search

Designed 2026-09-10, in a `grill-me` session.

## Problem

Two relevance mechanisms have now failed the same way. Widening `TOP_K` eight-fold
moved `evidence_rank_reciprocal` only 0.32 → 0.50, and a cross-encoder `reranker`
moved it 0.46 → 0.463. Neither ranked the required `chunk`s higher; the first only
cast a wider net and the second re-ordered what the net caught.

Both are semantic. The `embedding_model` compares two vectors built apart, a
`reranker` reads query and `chunk` together, but both score *meaning* — so a
`reranker` inherits `bge-m3`'s blind spot rather than correcting it.

BM25 does not score meaning at all. It scores term frequency, term rarity across
the collection, and length. It is the first mechanism tried here that can fail
differently, and several required `quote`s in the benchmark carry literal tokens
that it matches exactly.

At `TOP_K=4` the `answerer` receives every required `chunk` for 17 of 25
`golden_example`s.

## Definition of done

Not "hybrid search is implemented". This:

> Hybrid search is kept only if it improves retrieval on the benchmark by a
> margin larger than the benchmark can produce by chance.

Against `01-basic-rag-benchmark`, `TOP_K=4`, collection `bge-m3-1000-200`:

| Criterion | Bar |
|---|---|
| `evidence_found` | ≥ 0.780 (a gain of at least 0.10 over 0.680) |
| `correct` | ≥ 0.880 — must not regress |
| `grounded` | 1.000 — must hold |

**Deliberately the same bar reranking was held to.** There is a real argument for
raising it: the candidate-set ceiling here is ≥ 0.960 by construction (see below),
and the mechanism argument is stronger than reranking's was. It was rejected.
Raising a bar because the hypothesis feels good is how a genuine gain gets
discarded — reranking's +0.04 was a real effect that failed a bar set at +0.10,
and a bar set by optimism would repeat that mistake in the other direction.

`prompt tokens` and `latency` carry **no bar**, exactly as in the reranking run.

`TOP_K=4` is the structural invariant. Hybrid fetches 20 + 20 `candidate`s;
exactly 4 `chunk`s reach the `answerer`. That is what "at `TOP_K=4`'s cost" means,
and it is guaranteed by construction rather than measured against a tolerance.

**Prompt tokens: reported, with a ±15% fault band around 22,592.** Not a
criterion. A ±2% band was considered and rejected on measurement: chunk lengths
across the corpus run min 47 / p25 545 / median 907 / max 998, so drawing a
different 100 chunks moves the total by sd 3.6%, p5–p95 spanning −6.1% to +5.9%.
Changing *which* four chunks the `answerer` sees is the entire point of the
experiment, so ±2% would fail the run by chunk-length lottery. Reranking's +5.2%
on 7 changed questions is consistent with that variance, not with a cost problem.
A deviation beyond ±15% is a **bug signal**, not a result — fusion failing to
deduplicate, `TOP_K` not applied after the ensemble returns its full list, or the
same `chunk` arriving twice with different metadata.

`evidence_rank_reciprocal` is a **diagnostic with no bar**. It read 0.46 through
both prior interventions. It is the number that says whether the blind spot is
lexical.

### The baseline gate

Before any hybrid number is trusted, the new code must run with hybrid **off** and
reproduce `evidence_found` 0.680 and `correct` 0.880 exactly.

Unlike reranking's gate, this one is **inert by construction**. `retrieve()` keeps
its current body on the vector-only branch — it opens the `vector_store` itself and
searches at `TOP_K`. Only the hybrid branch consumes a passed-in retriever. The
baseline path therefore contains no changed line, and the gate confirms rather
than proves.

The asymmetry is deliberate and is the same shape `reranker=None` already
introduced. The alternative — routing baseline through the new path and
establishing identity by measurement — was rejected: it costs a full
`evaluation_run` before anything is learned about hybrid, and a result of 0.676
would mean debugging a refactor instead of running an experiment.

A hybrid run that silently fell back to vector-only would reproduce 0.680 exactly,
which is what a *passing gate* looks like. Hence the failure handling below.

### The prediction, recorded before the run

**Consensus wins outright, and that is the mechanism.** At `c=60` and depth 20:

| Chunk | Fused score |
|---|---|
| Worst possible consensus — rank 20 in *both* lists | `1/80 + 1/80` = **0.0250** |
| Best possible single-list — rank 1, seen by one retriever | `1/61` = **0.0164** |

The worst `chunk` both retrievers found beats the best `chunk` only one found. The
fused ranking is therefore strictly *every overlapping chunk, then every
single-list chunk*, and **overlap size determines the top-4 composition**. Equal
weights do not cause this; scaling both by 0.5 leaves the ordering identical.

This cuts both ways, and both directions are predicted here rather than explained
afterwards:

- **For the eight misses it should work well.** The `TOP_K=20` ceiling run showed
  that for 24 of 25 questions every required `chunk` is already inside vector
  search's top 20 — sitting at ranks 5–20 where `TOP_K=4` never sees it. A `chunk`
  at vector rank 18 and BM25 rank 1 scores `1/78 + 1/61` = 0.029 and sails in.
  Promoting those is fusion's entire opportunity.
- **Anything BM25 finds alone will not reach the prompt** whenever overlap ≥ 4 —
  including the one question whose evidence is not in vector's top 20 at all.

**If the result is flat, weights are not the lever.** For a BM25-only `chunk` at
rank 1 to beat the worst consensus `chunk`, BM25 would need more than **3.2×**
vector's weight — a different experiment, not a tune. `c` is the lever: at `c=10`
that comparison flips to 0.0909 against 0.0667 and single-list finds compete.
Written down now, because after a flat result the instinct will be to reach for
weights.

**The candidate-set ceiling can only rise.** The union strictly contains vector
search's top 20, so the ceiling on `evidence_found` is at least the 0.960 measured
at `TOP_K=20`. That bounds what fusion *could* promote. It does not bound what it
does — RRF still chooses 4, and it can choose worse than vector's own top 4.
Ceiling up, outcome open.

## Step 0: measure the overlap first

**Before the LLM evaluation**, run the 25 benchmark queries through vector top-20
and BM25 top-20 and record, with no `answerer` call and no cost:

- the size of the overlap between the two lists, per question;
- where each required `chunk` ranks in BM25's list, with the eight known vector
  misses called out separately.

This is the cheap equivalent of reranking's ceiling run, and it is a gate for the
same reason.

| Outcome | Reading |
|---|---|
| Required chunks rank high in BM25 on the misses | The lexical hypothesis holds. Proceed. |
| Overlap ≥ 4 on most questions, evidence inside it | Fusion promotes the right chunks. Proceed. |
| Required chunks rank low in BM25 everywhere | BM25 cannot see them either. Three mechanisms, one blind spot — a far larger finding than a failed bar, and the work redirects rather than proceeding. |

## Result — 2026-09-10 — the gate fails, and the work redirects

**The paid hybrid evaluation is not justified and was not run.** Step 0 predicts
the specified configuration below both the bar and the baseline, at no cost.

| Metric | baseline | predicted hybrid | bar | |
|---|---|---|---|---|
| `evidence_found` | 0.680 | **0.640** (16/25) | ≥ 0.780 | **fail** |
| `evidence_rank_reciprocal` | 0.463 | 0.450 | — | unchanged |

Not flat — a regression. Two questions fixed (14, 21) against three broken
(13, 19, 20), net −1 in twenty-five.

The prediction is arithmetic over real retrieval: both retrievers run at
`CANDIDATE_COUNT=20` against `01-basic-rag-benchmark` and the collection
`bge-m3-1000-200`, fused at `c=60` with equal weights — the configuration this
document specifies. Its only assumption is that `fusion.py` would implement the
formula written here, which is why `fusion.py` was never written.

Two self-checks ran first and both reproduced recorded numbers, so the probe was
measuring the right collection and the right dataset: `evidence_found` at
`TOP_K=4` came back **0.680 (17/25)**, and vector search held every required
`chunk` inside its top 20 for **24 of 25** questions — the ceiling measured on
2026-09-09.

### The diagnostic reads 0.46 for the third time

| Intervention | `evidence_rank_reciprocal` |
|---|---|
| `TOP_K` 1 → 8, an eight-fold widening | 0.32 → 0.50 |
| Cross-encoder `reranker` | 0.46 → 0.463 |
| Hybrid RRF fusion | 0.463 → 0.450 |

This was recorded beforehand as the number that would say whether the blind spot
is lexical. It says no. A wider net, a semantic re-scorer and a non-semantic
lexical retriever all fail to rank the required `chunk`s higher. **That is a
larger finding than a failed bar**, and it is the third outcome in the Step 0
table: the work redirects rather than proceeds.

### Why it regresses: the predicted property, with an unpredicted victim

Consensus dominance held exactly as written. Overlap between the two top-20
lists was ≥ 4 on **all 25** questions — mean 11.5, min 6, max 16 — so only
`chunk`s both retrievers agreed on ever reached the top 4.

The prediction above says anything **BM25** finds alone will not reach the
prompt. The actual damage is the mirror image, and all three broken questions
have this shape. Question 13:

```
vector@20   1,2        BM25 never retrieved quote 1 at all
bm25@20     -,1
fused      11,1        quote 1 fell from rank 1 to rank 11
```

Quote 1 sat at **vector rank 1**. Absent from BM25's list it scored
`1/61 = 0.0164`, while all ten consensus `chunk`s scored at least
`2/80 = 0.0250`. It was buried beneath every `chunk` the two retrievers agreed
on.

So RRF punishes evidence only one retriever finds, **whichever** retriever that
is. Vector search was right, BM25 was ignorant, and fusion read the disagreement
as grounds to demote the correct `chunk`. Written as a prediction about BM25's
discoveries, the property is symmetric, and on this corpus vector search is the
one with more to lose.

### The eight questions vector search misses at `TOP_K=4`

| vector@20 | bm25@20 | fused | in top 4 |
|---|---|---|---|
| 2,5 | 2,1 | 1,3 | ok |
| 1,9,5 | 1,7,6 | 1,7,3 | miss |
| 8,17,2 | 10,–,1 | 7,22,1 | miss |
| 1,5,2 | 1,5,2 | 1,4,2 | ok |
| 2,9,–,1 | 7,11,–,1 | 4,10,–,1 | miss |
| 1,5,3,4 | 2,7,9,6 | 1,5,4,3 | miss |
| 3,1,8,2 | 1,3,13,10 | 2,1,9,5 | miss |
| 5,1,2,7 | 7,1,–,11 | 3,1,12,8 | miss |

BM25 alone is a competent retriever here — 21 of 25 questions have every
required `chunk` inside its top 20, against vector's 24. It is not that BM25
cannot find the evidence. It is that it does not rank it higher, and fusion
cannot promote what neither list ranks well.

### Honest limits on this result

- **It predicts `evidence_found` only.** `correct` and `grounded` need the
  `answerer`. Reranking showed `correct_given_evidence` reaching 1.000 while
  evidence barely moved, so an accuracy gain cannot be ruled out — but
  `evidence_found` is the metric the bar was set on, and it regresses.
- **It is a simulation.** Real retrieval, real chunks, real ranks; simulated
  fusion.

### What was kept

- `bm25.py` — the scroll, the count guard and the retriever, with three tests.
  It works, it is inert until something passes it to `retrieve()`, and nothing
  does.
- `scripts/hybrid_step0.py` — the probe. It reproduces the baseline and the
  ceiling as self-checks, so it stays useful for the next retrieval idea.
- `rank_bm25` as a dependency.

Never written: `fusion.py`, the `retrieve()` change, the `main.py` wiring, the
`evaluation_run` metadata, and the `DOMAIN_TERMS.md` edits. The `candidate`
re-definition and the `fusion` entry are moot until something is built.

## Scope

**In.**

- A BM25 index built from `chunk`s scrolled out of Qdrant, in memory, driving
  `rank_bm25` directly through a `BaseRetriever` of ours.
- A count check at index-build time that hard-fails on a short or empty scroll.
- `fusion`, ours: RRF, `c=60`, equal weights, both retrievers at
  `CANDIDATE_COUNT=20`.
- Lowercase, NFKC-folded, non-alphanumeric-split tokenisation.
- `retrieve()` accepting an already-assembled fused `retriever`, `None` meaning
  the existing vector-only path.
- `evaluation_run` metadata recording hybrid on/off plus `c`, weights and both
  fetch depths.
- `rank_bm25` as a plain dependency.
- The `candidate` re-definition in `DOMAIN_TERMS.md`, and a new `fusion` entry.

**Out**, deliberately.

- **Reranking.** Architecture A, not B. Fusion is measured alone so the result is
  attributable to one mechanism. Reranking is worth revisiting *on top of* hybrid
  once the candidate set contains the right chunks to promote.
- **Tuning `c` or the weights.** Fixed at 60 and equal for this experiment. `c=10`
  is the named follow-up if the result is flat.
- **Unequal fetch depths.** BM25 ranks all 126 chunks every query and could fetch
  deeper for free. Held at 20 to avoid a second variable.
- **`retrieval_signals`.** Same reasoning reranking gave: it means `retrieve()`
  returning something other than `list[Document]`, which ripples into `rag_query`,
  the evaluation target and the evaluators. The signals exist for the `agent` to
  read, and the `agent` is project 02+. This is the third time that cost is paid.
- **Touching `indexing`, the `record_manager`, the Qdrant collection, chunking or
  the corpus.** `bge-m3-1000-200` stands exactly as it is, which is what makes the
  0.680 baseline comparable by construction rather than by argument.
- **Changing the `golden_example` set, the prompt, the `answerer` or `TOP_K`.**

## Design

```
                      ┌─ once per process ──────────────────────┐
                      │  Qdrant scroll → 126 chunks             │
                      │  assert count == collection points_count │
                      │  BM25Retriever(k=20)                    │
                      └─────────────────────────────────────────┘
question
  ↓
  ├─ vector_store search    k=CANDIDATE_COUNT (20)
  └─ BM25 search            k=CANDIDATE_COUNT (20)
        ↓
     EnsembleRetriever      RRF, c=60, equal weights
        ↓                   candidate set = union, 20–40 chunks
     cut to TOP_K (4)
        ↓
     answerer               unchanged
```

**Why the chunks come from Qdrant rather than from `data/`.** Re-loading and
re-splitting the corpus would produce byte-identical `chunk`s in 0.67s, and
`verify-corpus` already exists to detect drift. Scrolling Qdrant instead makes
corpus parity **structural rather than remembered**: BM25 indexes literally what
the `vector_store` searches, and divergence becomes impossible rather than
detectable. The cost is a little plumbing below the LangChain layer, since
`QdrantVectorStore` exposes no "give me everything".

**Why the index is built once and passed in.** The corpus is fixed for this
benchmark, so 25 identical scrolls would be waste. The staleness this introduces
is real but bounded: if documents are added or removed, `indexing` updates Qdrant
and a new BM25 index must be built from Qdrant before querying. Recorded here
rather than guarded in code, because the `evaluation_run` is a single process over
a hash-verified corpus.

**Why both pieces are ours rather than LangChain's.** `BM25Retriever` lives in
`langchain_community`, which warns on import that it is being sunset, and
`EnsembleRetriever` lives in `langchain_classic` — not in `langchain` v1, and
undeclared in `pyproject.toml`, which its own comment forbids for a directly
imported package. `reranker.py` already rejected this exact pattern, naming the
same two packages, and subclassed `langchain_core` instead. Following that
precedent costs the `DOMAIN_TERMS.md` rule about using LangChain's names for two
more components, and buys back: no new deprecated surface, no new package, and
the consensus-dominance property above becomes a **unit test** rather than a
claim about a library's internals.

**Tokenisation is lowercase, NFKC-folded, split on non-alphanumerics.** Not a
default — a decision, because it sets the ceiling on what BM25 can match.
`rank_bm25`'s usual companion preprocessor is `text.split()`, under which
`Depends` does not match `Depends()`, `502` does not match `502.`, and `RRF` does
not match `RRF,`. The hypothesis under test is precisely that required `quote`s
carry literal tokens BM25 matches exactly, so that preprocessor would
manufacture the null result. NFKC folding is the same lesson `normalise()` in
`evaluators.py` records — the corpus is PDFs, and an unfolded ligature makes
`ﬁnd` tokenise as `nd`. A flat Step 0 must mean the hypothesis is wrong, not
that the ruler is broken.

**Why the switch is an argument and not a config flag.** Same reasoning as
`reranker: ... | None` with no default. An `evaluation_run` that quietly skipped
the BM25 half would carry baseline numbers under a hybrid label — and worse than
in the reranking case, because it would reproduce 0.680 exactly, which reads as a
*passing gate*. The on/off decision is visible at the call site, alongside the
depths and the fusion parameters.

## Interfaces

| Module | Change |
|---|---|
| new — `bm25.py` | a `BaseRetriever` over `rank_bm25`, built from chunks scrolled out of Qdrant. Verifies the count. Raises on a short or empty collection. |
| new — `fusion.py` | RRF over N retrievers, `c=60`, equal weights. A `BaseRetriever` itself. |
| `retrieval.py` | `retrieve()` gains a retriever parameter, no default. `None` → the existing body, unchanged. Otherwise: invoke it, cut to `TOP_K`. |
| `main.py` | assembles the fused `retriever` for a hybrid run; passes `None` for the gate. Writes the fusion parameters into `evaluation_run` metadata. |
| `pyproject.toml` | `rank_bm25` as a plain dependency. Nothing from `langchain_community` or `langchain_classic`. |
| `DOMAIN_TERMS.md` | `candidate` re-defined; `fusion` added, marked *ours*. |

Nothing in `indexing.py`, `vector_store.py`, `text_splitter.py`, `answerer.py` or
`config.py`. **No new settings** — `CANDIDATE_COUNT=20` and `TOP_K=4` already
exist and already hold the right values.

## Failure

**A short or empty scroll must be a hard failure, at index-build time, before any
retrieval or LLM call.**

Qdrant's `scroll()` returns a page plus a `next_page_offset` and its default limit
is well under 126. Loop it wrong and BM25 indexes a fraction of the corpus: every
query still returns 20 candidates, the run completes, the numbers are worse than
they should be, and nothing says why. An empty collection is worse still — fusion
degenerates to vector-search-at-depth-20-cut-to-4 and reports a number near
baseline that reads as "hybrid didn't help".

Neither is caught by the ±15% token band: a short index changes *which* chunks are
selected, not how many.

Qdrant reports `points_count`, so the check is exact and costs one call. **An empty
BM25 index is not a legitimate vector-only mode** — vector-only is the `None` path,
explicitly.

## Open questions

Deferred deliberately, not overlooked.

- **An RRF score cannot carry the weak-match signal.** Not a different scale — a
  different *kind*. Cosine similarity measures relevance, so "the best score was
  low" is meaningful. An RRF score measures rank consensus: `1/61 + 1/61` means
  "two retrievers each ranked this first", not "this is a good match", and both may
  have rated it mediocre. A weak-match signal on an ensemble has to reach past
  fusion to the member retrievers' own scores. For whoever implements
  `retrieval_signals`.
- **`candidate count` becomes the most informative of the three signals.**
  Reranking made it real but constant at 20. Hybrid makes it vary, 20–40, and the
  value is a direct readout of how much the two retrievers disagreed on a given
  query. Free, and more interesting than either of the others.
- **`tokenise()` and `evaluators.normalise()` disagree about NFKC.** The
  evaluator folds it before checking whether a `chunk` contains a `quote`;
  `tokenise` does not. A document could therefore produce a `chunk` the ruler
  scores as holding the evidence while BM25 could never have matched the term
  leading to it. Measured on the current corpus the gap is **zero terms wide** —
  the four documents contain no ligatures, only three `…` characters, which
  tokenise to nothing either way. Left uncoded rather than guessed at: folding
  is one line, but a test for it would assert behaviour this corpus never
  exercises. Revisit when the corpus changes, which `data/drafts/`,
  `corpus.sha256` and `verify-corpus` already make a reviewed event.
- **`c=10`, deferred rather than run.** Low `c` sharpens rank discrimination and
  would let single-list finds compete with consensus — at `c=10` a rank-1
  single-list `chunk` scores 0.0909 against a worst-consensus 0.0667. It is the
  named lever precisely because weights are not one: BM25 would need more than
  3.2× vector's weight to achieve the same thing. The probe can sweep `c` at
  zero cost. It was deliberately **not** swept: `c=60` with equal weights is the
  experiment this document specifies, and searching for a constant that clears
  the bar after seeing the result is how a fixed criterion becomes a story told
  afterwards. A sweep is its own experiment, with its own prediction recorded
  first.
- **`fusion` as the term for the component we now own.** `DOMAIN_TERMS.md` says
  to use LangChain's name where LangChain supplies the thing, and it does supply
  `EnsembleRetriever` — but on a surface this repo has decided not to import. The
  proposed entry is `fusion`, marked *ours*, alongside `chunk`, `candidate` and
  `answerer`. Confirm before it is written into `DOMAIN_TERMS.md`.
- **Whether BM25 should fetch deeper than vector.** It ranks all 126 chunks every
  query at no cost. Held equal here to keep one variable.
