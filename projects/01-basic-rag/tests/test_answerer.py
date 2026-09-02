from answerer import build_prompt, stream_answer
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


def test_prompt_includes_the_question_and_the_chunks():
    chunks = [Document(page_content="hybrid search runs both searches in parallel")]

    prompt = build_prompt("what is hybrid search?", chunks)

    assert "hybrid search runs both searches in parallel" in prompt
    assert "what is hybrid search?" in prompt


def test_streams_the_answer_in_pieces():
    model = FakeListChatModel(responses=["hybrid search runs both"])
    chunks = [Document(page_content="anything")]

    pieces = list(stream_answer("what is it?", chunks, model))

    assert len(pieces) > 1
    assert "".join(pieces) == "hybrid search runs both"
