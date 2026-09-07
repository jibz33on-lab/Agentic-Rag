"""Turns raw results into the numbers an evaluation_run reports.

This module has no dependencies — no network, no client, no config. That is
deliberate. The four denominator rules below are where a quiet arithmetic bug
would live, and a pure module means every one of them is testable with a list
of dicts and no API key.

The rules, once, here:

  failed    a rag_query that raised. Excluded from every quality metric and
            reported as failure_rate. Counting it as a miss would count it
            twice and make two runs of one config differ on the provider's mood.
  unjudged  the judge returned nothing parseable. Retrieval still scores;
            generation does not. Coercing it to incorrect would make a broken
            judge look like a bad answerer.
  retrieval over everything that completed — it needs no judge, so a judge
            failure must not shrink its denominator.
  generation over what was judged, reported twice: overall, and conditional on
            retrieval having hit. The conditional denominator moves between
            configurations, so its size is always reported beside it.
"""

import re
import unicodedata


def normalise(text: str) -> str:
    """Flatten the differences that are not differences.

    NFKC folds ligatures — a PDF's "ﬁ" becomes "fi" — and collapsing whitespace
    turns a table row split across columns and newlines into the one sentence a
    quote is written as. Without this, a quote that is genuinely present scores
    a miss, and 60 of them look like terrible retrieval rather than a broken
    ruler.

    Case is preserved. Quotes are copied, not composed, and lowercasing would
    hide a generator that paraphrases instead of quoting.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def supports(chunk_text: str, quote: str) -> bool:
    """Does this chunk contain the span the golden_example was written from?"""
    return normalise(quote) in normalise(chunk_text)


def score_retrieval(chunk_texts: list[str], quote: str) -> tuple[bool, int | None]:
    """Find the first chunk supporting `quote`, and where it ranked.

    Rank is 1-based and counts position in the retrieved order, which is what
    makes MRR mean "how far down the list was the evidence".
    """
    for rank, text in enumerate(chunk_texts, 1):
        if supports(text, quote):
            return True, rank
    return False, None


def summarise(results: list[dict]) -> dict:
    """Aggregate one evaluation_run's results into the reported numbers."""
    attempted = len(results)
    completed = [r for r in results if r.get("status") != "failed"]
    judged = [r for r in completed if r.get("status") == "completed"]
    hits = [r for r in judged if r.get("hit")]

    def rate(part, whole):
        return len(part) / len(whole) if whole else 0.0

    def correct(group):
        return [r for r in group if r.get("verdict") == "correct"]

    return {
        "attempted": attempted,
        "completed": len(completed),
        "judged": len(judged),
        "failure_rate": (attempted - len(completed)) / attempted if attempted else 0.0,
        "unjudged_rate": (len(completed) - len(judged)) / len(completed) if completed else 0.0,
        # Retrieval: over everything that completed, judged or not.
        "hit_rate": rate([r for r in completed if r.get("hit")], completed),
        "mrr": (
            sum(1 / r["rank"] for r in completed if r.get("rank")) / len(completed)
            if completed
            else 0.0
        ),
        # Generation: over what was judged. `declined` is never `correct` — it
        # is correct behaviour, which declined_rate reports separately.
        "accuracy_overall": rate(correct(judged), judged),
        "accuracy_conditional": rate(correct(hits), hits),
        "conditional_n": len(hits),
        "grounded_rate": rate([r for r in judged if r.get("grounded")], judged),
        "declined_rate": rate([r for r in judged if r.get("verdict") == "declined"], judged),
        # Raw counts, not rates: at 60 examples a percentage implies a
        # precision these do not have.
        "working": len(
            [
                r
                for r in judged
                if r.get("hit") and r.get("verdict") == "correct" and r.get("grounded")
            ]
        ),
        "misread": len([r for r in judged if r.get("hit") and r.get("verdict") == "incorrect"]),
        "correct_refusal": len(
            [r for r in judged if not r.get("hit") and r.get("verdict") == "declined"]
        ),
        # The row nothing else can see: right answer, wrong reason.
        "answered_blind": len(
            [
                r
                for r in judged
                if not r.get("hit") and r.get("verdict") == "correct" and not r.get("grounded")
            ]
        ),
    }
