import pytest
from guardrails import NoAnswerError, check_answer_is_not_empty


def test_raises_when_the_answer_is_empty():
    with pytest.raises(NoAnswerError):
        check_answer_is_not_empty("")


def test_raises_when_the_answer_is_only_whitespace():
    with pytest.raises(NoAnswerError):
        check_answer_is_not_empty("   \n  ")


def test_accepts_a_real_answer():
    check_answer_is_not_empty("hybrid search combines keyword and vector results")
