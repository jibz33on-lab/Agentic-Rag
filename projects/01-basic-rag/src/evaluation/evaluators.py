"""The evaluation logic LangSmith cannot supply.

Everything else — running the experiment, storing the dataset, recording traces,
tokens, latency and score aggregation — is LangSmith's. What is left here is the
part that depends on our corpus: what counts as evidence for an answer.
"""

import json
import re
import unicodedata


def normalise(text: str) -> str:
    """Flatten the differences that are not differences.

    NFKC folds ligatures — a PDF's "ﬁ" becomes "fi" — and collapsing whitespace
    turns a table row split across columns and newlines into the one sentence a
    quote is written as. Without this, a quote that is genuinely present scores
    a miss, and a whole dataset of them looks like terrible retrieval rather
    than a broken ruler.

    Case is preserved. Quotes are copied, not composed, and lowercasing would
    hide a generator that paraphrases instead of quoting.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def supports(chunk_text: str, quote: str) -> bool:
    """Does this chunk contain the span the example was written from?"""
    return normalise(quote) in normalise(chunk_text)


def find_evidence(chunk_texts: list[str], quote: str) -> int | None:
    """Where in the retrieved order the evidence turned up, 1-based.

    None when no retrieved chunk contains it. The rank matters as well as the
    hit: evidence at position four is worse than evidence at position one, and
    a change that moves it up is an improvement a boolean cannot see.
    """
    for rank, text in enumerate(chunk_texts, 1):
        if supports(text, quote):
            return rank
    return None


def evidence_ranks(chunk_texts: list[str], reference_outputs: dict) -> list[int | None]:
    """Where each piece of required evidence turned up, in retrieved order.

    One entry per quote the example needs, None where it was not retrieved.

    A single-chunk example is read as a one-element list: examples written
    before multi-chunk support carry `quote` and no `quotes`, and this keeps
    their scores exactly as they were.

    Both the evidence evaluator and the judge call this, so they cannot drift
    into disagreeing about whether the same run had its evidence.
    """
    quotes = reference_outputs.get("quotes") or [reference_outputs["quote"]]
    return [find_evidence(chunk_texts, quote) for quote in quotes]


def evidence(outputs: dict, reference_outputs: dict) -> dict:
    """Did retrieval find the text the answer was supposed to come from?

    A LangSmith evaluator: the argument names are the contract, and `evaluate()`
    fills them from the target's output and the dataset example.

    Three scores:

    `evidence_found` is all-or-nothing. A question needing three chunks is not
    served by two of them, so this asks whether the answerer had everything it
    needed, not whether it had something.

    `evidence_recall` is the fraction retrieved — the difference between
    retrieval being broken and retrieval being one chunk short.

    `evidence_rank_reciprocal` uses the DEEPEST required rank, because that is
    the smallest TOP_K that would have retrieved every piece. Zero when any is
    missing: no TOP_K would have been enough. For one quote this is exactly the
    old 1/rank.
    """
    ranks = evidence_ranks(outputs["chunk_texts"], reference_outputs)
    retrieved = [rank for rank in ranks if rank is not None]
    complete = len(retrieved) == len(ranks)
    return {
        "results": [
            {"key": "evidence_found", "score": int(complete)},
            {"key": "evidence_recall", "score": len(retrieved) / len(ranks)},
            {
                "key": "evidence_rank_reciprocal",
                "score": 1 / max(retrieved) if complete else 0,
            },
        ]
    }


JUDGE_SCHEMA = {
    "name": "judgement",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["correct", "incorrect", "declined"]},
            "grounded": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["verdict", "grounded", "reason"],
        "additionalProperties": False,
    },
}

JUDGE_PROMPT = """You are scoring one answer from a retrieval-augmented system.

Verdict:
- correct   — conveys the same facts as the expected answer. Wording may differ.
- declined  — says the excerpts do not contain the answer. This is correct
              behaviour when the excerpts genuinely lack it, not a wrong answer.
- incorrect — anything else, including a partly right answer that asserts
              something false.

Grounded: is every factual claim in the answer supported by the excerpts below?
An answer that is right but unsupported by them is NOT grounded.

Question: {question}

Expected answer: {expected_answer}

Excerpts the system was given:
{excerpts}

Answer given: {answer}"""


def make_judge(client, model: str):
    """Build the LangSmith evaluator that scores an answer.

    A factory rather than a plain function because the evaluator's argument
    names are LangSmith's contract — it fills `inputs`, `outputs` and
    `reference_outputs` by name — so the client and model have to be closed
    over rather than passed in.

    The judge is never shown the expected `quote`. Groundedness must be judged
    against the excerpts the answerer actually received; showing it the golden
    evidence would have it check against text the answerer may never have seen,
    and would make the answered-blind case unreachable.
    """

    def judge(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        excerpts = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(outputs["chunk_texts"], 1))
        prompt = JUDGE_PROMPT.format(
            question=inputs["question"],
            expected_answer=reference_outputs["expected_answer"],
            excerpts=excerpts,
            answer=outputs["answer"],
        )

        judgement = _ask_judge(client, model, prompt)
        if judgement is None:
            # Retried and still unparseable. No feedback at all, which drops
            # this example from the averages. Coercing it to incorrect would
            # make a broken judge look like a bad answerer.
            return {"results": []}

        correct = int(judgement["verdict"] == "correct")
        grounded = int(judgement["grounded"])
        # The same definition evidence_found uses, via the same function —
        # partial evidence is not evidence, and the two scores must not
        # disagree about the same run.
        ranks = evidence_ranks(outputs["chunk_texts"], reference_outputs)
        found = all(rank is not None for rank in ranks)
        comment = judgement["reason"]

        results = [
            {"key": "correct", "score": correct, "comment": comment},
            {"key": "grounded", "score": grounded, "comment": comment},
        ]
        # Emitted for a subset on purpose. LangSmith averages a key over the
        # runs that carry it, so these means come out conditional without any
        # aggregation code of ours.
        if found:
            results.append({"key": "correct_given_evidence", "score": correct})
        else:
            results.append({"key": "answered_blind", "score": int(correct and not grounded)})
        return {"results": results}

    return judge


def _ask_judge(client, model: str, prompt: str) -> dict | None:
    """One judgement, retried once. None when it still will not parse."""
    for _ in range(2):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_schema", "json_schema": JUDGE_SCHEMA},
        )
        try:
            return json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, TypeError):
            continue
    return None
