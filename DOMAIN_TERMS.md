# Domain Terms

The shared vocabulary for this repo. These exact words are used in conversation,
code, comments, tests, and docs — by both the human and the AI.

Terms are written in `snake_case` because they double as code identifiers. If a
term is ambiguous or missing, we stop and fix it here before writing more code.

> **Status: draft.** These definitions were proposed by the AI from the term names
> and the current repo layout. Review and correct them — a wrong definition here
> propagates into every project.

---

## Core data

### `document`
A whole source item as it arrived, before any splitting — one PDF, one web page,
one transcript. Holds its own metadata (origin, retrieved-at, title). A `document`
is never what gets embedded; it is what a `chunk` comes from.

### `chunk`
A contiguous slice of exactly one `document`, sized for retrieval and embedding.
Always knows which `document` it came from and where in it. Chunks are the unit
that a `retrieval_strategy` returns.

### `evidence_tier`
How much a retrieved `chunk` should be trusted when the `agent` reasons over it.
A ranking of source quality, not of similarity score — a strong keyword match from
a weak source stays a weak tier. Assigned at ingestion, carried through retrieval.

---

## Doing the work

### `ingestion_job`
One run that takes raw sources and produces stored `chunk`s: load, split, enrich
with `evidence_tier`, embed, persist. Re-runnable, and reports what it wrote.

### `retrieval_strategy`
A named, swappable way of going from a query to a ranked list of `chunk`s — dense,
keyword, hybrid, reranked, multi-hop. The thing being compared across projects, so
strategies share one interface and can be substituted for each other.

### `agent`
The component that decides what to do next: which `tool_call` to make, whether the
evidence so far is enough, when to answer. Owns control flow. Distinct from
`retrieval_strategy`, which only fetches when asked.

### `tool_call`
One invocation of a capability by the `agent` — a retrieval, a search, a
calculation — with its arguments and its result. The atomic step recorded in a
`trace`.

---

## Knowing whether it works

### `trace`
The full ordered record of one run: the query, every `tool_call` and result, the
`agent`'s decisions, and the final answer. What gets read when debugging why a run
went wrong, and what an `evaluation_run` scores.

### `golden_example`
A hand-checked query paired with its expected answer and the `chunk`s that should
have supported it. The fixed reference an `evaluation_run` measures against.
Curated by the human, never generated and silently trusted.

### `evaluation_run`
One scoring pass of a configuration against a set of `golden_example`s, producing
comparable numbers. The unit of "did this change help" — meaningless unless the
`golden_example` set is held constant across runs.

---

## Adding a term

Propose it here first, with a one-line definition and a note on what it is *not*.
Ambiguity between two neighbouring terms is the thing worth spending words on.
