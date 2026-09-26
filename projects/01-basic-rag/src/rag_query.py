"""One pass from question to answer: retrieval and generation as one traced unit.

This lives here rather than in the terminal command because it now has two
callers — `ask`, and an evaluation_run. Evaluating a reassembled lookalike of
the pipeline would measure a system we do not ship.
"""

from collections.abc import Callable
from dataclasses import dataclass

from answerer import stream_answer
from config import Config
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from retrieval import retrieve


@dataclass(frozen=True)
class RagQueryResult:
    """What one rag_query produced, and where to find its record.

    `chunks` are LangChain `Document`s carrying their text, not source and page
    summaries. Quote matching needs the content, and since this function is
    traced, the retrieved text lands in LangSmith where a bad answer can be
    diagnosed without running the query again.

    `run_id` is None when tracing is off. An evaluation_run then loses its
    system metrics for that question and scores retrieval and generation anyway.
    """

    answer: str
    chunks: list[Document]
    run_id: str | None


def record_cost(run_tree, usage: dict | None) -> None:
    """Put OpenRouter's cost on the current run, where the UI can show it.

    LangSmith fills its own cost column by pricing the model itself, and it does
    not price the ones we reach through OpenRouter — so that column stays empty
    and the figure would otherwise live only inside the run's outputs, where
    nothing can filter or sort on it.

    Registering a price with LangSmith instead was considered and rejected: it
    would compute tokens times a fixed rate, while OpenRouter charges whatever
    the provider it routed to charges. That gives two costs on one screen that
    disagree, which is worse than one cost you have to know where to find.

    Does nothing without a run tree — tracing may be off — and nothing without a
    cost, so a provider that stops reporting one leaves no misleading zero.
    """
    if run_tree is None or not usage:
        return
    cost = usage.get("cost")
    if cost is None:
        return
    run_tree.add_metadata({"openrouter_cost": cost})


@traceable(name="rag_query", run_type="chain")
def rag_query(
    question: str,
    config: Config,
    embeddings: Embeddings,
    model: BaseChatModel,
    reranker: BaseDocumentCompressor | None,
    prompt: str,
    on_piece: Callable[[str], None] | None = None,
) -> RagQueryResult:
    """Retrieve, then answer — as one traced unit.

    The decorator is what makes LangSmith record retrieval and generation as
    children of a single query, rather than as two unrelated top-level runs. It
    is the difference between "an LLM call took 26s" and "this question took
    26s, of which 2s was retrieval".

    `on_piece` is called with each piece as it arrives, so a caller can print a
    streaming answer without the printing happening in here. It is optional: an
    evaluation_run has nothing to print.

    `reranker` is not optional, deliberately. It is built once at startup and
    passed down like `embeddings` and `model`, and a default of None would let a
    caller skip reranking by forgetting an argument — producing an
    evaluation_run labelled reranked that carries baseline numbers. Pass None to
    mean it explicitly.
    """
    run_tree = get_current_run_tree()
    chunks = retrieve(question, config, embeddings, reranker)

    answer = ""
    for piece in stream_answer(question, chunks, model, prompt):
        if on_piece is not None:
            on_piece(piece)
        answer += piece

    # After the stream, not during: the usage chunk is the last thing to arrive.
    record_cost(run_tree, getattr(model, "last_usage", None))
    return RagQueryResult(
        answer=answer, chunks=chunks, run_id=str(run_tree.id) if run_tree else None
    )
