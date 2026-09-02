"""Turns a question plus retrieved chunks into an answer."""

from collections.abc import Iterator

from config import Config
from guardrails import check_answer_is_not_empty
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

PROMPT = """Answer the question using only the excerpts below.

If the excerpts do not contain the answer, say so plainly. Do not fill gaps
from your own knowledge — the point of these excerpts is that the answer comes
from the user's own documents, not from you.

Excerpts:
{excerpts}

Question: {question}

Answer:"""


def build_chat_model(config: Config) -> ChatOpenAI:
    """The chat model, served by OpenRouter.

    Reasoning is switched off. It is on by default — we never asked for it —
    and it costs about 1.5 seconds before any answer starts, because the model
    thinks first and that thinking is not shown. Worse, it sometimes wanders
    off and returns no answer at all.

    LangChain has no parameter for this because it is an OpenRouter feature,
    so it goes through extra_body, which passes options straight to the
    provider. It is also why the thinking was invisible: LangChain reads the
    stream, keeps `content`, and silently drops the `reasoning` field.
    """
    return ChatOpenAI(
        model=config.llm_model,
        api_key=config.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
        temperature=0,
        extra_body={"reasoning": {"enabled": False}},
    )


def build_prompt(question: str, chunks: list[Document]) -> str:
    """Lay the question and the retrieved chunks out for the model.

    Each excerpt is labelled with where it came from, so the model can point at
    its source and you can check the answer against the document yourself.
    """
    excerpts = "\n\n".join(
        f"[{i}] from {chunk.metadata.get('source', 'unknown')}"
        f" page {chunk.metadata.get('page', '-')}\n{chunk.page_content}"
        for i, chunk in enumerate(chunks, 1)
    )
    return PROMPT.format(excerpts=excerpts, question=question)


def stream_answer(question: str, chunks: list[Document], model: BaseChatModel) -> Iterator[str]:
    """Yield the answer in pieces as the model produces them.

    Streaming does not make the answer arrive sooner, but it makes it start
    arriving. Waiting for a whole answer in silence feels far longer than
    reading one as it is written.
    """
    answer = ""
    for piece in model.stream(build_prompt(question, chunks)):
        answer += piece.content
        yield piece.content
    check_answer_is_not_empty(answer)


def answer_question(question: str, chunks: list[Document], model: BaseChatModel) -> str:
    """The whole answer, once it is finished.

    Built on stream_answer so there is one code path, and the streamed and
    unstreamed answers cannot drift apart.
    """
    return "".join(stream_answer(question, chunks, model))
