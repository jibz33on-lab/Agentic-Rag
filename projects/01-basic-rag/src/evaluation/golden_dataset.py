"""Builds the golden dataset from our corpus and pushes it to LangSmith.

LangSmith owns the dataset once it is there — versions, edits, and every
experiment run against it. What it cannot do is invent corpus-specific questions
from our PDFs, which is the only reason this module exists.

    chunks -> sample -> generate -> validate the quote -> LangSmith Dataset
"""

import json
import random

from .evaluators import supports

SEED = 0
QUOTE_LIMIT = 200

GENERATOR_SCHEMA = {
    "name": "golden_example",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "usable": {"type": "boolean"},
            "question": {"type": "string"},
            "expected_answer": {"type": "string"},
            "quote": {"type": "string"},
        },
        "required": ["usable", "question", "expected_answer", "quote"],
        "additionalProperties": False,
    },
}

GENERATOR_PROMPT = """Write one question that this excerpt alone answers.

Rules:
- Answerable from this excerpt alone.
- Self-contained. No "according to the text", no "in this document", no pronoun
  without a referent. The question is embedded on its own to search with, so a
  question that only makes sense beside this excerpt cannot be retrieved by
  anything.
- Specific enough to find. Carry the distinctive nouns of the subject.
- The quote is COPIED from the excerpt, character for character, contiguous,
  at most {limit} characters, and contains the evidence for the answer.

If the excerpt holds no self-contained fact worth asking about — a table of
contents, a running header, a reference list, a fragment — set usable to false
and leave the other fields empty.

Excerpt:
{text}"""


def choose_chunks(chunks: list[dict], total: int, seed: int = SEED) -> list[dict]:
    """A deterministic sample with every document represented.

    Uniform random over a corpus this size would usually cover all four
    documents anyway. "Usually" is not a property worth having in the reference
    set that every later comparison is measured against, so one chunk per
    document is taken first and the rest drawn from what is left.

    The seed is fixed in code, not configurable: a dataset you cannot rebuild
    identically is not a fixed reference, and a tunable seed invites rerolling
    until the numbers look better.
    """
    rng = random.Random(seed)
    ordered = sorted(chunks, key=lambda c: (c["source"], c["text"]))

    by_source: dict[str, list[dict]] = {}
    for chunk in ordered:
        by_source.setdefault(chunk["source"], []).append(chunk)

    chosen = [rng.choice(group) for _, group in sorted(by_source.items())]
    remaining = [c for c in ordered if c not in chosen]
    chosen += rng.sample(remaining, min(total - len(chosen), len(remaining)))
    return chosen[:total]


def make_generator(client, model: str):
    """Build the function that turns one chunk into an example, or nothing."""

    def generate(chunk: dict) -> dict | None:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": GENERATOR_PROMPT.format(limit=QUOTE_LIMIT, text=chunk["text"]),
                }
            ],
            temperature=0,
            response_format={"type": "json_schema", "json_schema": GENERATOR_SCHEMA},
        )
        try:
            written = json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, TypeError):
            return None

        if not written.get("usable"):
            return None

        quote = written["quote"]
        # Validated here rather than trusted. Models tidy quotes instead of
        # copying them, and an unverifiable quote scores a miss for every
        # configuration equally — which looks like bad retrieval rather than a
        # bad example, and is the hardest kind of mistake to notice later.
        if not quote or len(quote) > QUOTE_LIMIT or not supports(chunk["text"], quote):
            return None

        return {
            "question": written["question"],
            "expected_answer": written["expected_answer"],
            "quote": quote,
            "source": chunk["source"],
            "page": chunk.get("page"),
        }

    return generate


def push(client, dataset_name: str, examples: list[dict]):
    """Put the examples in LangSmith, which owns them from here on.

    `inputs` is what rag_query is given; `outputs` is what the evaluators check
    against. The split matters — evaluate() passes them to an evaluator as
    `inputs` and `reference_outputs` respectively, so the question must be in
    one and the quote in the other.

    Deliberately no local copy is kept. Two sources of truth for a reference set
    is one more than the number that can be right.
    """
    if client.has_dataset(dataset_name=dataset_name):
        dataset = client.read_dataset(dataset_name=dataset_name)
    else:
        dataset = client.create_dataset(
            dataset_name,
            description=(
                "Questions generated from the project 01 corpus, each carrying "
                "the verbatim quote its answer should come from."
            ),
        )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[
            {
                "inputs": {"question": e["question"]},
                "outputs": {
                    "expected_answer": e["expected_answer"],
                    "quote": e["quote"],
                },
                "metadata": {"source": e["source"], "page": e["page"]},
            }
            for e in examples
        ],
    )
    return dataset


GOLDEN_EXAMPLES = 20


def read_chunks(qdrant_client, collection_name: str) -> list[dict]:
    """Every indexed chunk, with the metadata an example needs.

    Read back rather than re-derived from the PDFs, so the text sampled is
    exactly the text retrieval searches.
    """
    points, _ = qdrant_client.scroll(
        collection_name=collection_name, limit=10_000, with_payload=True, with_vectors=False
    )
    return [
        {
            "source": (p.payload.get("metadata") or {}).get("source", "unknown"),
            "page": (p.payload.get("metadata") or {}).get("page"),
            "text": p.payload["page_content"],
        }
        for p in points
    ]
