# Design: the v1 answerer prompt

Designed 2026-09-26, in the session that followed
[`answerer-prompt.md`](answerer-prompt.md), which built the machinery this uses.

## Problem

`baseline` is the only prompt in the registry, and nothing is known about what
any prompt technique does to this system. The aim is to find out, by changing
one prompt and measuring the same 25 `golden_example`s against it.

**This is a learning exercise, and that is a deliberate framing rather than a
consolation.** The baseline sanity run (`bge-m3-1000-200-b9037d76`) showed
`correct_given_evidence` 1.000, `grounded` 1.000 and `answered_blind` 0.000: all
eight failures are `evidence_found` misses, and none is an answer-generation
failure. There is no accuracy headroom for a prompt to recover. V1 exists to
learn what these techniques do, not to raise `correct`.

## The shared concept

**V1 keeps every evidence rule the baseline has and changes how the answer is
written.** A role, a goal, a procedure for partial evidence, and two style
instructions. The model still answers only from the excerpts.

The alternative — loosening sourcing so the answerer could add its own knowledge
about a topic — was named and rejected. It would be a different product, it
would drop `grounded` by design, and it would make the eight recorded
experiments incomparable to anything after it. Recorded here as **decision A**.

## The prompt

```
You are a senior AI engineer explaining material from a colleague's documents.

Your goal is to give an engineer what they need to use this in practice, in a
form they can check against the source documents.

Answer the question using only the excerpts below.                     <- frozen

If the excerpts do not contain the answer, say so plainly. Do not fill  <- frozen
gaps from your own knowledge - the point of these excerpts is that the
answer comes from the user's own documents, not from you.

Work out which parts of the question the excerpts cover. Answer those parts.
State plainly what they do not cover.

Write in plain language. Use bullet points where they help rather than one
long paragraph.

Excerpts:                                                              <- frozen
{excerpts}

Question: {question}                                                   <- frozen

Answer:                                                                <- frozen
```

Five slots, so that V2 and V3 have an obvious home rather than being stirred
into a growing paragraph: role, goal, the frozen task and evidence rules, the
reasoning procedure, then format.

## Scope

**In** — five techniques: role (tethered), goal, reasoning procedure, plain
language, response structure. `v1` added to `PROMPTS` beside `baseline`.

**Out** — citations (V2), important-point callouts (V2), diagrams (V3), few-shot
examples, question-type handling, any length instruction, any change to
`baseline`, retrieval, `TOP_K`, the `reranker`, the `embedding_model`, the
`answerer_model`, the judge, the dataset, and the evaluators.

## Decisions and why

| decision | why |
|---|---|
| the role is **tethered** to the documents | an untethered claim of expertise invites the model to use that expertise, which is what decision A forbids |
| the goal is verifiability plus practical use | a goal that restates the task line costs tokens and teaches nothing; this one says what a good answer achieves |
| the reasoning procedure is **behavioural, not a scratchpad** | provider reasoning is disabled in `build_chat_model` after a measured 1.5s cost, so there is no hidden place for silent reasoning. Written reasoning would be visible tokens the judge scores for grounding. This instructs the order of work, not the narration of it |
| no length instruction | saying nothing is what actually lets the model decide; an explicit "as long as it needs" would be an instruction and would change behaviour |
| five techniques in one version | chosen knowingly against the one-at-a-time rule, to get a version worth shipping first and decompose in V2 and V3 |

### The one place V1 touches a frozen line

The reasoning procedure refines the evidence rule above it. *"If the excerpts do
not contain the answer, say so plainly"* reads as all-or-nothing; *"answer the
parts they cover, state what they do not"* makes it partial. The frozen text is
not edited, but its meaning shifts. That is deliberate, and it is the behaviour
V1 is most likely to change: rows 1 and 7 of the baseline refused outright while
holding 33% and 50% of the required evidence, where rows 3 and 5 answered what
they could. The procedure asks for consistently what the model already does
inconsistently.

## Interfaces

| module | change |
|---|---|
| `answerer.py` | `V1_PROMPT` constant, and `"v1"` added to `PROMPTS` |
| `.env.example` | nothing required; `ANSWERER_PROMPT` is already documented |

Nothing else. The plumbing already exists: `config.py` carries the name,
`resolve_prompt` validates it, `rag_query` threads it, and `run_evaluation`
records it. Selecting v1 is an `.env` change.

## What tells us anything

**Must be identical.** Retrieval is frozen, so any movement means something
leaked: `evidence_found` 0.680, `evidence_recall` 0.853,
`evidence_rank_reciprocal` 0.463.

**Guardrails.** `grounded` 1.000, `answered_blind` 0.000,
`correct_given_evidence` 1.000.

**Signal.** `completion_tokens` (3,429 at baseline), latency P50 (4.03s), and
reading the 25 answers: do bullets appear, does the register change, do the 17
"Based on the excerpts..." openings survive, and do rows 1 and 7 become partial
answers instead of refusals.

**Expected prompt tokens ~24,700**, up from 22,592 — about 85 tokens of new
instruction across 25 questions. A change here is the prompt working, not a
fault. That is the opposite of the plumbing check, where 22,592 exactly was the
pass condition.

**Expected shape of the result.** `correct` flat or slightly down, since it
cannot rise. `completion_tokens` up substantially. `grounded` at genuine risk: a
bulleted answer makes more separate claims than a prose one, and the judge
checks every claim.

## Open questions

- **Attribution.** Five techniques in one version means the honest reading of any
  result is "V1 did this", not "the role did this". Accepted deliberately. If a
  number moves sharply, decomposing it means more runs, not more analysis.
- **V1 may pre-empt V2.** The goal line says "in a form they can check against
  the source documents", which gestures at sourcing without instructing it.
  Citation is 1 of 25 answers today. If V1 lifts that on its own, V2's citation
  instruction has less headroom left to demonstrate, and V2's result must be read
  against V1's rate rather than against the baseline's.
- **Whether `correct` under-reports partial answers.** The judge rules a partly
  answered question `declined`, which scores 0. Rows 3 and 5 gave substantially
  correct partial answers and scored nothing. That is a property of
  `JUDGE_PROMPT`, which is apparatus and must not change — but it means `correct`
  slightly under-reports quality on multi-chunk questions, equally for every
  configuration.
