import pytest
from prompts import resolve_prompt


def test_resolves_baseline_to_the_frozen_answerer_prompt():
    prompt = resolve_prompt("baseline")

    assert "Answer the question using only the excerpts below." in prompt
    assert "{excerpts}" in prompt
    assert "{question}" in prompt


def test_rejects_an_unknown_answerer_prompt_name():
    with pytest.raises(ValueError) as error:
        resolve_prompt("not-a-prompt")

    assert "not-a-prompt" in str(error.value)
    assert "baseline" in str(error.value)


def test_v1_keeps_the_baseline_evidence_rules():
    prompt = resolve_prompt("v1")

    assert "senior AI engineer" in prompt
    assert "Answer the question using only the excerpts below." in prompt
    assert "Do not fill gaps" in prompt
    assert "{excerpts}" in prompt
    assert "{question}" in prompt
