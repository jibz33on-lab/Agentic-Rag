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


# The answerer's prompts, by name. `baseline` is the one every recorded
# experiment was run with, and its text does not change: editing it would
# invalidate every comparison against those numbers without anything failing.
# New work becomes a new name, and old names stay selectable so a recorded
# experiment can be reproduced.
PROMPTS = {"baseline": BASELINE_PROMPT}


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
