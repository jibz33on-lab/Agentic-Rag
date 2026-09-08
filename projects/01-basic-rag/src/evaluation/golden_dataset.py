"""Builds the golden dataset from our corpus and pushes it to LangSmith.

LangSmith owns the dataset once it is there — versions, edits, and every
experiment run against it. What it cannot do is invent corpus-specific questions
from our PDFs, which is the only reason this module exists.

    chunks -> sample -> generate -> validate the quotes -> LangSmith Dataset

Two kinds of example. A single-chunk one asks something one excerpt answers.
A multi-chunk one asks something no single excerpt answers, so retrieval has to
return several. Both carry the same shape: a `quotes` list, one entry per chunk
the answer needs.
"""

import json
import random

import numpy as np

from .evaluators import supports

SEED = 0
QUOTE_LIMIT = 200
MIN_GROUP = 2
MAX_GROUP = 4

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
- The expected_answer is a COMPLETE, standalone sentence answering the question
  in your own words. Not copied from the excerpt, not a sentence fragment, and
  it must read sensibly on its own without the excerpt beside it.
- The quote is COPIED from the excerpt, character for character, contiguous,
  at most {limit} characters, and contains the evidence for the answer.

If the excerpt holds no self-contained fact worth asking about — a table of
contents, a running header, a reference list, a fragment — set usable to false
and leave the other fields empty.

Excerpt:
{text}"""


MULTI_SCHEMA = {
    "name": "multi_chunk_example",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "usable": {"type": "boolean"},
            "question": {"type": "string"},
            "expected_answer": {"type": "string"},
            "quotes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["usable", "question", "expected_answer", "quotes"],
        "additionalProperties": False,
    },
}

MULTI_PROMPT = """Write one question that needs ALL of the excerpts below to answer.

Rules:
- The question must NOT be fully answerable from any single excerpt on its own.
  Each excerpt must contribute something the others do not. If the excerpts have
  no such question between them, set usable to false.
- Self-contained. No "according to the text", no "in this document", no pronoun
  without a referent. The question is embedded on its own to search with.
- Specific enough to find. Carry the distinctive nouns of the subject.
- The expected_answer is a COMPLETE, standalone sentence combining what the
  excerpts say, in your own words. Not copied, not a fragment.
- Give exactly one quote per excerpt, in the same order. Each is COPIED from its
  own excerpt, character for character, contiguous, at most {limit} characters,
  and carries that excerpt's contribution to the answer.

Excerpts:
{excerpts}"""

NECESSITY_SCHEMA = {
    "name": "necessity_check",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answerable_from_one": {"type": "boolean"},
            "which": {"type": "integer"},
        },
        "required": ["answerable_from_one", "which"],
        "additionalProperties": False,
    },
}

NECESSITY_PROMPT = """Can this question be COMPLETELY answered using only ONE of the
excerpts below?

Say yes only if a single excerpt on its own contains everything needed for a
full answer. Partial relevance is not enough. Give its number in `which`, or -1.

Question: {question}

{excerpts}"""


def choose_related_groups(
    chunks: list[dict], groups: int, seed: int = SEED, size: int | None = None
) -> list[list[dict]]:
    """Pick groups of related chunks, two to four each, by vector similarity.

    Related rather than random: a question spanning two unrelated chunks is a
    question nobody would ask, and would test nothing except whether the
    retriever can be confused.

    The vectors are the ones already in Qdrant, so this costs no API calls and
    clusters by the same geometry retrieval searches. Group sizes vary because
    a two-chunk question is a genuinely easier test than a four-chunk one, and
    a dataset of only four-chunk questions would measure one difficulty.

    `size` fixes the group size instead of drawing it, so a benchmark can ask
    for a deliberate mix rather than whatever the seed happened to produce.
    """
    rng = random.Random(seed)
    pool = [c for c in sorted(chunks, key=lambda c: (c["source"], c["text"])) if c.get("vector")]
    if len(pool) < MIN_GROUP:
        return []

    vectors = np.array([c["vector"] for c in pool], dtype=float)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    taken: set[int] = set()
    out: list[list[dict]] = []
    for _ in range(groups):
        free = [i for i in range(len(pool)) if i not in taken]
        if len(free) < MIN_GROUP:
            break
        anchor = rng.choice(free)
        wanted = size if size is not None else rng.randint(MIN_GROUP, MAX_GROUP)
        similarity = vectors @ vectors[anchor]
        nearest = sorted(free, key=lambda i: (-similarity[i], i))[:wanted]
        if len(nearest) < MIN_GROUP:
            break
        taken.update(nearest)
        out.append([pool[i] for i in nearest])
    return out


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

        # The prompt asks for an answer in the model's own words; this is the
        # constraint behind the request. An expected_answer that is just the
        # quote makes the judge compare the answer against the source text
        # itself, so "correct" scores far more easily than it should.
        answer = written["expected_answer"].strip()
        if not answer or answer == quote.strip():
            return None

        return {
            "question": written["question"],
            "expected_answer": answer,
            # One shape for both kinds. A single-chunk example is simply a
            # group of one, so nothing downstream has to branch.
            "quote": quote,
            "quotes": [quote],
            "chunk_count": 1,
            "source": chunk["source"],
            "page": chunk.get("page"),
            "sources": [chunk["source"]],
            "pages": [chunk.get("page")],
        }

    return generate


def _trim(quote: str) -> str:
    """Cut a quote down to the limit without breaking it.

    Models copy faithfully and then ignore the character budget — measured at
    245 to 785 characters against a 200 limit, every one of them verbatim. A
    prefix of a verbatim span is still a verbatim span, so trimming keeps the
    quote matchable where rejecting would throw away a usable example.

    Trimmed at a word boundary where there is one, because these quotes are
    read by people as well as matched by code, and a quote ending mid-word
    reads as a bug rather than a budget.
    """
    quote = quote.strip()
    if len(quote) <= QUOTE_LIMIT:
        return quote
    cut = quote[:QUOTE_LIMIT]
    spaced = cut.rsplit(" ", 1)[0]
    return spaced if len(spaced) > QUOTE_LIMIT // 2 else cut


def make_multi_generator(client, model: str):
    """Build the function that turns a group of chunks into one example.

    Returns None when the group yields nothing usable — including when the
    question it produced turns out to be answerable from a single excerpt after
    all, which is the failure this whole thing exists to avoid.
    """

    def _numbered(group: list[dict]) -> str:
        return "\n\n".join(f"[{i}] {c['text']}" for i, c in enumerate(group))

    def _ask(prompt: str, schema: dict) -> dict | None:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        try:
            return json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, TypeError):
            return None

    def generate(group: list[dict]) -> dict | None:
        written = _ask(
            MULTI_PROMPT.format(limit=QUOTE_LIMIT, excerpts=_numbered(group)), MULTI_SCHEMA
        )
        if written is None or not written.get("usable"):
            return None

        quotes = [_trim(q) for q in written.get("quotes") or []]
        # One quote per chunk, each verifiable in its own chunk. Fewer quotes
        # than chunks means at least one chunk is not actually required, and
        # the example is not the thing it claims to be.
        if len(quotes) != len(group):
            return None
        for quote, chunk in zip(quotes, group, strict=True):
            if not quote or not supports(chunk["text"], quote):
                return None

        answer = written["expected_answer"].strip()
        if not answer or answer in quotes:
            return None

        # The generator was asked for a question needing every excerpt. Asking
        # is not evidence. This is the check behind the request, and it is a
        # separate call so the model is not marking its own homework in the
        # same breath it did the work.
        verdict = _ask(
            NECESSITY_PROMPT.format(question=written["question"], excerpts=_numbered(group)),
            NECESSITY_SCHEMA,
        )
        if verdict is None or verdict.get("answerable_from_one"):
            return None

        return {
            "question": written["question"],
            "expected_answer": answer,
            # quotes[0] is repeated as `quote` so the existing evidence
            # evaluator keeps working. It scores one quote, not all of them —
            # using the full list needs a change to evaluators.py.
            "quote": quotes[0],
            "quotes": quotes,
            "chunk_count": len(group),
            "source": group[0]["source"],
            "page": group[0].get("page"),
            "sources": [c["source"] for c in group],
            "pages": [c.get("page") for c in group],
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
                    "quotes": e["quotes"],
                },
                "metadata": {
                    "source": e["source"],
                    "page": e["page"],
                    "chunk_count": e["chunk_count"],
                    "sources": e["sources"],
                    "pages": e["pages"],
                },
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
        collection_name=collection_name, limit=10_000, with_payload=True, with_vectors=True
    )
    return [
        {
            "source": (p.payload.get("metadata") or {}).get("source", "unknown"),
            "page": (p.payload.get("metadata") or {}).get("page"),
            "text": p.payload["page_content"],
            # Carried so related chunks can be grouped without re-embedding or
            # a second round trip. Same vectors retrieval searches.
            "vector": p.vector,
        }
        for p in points
    ]
