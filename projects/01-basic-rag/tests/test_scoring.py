from evaluation.scoring import summarise, supports

TABLE_CHUNK = (
    "Symptom Missing layer Fix\n"
    "DB CPU pegged, mostly from SELECTs\nNo read scaling\nRead replicas\n"
)


def test_matches_a_quote_across_collapsed_whitespace():
    """The real case this rule exists for: a PDF table row, where the columns
    arrive separated by newlines and the quote reads as one sentence."""
    quote = "DB CPU pegged, mostly from SELECTs No read scaling Read replicas"

    assert supports(TABLE_CHUNK, quote) is True


def test_does_not_match_a_quote_that_is_absent():
    assert supports(TABLE_CHUNK, "sharding splits writes across shards") is False


def _result(**overrides):
    base = {"status": "completed", "hit": True, "rank": 1, "verdict": "correct", "grounded": True}
    return {**base, **overrides}


def test_hit_rate_and_mrr_count_the_rank_of_the_first_supporting_chunk():
    results = [_result(hit=True, rank=1), _result(hit=True, rank=4), _result(hit=False, rank=None)]

    summary = summarise(results)

    assert summary["hit_rate"] == 2 / 3
    assert summary["mrr"] == (1 / 1 + 1 / 4 + 0) / 3


def test_failures_are_excluded_from_quality_and_reported_on_their_own():
    """Counting a provider timeout as a retrieval miss would count it twice —
    it is already the failure_rate — and would make two runs of one config
    differ on the provider's mood."""
    results = [_result(hit=True, rank=1), {"status": "failed", "error": "timeout"}]

    summary = summarise(results)

    assert summary["hit_rate"] == 1.0
    assert summary["failure_rate"] == 0.5
    assert summary["completed"] == 1


def test_unjudged_examples_still_score_retrieval_but_not_generation():
    """A judge that returned nothing parseable says nothing about the answerer.
    Coercing it to incorrect would make a broken judge look like a bad model."""
    results = [_result(), _result(status="unjudged", verdict=None, grounded=None)]

    summary = summarise(results)

    assert summary["hit_rate"] == 1.0
    assert summary["judged"] == 1
    assert summary["unjudged_rate"] == 0.5
    assert summary["accuracy_overall"] == 1.0


def test_conditional_accuracy_is_reported_with_the_size_of_its_denominator():
    """Its denominator moves between configurations, so the number is
    meaningless travelling alone."""
    results = [
        _result(hit=True, verdict="correct"),
        _result(hit=True, verdict="incorrect"),
        _result(hit=False, rank=None, verdict="declined"),
    ]

    summary = summarise(results)

    assert summary["accuracy_conditional"] == 0.5
    assert summary["conditional_n"] == 2
    assert summary["accuracy_overall"] == 1 / 3


def test_a_declined_answer_is_not_counted_correct():
    """Declining is correct behaviour under bad retrieval, not a correct
    answer. It shows up in declined_rate, never in accuracy."""
    results = [_result(hit=False, rank=None, verdict="declined", grounded=True)]

    summary = summarise(results)

    assert summary["accuracy_overall"] == 0.0
    assert summary["declined_rate"] == 1.0


def test_counts_answers_that_were_right_without_the_evidence():
    """Retrieval missed, the answer was right anyway, and it was not grounded —
    the model answered from its own knowledge. Looks like a pass, is a failure,
    and no other number in this summary can see it."""
    results = [
        _result(hit=False, rank=None, verdict="correct", grounded=False),
        _result(hit=True, rank=1, verdict="correct", grounded=True),
    ]

    summary = summarise(results)

    assert summary["answered_blind"] == 1
    assert summary["working"] == 1
