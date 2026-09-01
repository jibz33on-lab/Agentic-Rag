# Domain Terms

The shared vocabulary for this repo. These exact words are used in conversation,
code, comments, tests, and docs — by both the human and the AI.

Terms are written in `snake_case` because they double as code identifiers. If a
term is ambiguous or missing, we stop and fix it here before writing more code.

> **Review status.** `retrieval_strategy`, `retrieval_signals` and `agent` were
> settled in a design session and are agreed. The rest are still AI-proposed drafts
> from the term names and repo layout — review them before a project depends on
> them, since a wrong definition here propagates everywhere.

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

---

## Doing the work

### `ingestion_job`
One run that takes raw sources and produces stored `chunk`s: load, split, embed,
persist. Re-runnable, and reports what it wrote.

### `retrieval_strategy`
A named, swappable way of going from a query to ranked `chunk`s plus
`retrieval_signals` — dense, keyword, hybrid, reranked, multi-hop. Fetches when
asked and nothing more: it never interprets what it found or decides what happens
next. The thing being compared across projects, so every strategy shares one
interface and returns the same shape.

### `retrieval_signals`
What a `retrieval_strategy` noticed while fetching, returned alongside the
`chunk`s. A fixed set of three, filled in by every strategy:

- **weak match** — the best score was low, so likely nothing here answers the
  query. Defined per strategy, since scores are not comparable across strategies.
- **source concentration** — how few `document`s the returned `chunk`s came from.
- **candidate count** — how many `chunk`s were considered before cutting to top-k.

Observations, not judgements. Retrieval reports what it saw; the `agent` decides
what it means. The set is fixed deliberately — adding a field later means editing
every strategy that already exists.

### `agent`
The component that decides what to do next: which `tool_call` to make, whether the
evidence so far is enough, when to answer. Owns control flow, and owns all
interpretation — reading `retrieval_signals`, noticing when sources disagree, and
deciding to answer from the best match while quoting what contradicts it.
Distinct from `retrieval_strategy`, which only fetches when asked.

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
