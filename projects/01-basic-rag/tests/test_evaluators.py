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
