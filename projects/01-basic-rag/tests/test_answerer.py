import pytest
from answerer import build_chat_model, build_prompt, stream_answer
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from openai import APIError
from prompts import BASELINE_PROMPT


class CapturingModel:
    """Records the prompt it was asked to stream."""

    def __init__(self):
        self.streamed = None

    def stream(self, prompt):
        self.streamed = prompt
        yield AIMessage(content="an answer")


def test_renders_with_the_prompt_it_is_given_not_the_baseline():
    chunks = [Document(page_content="anything")]

    prompt = build_prompt("what is it?", chunks, "ONLY-THIS {excerpts} {question}")

    assert "ONLY-THIS" in prompt
    assert "Answer the question using only the excerpts below." not in prompt


def test_streams_the_prompt_it_is_given_not_the_baseline():
    model = CapturingModel()
    chunks = [Document(page_content="anything")]

    list(stream_answer("what is it?", chunks, model, "MARKER {excerpts} {question}"))

    assert "MARKER" in model.streamed
    assert "Answer the question using only the excerpts below." not in model.streamed


def test_prompt_includes_the_question_and_the_chunks():
    chunks = [Document(page_content="hybrid search runs both searches in parallel")]

    prompt = build_prompt("what is hybrid search?", chunks, BASELINE_PROMPT)

    assert "hybrid search runs both searches in parallel" in prompt
    assert "what is hybrid search?" in prompt


def test_streams_the_answer_in_pieces():
    model = FakeListChatModel(responses=["hybrid search runs both"])
    chunks = [Document(page_content="anything")]

    pieces = list(stream_answer("what is it?", chunks, model, BASELINE_PROMPT))

    assert len(pieces) > 1
    assert "".join(pieces) == "hybrid search runs both"


def test_keeps_the_openrouter_cost_that_langchain_drops(live_openrouter_config):
    """OpenRouter reports the real cost; LangChain's usage_metadata has no slot
    for it, so it is dropped. If this ever stops being captured, the cost column
    in every evaluation_run silently empties — hence a test rather than a note.
    """
    model = build_chat_model(live_openrouter_config)

    list(model.stream("Say the word yes."))

    assert model.last_usage is not None
    assert model.last_usage.get("cost") is not None


def test_forgets_the_previous_cost_when_a_request_fails(live_openrouter_config):
    """A failed request must not inherit the last one's cost.

    The captured usage lives on the model instance, so without a reset a
    request that dies before reporting usage leaves the previous question's
    figure in place — and an evaluation_run would attribute it to the wrong
    golden_example, silently.
    """
    model = build_chat_model(live_openrouter_config)
    model.model_name = "definitely/not-a-real-model"
    model.last_usage = {"cost": 99.0}

    with pytest.raises(APIError):
        list(model.stream("Say the word yes."))

    assert model.last_usage is None
