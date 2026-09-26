"""The answerer's prompts, by name.

Separate from answerer.py because the answerer does not need them. It receives a
rendered prompt and renders it; nothing in there chooses one. `resolve_prompt`
is called at startup by the terminal command and the api service instead.

Adding a prompt is adding an entry here. Nothing else changes: config.py carries
the name, rag_query threads the text, and run_evaluation records which one ran.
"""

BASELINE_PROMPT = """Answer the question using only the excerpts below.

If the excerpts do not contain the answer, say so plainly. Do not fill gaps
from your own knowledge — the point of these excerpts is that the answer comes
from the user's own documents, not from you.

Excerpts:
{excerpts}

Question: {question}

Answer:"""


# Five techniques on top of the baseline: a role, a goal, a procedure for
# partial evidence, plain language and bullet structure. See
# designs/answerer-prompt-v1.md.
#
# The two evidence rules are copied from BASELINE_PROMPT verbatim. That is
# decision A: v1 changes how an answer is written, never where its facts come
# from. test_v1_keeps_the_baseline_evidence_rules fails if they are edited out,
# because losing them would drop `grounded` with nothing else to say why.
#
# The role is tethered — "from a colleague's documents" — because an untethered
# claim of expertise invites the model to use that expertise, which is the one
# thing decision A forbids.
#
# The procedure is behavioural, not a scratchpad. Provider reasoning is disabled
# in build_chat_model after a measured 1.5s cost, so there is nowhere for silent
# reasoning to happen; written reasoning would be visible tokens the judge scores
# for grounding. This instructs the order of work, not the narration of it.
#
# Nothing says how long an answer should be. Saying nothing is what actually
# leaves that to the model.
V1_PROMPT = """You are a senior AI engineer explaining material from a colleague's documents.

Your goal is to give an engineer what they need to use this in practice, in a
form they can check against the source documents.

Answer the question using only the excerpts below.

If the excerpts do not contain the answer, say so plainly. Do not fill gaps
from your own knowledge — the point of these excerpts is that the answer comes
from the user's own documents, not from you.

Work out which parts of the question the excerpts cover. Answer those parts.
State plainly what they do not cover.

Write in plain language. Use bullet points where they help rather than one
long paragraph.

Excerpts:
{excerpts}

Question: {question}

Answer:"""


# The answerer's prompts, by name. `baseline` is the one every recorded
# experiment was run with, and its text does not change: editing it would
# invalidate every comparison against those numbers without anything failing.
# New work becomes a new name, and old names stay selectable so a recorded
# experiment can be reproduced.
PROMPTS = {"baseline": BASELINE_PROMPT, "v1": V1_PROMPT}


def resolve_prompt(name: str) -> str:
    """The prompt registered under `name`.

    Raises rather than falling back to `baseline`. A typo that quietly ran the
    baseline would produce an evaluation_run labelled with the prompt that was
    asked for, carrying the numbers of the one that actually ran.
    """
    if name not in PROMPTS:
        known = ", ".join(sorted(PROMPTS))
        raise ValueError(f"unknown ANSWERER_PROMPT {name!r}. Available prompts: {known}")
    return PROMPTS[name]
