from evaluation.evaluators import evidence, make_judge, supports

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


def test_scores_evidence_by_where_it_was_retrieved():
    """Rank matters as well as presence: evidence at position four is worse
    than at position one, and a change that moves it up is an improvement a
    boolean cannot see."""
    outputs = {"chunk_texts": ["nothing here", TABLE_CHUNK]}
    reference = {"quote": "DB CPU pegged, mostly from SELECTs No read scaling"}

    scores = {r["key"]: r["score"] for r in evidence(outputs, reference)["results"]}

    assert scores["evidence_found"] == 1
    assert scores["evidence_rank_reciprocal"] == 0.5


def test_scores_evidence_as_absent_when_no_chunk_contains_the_quote():
    outputs = {"chunk_texts": ["nothing here", "nor here"]}
    reference = {"quote": "sharding splits writes across shards"}

    scores = {r["key"]: r["score"] for r in evidence(outputs, reference)["results"]}

    assert scores["evidence_found"] == 0
    assert scores["evidence_rank_reciprocal"] == 0


class FakeResponse:
    def __init__(self, content):
        message = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": message})()]


class FakeOpenAI:
    """Returns scripted completions, one per call, then repeats the last."""

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = 0

        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls += 1
                return FakeResponse(outer.contents[min(outer.calls - 1, len(outer.contents) - 1)])

        self.chat = type("Chat", (), {"completions": Completions()})()


FOUND = {"chunk_texts": [TABLE_CHUNK]}
MISSED = {"chunk_texts": ["nothing relevant here"]}
REFERENCE = {
    "quote": "DB CPU pegged, mostly from SELECTs No read scaling",
    "expected_answer": "Read scaling is missing; the fix is read replicas.",
}


def _scores(result):
    return {r["key"]: r["score"] for r in result["results"]}


def test_scores_correctness_conditionally_when_the_evidence_was_retrieved():
    """correct_given_evidence is emitted only for examples where the answerer
    actually had the right text. LangSmith averages a key over the runs that
    carry it, so that mean is the conditional accuracy and its count is the
    denominator — no aggregation code of ours."""
    client = FakeOpenAI('{"verdict": "correct", "grounded": true, "reason": "matches"}')
    judge = make_judge(client, "test-model")

    scores = _scores(judge({"question": "q"}, {**FOUND, "answer": "a"}, REFERENCE))

    assert scores["correct"] == 1
    assert scores["correct_given_evidence"] == 1
    assert "answered_blind" not in scores


def test_flags_an_answer_that_was_right_without_the_evidence():
    """Evidence missing, answer correct, not grounded — the model answered from
    its own knowledge. Reads as a pass, is a failure."""
    client = FakeOpenAI('{"verdict": "correct", "grounded": false, "reason": "not in excerpts"}')
    judge = make_judge(client, "test-model")

    scores = _scores(judge({"question": "q"}, {**MISSED, "answer": "a"}, REFERENCE))

    assert scores["answered_blind"] == 1
    assert "correct_given_evidence" not in scores


def test_a_declined_answer_is_not_counted_correct():
    """Refusing when the excerpts lack the answer is what the prompt demands.
    Marking it wrong would point the metric backwards."""
    client = FakeOpenAI('{"verdict": "declined", "grounded": true, "reason": "said so"}')
    judge = make_judge(client, "test-model")

    scores = _scores(judge({"question": "q"}, {**MISSED, "answer": "not here"}, REFERENCE))

    assert scores["correct"] == 0
    assert scores["answered_blind"] == 0


def test_retries_once_then_emits_no_scores_at_all():
    """A judge that cannot be parsed says nothing about the answerer. Emitting
    no feedback drops the example from the averages; coercing it to incorrect
    would make a broken judge look like a bad model."""
    client = FakeOpenAI("not json", "still not json")
    judge = make_judge(client, "test-model")

    result = judge({"question": "q"}, {**FOUND, "answer": "a"}, REFERENCE)

    assert result["results"] == []
    assert client.calls == 2


# --- multi-chunk evidence ---------------------------------------------------

Q1 = "alpha evidence one"
Q2 = "beta evidence two"
Q3 = "gamma evidence three"
FILLER = "nothing relevant here"


def test_single_chunk_example_keeps_its_current_meaning():
    """The 15 existing examples carry `quote` and no `quotes`. A single quote is
    read as a one-element evidence list, so their scores are unchanged."""
    outputs = {"chunk_texts": [FILLER, Q1]}

    scores = _scores(evidence(outputs, {"quote": Q1}))

    assert scores["evidence_found"] == 1
    assert scores["evidence_recall"] == 1.0
    assert scores["evidence_rank_reciprocal"] == 0.5


def test_multi_chunk_example_with_every_quote_retrieved():
    outputs = {"chunk_texts": [Q1, FILLER, Q2]}

    scores = _scores(evidence(outputs, {"quote": Q1, "quotes": [Q1, Q2]}))

    assert scores["evidence_found"] == 1
    assert scores["evidence_recall"] == 1.0


def test_multi_chunk_example_missing_one_quote_is_not_found():
    """All-or-nothing: the question needs both chunks, so retrieving one is not
    'the model had what it needed'."""
    outputs = {"chunk_texts": [Q1, FILLER]}

    scores = _scores(evidence(outputs, {"quote": Q1, "quotes": [Q1, Q2]}))

    assert scores["evidence_found"] == 0


def test_evidence_recall_gives_partial_credit():
    """The strict score says pass or fail; recall says how close it came, which
    is the difference between 'retrieval is broken' and 'retrieval is short'."""
    outputs = {"chunk_texts": [Q1, FILLER]}

    scores = _scores(evidence(outputs, {"quote": Q1, "quotes": [Q1, Q2]}))

    assert scores["evidence_recall"] == 0.5


def test_rank_reciprocal_uses_the_deepest_required_rank():
    """max(rank) is the smallest TOP_K that would have retrieved everything, so
    its reciprocal is the reciprocal of the TOP_K this question actually needs."""
    outputs = {"chunk_texts": [Q1, Q2, Q3]}

    scores = _scores(evidence(outputs, {"quote": Q1, "quotes": [Q1, Q2, Q3]}))

    assert scores["evidence_rank_reciprocal"] == 1 / 3


def test_rank_reciprocal_is_zero_when_any_required_evidence_is_missing():
    """There is no TOP_K that would have retrieved it all."""
    outputs = {"chunk_texts": [Q1, Q2]}

    scores = _scores(evidence(outputs, {"quote": Q1, "quotes": [Q1, Q2, Q3]}))

    assert scores["evidence_rank_reciprocal"] == 0


def test_judge_requires_all_evidence_before_scoring_conditionally():
    """The judge's conditional must use the same definition as evidence_found,
    or the two disagree about the same run. Partial evidence is not evidence."""
    client = FakeOpenAI('{"verdict": "correct", "grounded": false, "reason": "r"}')
    judge = make_judge(client, "test-model")
    outputs = {"chunk_texts": [Q1, FILLER], "answer": "a"}
    reference = {"quote": Q1, "quotes": [Q1, Q2], "expected_answer": "x"}

    scores = _scores(judge({"question": "q"}, outputs, reference))

    assert "correct_given_evidence" not in scores
    assert scores["answered_blind"] == 1
