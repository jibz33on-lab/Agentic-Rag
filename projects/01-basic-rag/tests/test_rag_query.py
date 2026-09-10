from conftest import FAKE_DIMENSIONS
from indexing import index_chunks
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from rag_query import rag_query, record_cost

SOURCE = Document(
    page_content="hybrid search runs both searches in parallel",
    metadata={"source": "test.pdf"},
)


def _indexed(config):
    embeddings = DeterministicFakeEmbedding(size=FAKE_DIMENSIONS)
    index_chunks([SOURCE], config, embeddings)
    return embeddings


def test_returns_the_answer_and_the_chunks_it_came_from(services, config):
    """The chunks come back as Documents carrying their text, not as source and
    page dicts. Quote matching needs the content, and a trace that records what
    was retrieved can be diagnosed without re-running the query."""
    embeddings = _indexed(config)
    model = FakeListChatModel(responses=["both at once"])

    result = rag_query("what is hybrid search?", config, embeddings, model, None)

    assert result.answer == "both at once"
    assert result.chunks[0].page_content == SOURCE.page_content


def test_streams_each_piece_to_the_caller_when_asked(services, config):
    """on_piece is optional — an evaluation_run has nothing to print, and a
    required callback would force it to pass a no-op forever."""
    embeddings = _indexed(config)
    model = FakeListChatModel(responses=["both at once"])
    seen = []

    rag_query("what is hybrid search?", config, embeddings, model, None, on_piece=seen.append)

    assert len(seen) > 1
    assert "".join(seen) == "both at once"


class FakeRunTree:
    """Stands in for langsmith's RunTree, which needs a live traced context."""

    def __init__(self):
        self.added = []

    def add_metadata(self, metadata):
        self.added.append(metadata)


def test_records_the_openrouter_cost_on_the_current_run():
    """LangSmith's own cost column stays empty for a model it does not price,
    so the exact figure goes in metadata, where the runs table can filter on it.
    """
    tree = FakeRunTree()

    record_cost(tree, {"cost": 9.18e-06, "prompt_tokens": 14})

    assert tree.added == [{"openrouter_cost": 9.18e-06}]


def test_records_nothing_when_tracing_is_off():
    """get_current_run_tree() returns None with tracing disabled, and an
    evaluation_run must still score retrieval and generation without it."""
    assert record_cost(None, {"cost": 9.18e-06}) is None


def test_records_nothing_when_the_provider_reported_no_cost():
    """A missing cost must leave no metadata at all. Writing a zero would read
    as a free request rather than an unknown one."""
    tree = FakeRunTree()

    record_cost(tree, {"prompt_tokens": 14})

    assert tree.added == []
