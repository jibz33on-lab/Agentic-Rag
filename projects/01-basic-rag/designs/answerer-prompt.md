# Design: answerer prompt

Designed 2026-09-26.

## Problem

The `answerer`'s prompt is one of the things we can change, and nothing records
which one produced a given `evaluation_run`. Two prompt experiments sit in
LangSmith identical in metadata, separable only by timestamp. Worse, editing the
prompt in place destroys the only copy of what the previous experiment measured.

`designs/evaluation.md` already lists the prompt among the configurations an
experiment is supposed to vary. This is the piece that makes it measurable.

## The shared concept

**Named prompts live in the repo. Configuration selects one. The label recorded
on the `evaluation_run` is derived from that selection, so it cannot disagree
with what actually ran.**

The alternative — one prompt constant plus a hand-maintained version label — was
rejected. Nothing forces the label to be updated, and forgetting once produces an
experiment labelled `baseline` carrying different numbers, silently. That is the
same failure `rag_query.py:84-88` refuses a default `reranker` to prevent: "an
evaluation_run labelled reranked that carries baseline numbers". Deriving the
label from the selection makes the class of bug unreachable rather than
discouraged.

`baseline` is the current prompt text, unchanged, and stays frozen. Later
variants are added under new names — `v1`, `v2` — and every name stays
selectable. Nothing supersedes anything, for the same reason the
collection-per-settings scheme (`config.py:60-70`) keeps every combination alive:
reproducing the original experiment is the point.

## Scope

**In**

- a registry of named prompts in `answerer.py`, with `baseline` as its only entry
- `ANSWERER_PROMPT` in `Config`, defaulting to `baseline`
- resolution and validation at startup, owned by `answerer.py`
- the resolved prompt threaded into `stream_answer`, with no default
- the selected name in the `evaluation_run` metadata
- one manual sanity check that the plumbing did not change the baseline

**Out**

- writing `v1` or any other variant — its own session, after the baseline
  failures have been read
- any change to `baseline`'s text
- retrieval, `TOP_K`, the `reranker`, the `embedding_model`, the
  `answerer_model` — frozen for this and the experiment that follows
- `JUDGE_PROMPT`, `GENERATOR_PROMPT`, `MULTI_PROMPT`, `NECESSITY_PROMPT`. These
  are apparatus, not the experiment, and never vary
- prompt fingerprinting and run-blocking validation
- a `prompts/` folder, and the LangSmith Prompt Hub
- extra terminal output
- bundling `rag_query`'s parameters into an object

## Decisions and why

| decision | why |
|---|---|
| configuration selects, rather than labels | a label that is maintained by hand can lie about what ran |
| name only — no fingerprint, no hash | the prompt is a tracked constant, so git already provides the audit trail a manifest gives the corpus; the rendered prompt is in every `trace` |
| `baseline` frozen by convention | enforcement would be machinery guarding a hole git has covered |
| all names stay selectable | reproducing a recorded experiment is the whole point of freezing one |
| constants in `answerer.py`, not a folder | the other four prompts already live as constants beside their callers; files earn their place when non-engineers edit them |
| `answerer.py` validates, not `load_config` | see below |
| the new parameter has no default | a forgotten argument would silently answer with `baseline` while the metadata said otherwise |

### Why validation is not in `load_config`

`answerer.py` imports `Config`, so `config.py` cannot import the registry back.
Validating in `load_config` would mean duplicating the prompt names there — two
sources of truth for which prompts exist — or moving the prompts away from the
`answerer` that owns them.

So `answerer.py` raises on an unknown name, at startup, before the first question
or request. That is where `build_reranker` already fails for the same reason
(`main.py:282-284`): "a model that will not load ends the run here rather than
fifteen examples in, having already spent money." An `evaluation_run` is 25 paid
questions.

**Accepted cost.** `load_config` stops being the single gate where every bad
setting is caught. One setting now passes it and fails a few lines later. Taken
knowingly, in exchange for one source of truth for the names.

## Interfaces

| module | change |
|---|---|
| `config.py` | new `answerer_prompt: str` field, read from `ANSWERER_PROMPT`, defaulting to `baseline`. No validation of the value |
| `answerer.py` | the registry, keyed by name, with `baseline` holding today's text verbatim. A resolver that takes the name and returns the prompt, raising on an unknown one. `build_prompt` and `stream_answer` take the prompt as a parameter instead of reading the module constant |
| `rag_query.py` | carries the resolved prompt through to `stream_answer`. Signature grows to seven parameters |
| `main.py` | resolves at startup in `ask` and `run_evaluation`, alongside `build_chat_model` and `build_reranker`; adds the selected name to the `evaluate` metadata |
| `asgi.py` | resolves at startup, so a bad name kills the `container` on boot rather than on the first request |
| `api.py` | the resolved prompt joins the dependencies it closes over (`api.py:102-117`) |
| `.env.example` | documents `ANSWERER_PROMPT` |

`rag_query` reaching seven parameters is noted, not addressed. The third growth
is worth stopping for.

## Done

Unit tests, and one live check.

The unit layer must include a test that passes a **non-`baseline`** prompt and
asserts the rendered output uses it. Without it, a version where the resolved
prompt is computed, passed and then ignored would stay green — the registry has
one entry, and that entry is the default.

The live check is one `evaluation_run` at the shipped configuration, run by hand
after implementation. **Prompt tokens must be 22,592**, matching the TOP_K=4 row
in `docs/roadmap.md`. That number is deterministic: if the rendered prompt is
byte-identical, it cannot move, and no sampling or judge is involved. The judged
metrics (`correct` 0.880, `grounded` 1.000, `evidence_found` 0.680) are reviewed
as a sanity band, not as equality — `temperature=0` through OpenRouter routes
across ~30 providers and is not bit-reproducible.

This is a one-time validation, not a gate framework. Its purpose is to stop the
first `v1` comparison confounding two changes: the new prompt, and the plumbing
that delivered it.

## Open questions

- **Whether the sanity check gets a line in `docs/roadmap.md`.** The reranking
  gate got a short section. One sentence recording what this run reported would
  tell the next reader the plumbing was checked. Deferred, not decided.
- **No term was added to `DOMAIN_TERMS.md`.** There is still no word for one
  named, selectable `answerer` prompt — `prompt_variant` was proposed and set
  aside in favour of plain names. Relatedly, "prompt" is now ambiguous in this
  repo: one is the experiment and four are apparatus, and that line exists only
  in prose. If a second variant makes either bite, fix it there first.
- **When a `prompts/` folder becomes right.** Not at two entries. Probably when
  a variant needs more commentary than code around it, or at the point
  `answerer.py` is visibly a prompt library with an answerer attached.
