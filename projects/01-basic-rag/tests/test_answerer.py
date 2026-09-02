from answerer import build_prompt
from langchain_core.documents import Document


def test_prompt_includes_the_question_and_the_chunks():
    chunks = [Document(page_content="hybrid search runs both searches in parallel")]

    prompt = build_prompt("what is hybrid search?", chunks)

    assert "hybrid search runs both searches in parallel" in prompt
    assert "what is hybrid search?" in prompt
