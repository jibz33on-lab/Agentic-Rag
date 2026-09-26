"""Reads settings from the environment and checks them before anything runs."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200

# Defaults match docker-compose.yml at the repo root.
DEFAULT_ANSWERER_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_LANGSMITH_DATASET = "01-basic-rag-benchmark"
# The answerer prompt every recorded experiment was run with. Named rather
# than spelled out: the text lives with the answerer, this only selects it.
DEFAULT_ANSWERER_PROMPT = "baseline"
DEFAULT_DATA_FOLDER = "data"
DEFAULT_TOP_K = 4
# How many candidates the reranker scores before cutting to TOP_K. Unused when
# RERANKER_MODEL is unset, which is why it does not constrain TOP_K then.
DEFAULT_CANDIDATE_COUNT = 20
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_POSTGRES_USER = "agentic"
DEFAULT_POSTGRES_PASSWORD = "agentic"
DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DB = "agentic_rag"


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    # Optional, unlike the OpenRouter key: ingest and ask never touch OpenAI.
    # The evaluation commands check for it when they run. See load_config.
    openai_api_key: str | None
    embedding_model: str
    # The model under test. Generator and judge are the apparatus, pinned
    # separately so that changing the answerer does not also change the ruler.
    answerer_model: str
    # Which of the answerer's prompts to run, by name. Not validated here:
    # config.py cannot import the registry without a cycle, so answerer.py
    # checks the name at startup and lists the ones that exist.
    answerer_prompt: str
    generator_model: str | None
    judge_model: str | None
    embedding_dimensions: int
    chunk_size: int
    chunk_overlap: int
    data_folder: str
    top_k: int
    # None turns reranking off, leaving retrieval exactly as it was before the
    # reranker existed. That is what lets the baseline be reproduced on this
    # code and compared against a reranked run.
    reranker_model: str | None
    candidate_count: int
    qdrant_url: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    langsmith_dataset: str

    @property
    def collection_name(self) -> str:
        """Where this combination of settings stores its chunks.

        Settings live in the name so that changing one points at a different,
        empty collection rather than silently reusing chunks built the old way.

        Every setting that changes the chunks must appear here. A new chunking
        setting left out of this name would be silently ignored on a re-run,
        because indexing compares file contents and never sees our settings.
        """
        model = self.embedding_model.rsplit("/", 1)[-1]
        return f"{model}-{self.chunk_size}-{self.chunk_overlap}"

    @property
    def postgres_url(self) -> str:
        """Where the record manager keeps track of what has been indexed.

        The +psycopg suffix picks psycopg 3, which is what is installed.
        Without it SQLAlchemy reaches for psycopg2 and fails on import.

        User and password are escaped because a generated password containing
        @ or / would otherwise produce a URL no parser can read, and the error
        it causes looks nothing like its cause.
        """
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _whole_number(env: Mapping[str, str], name: str, default: int | str) -> int:
    raw = env.get(name) or default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def _text(env: Mapping[str, str], name: str, default: str) -> str:
    return env.get(name) or default


def load_config(env: Mapping[str, str]) -> Config:
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    top_k = _whole_number(env, "TOP_K", DEFAULT_TOP_K)
    reranker_model = env.get("RERANKER_MODEL") or None
    candidate_count = _whole_number(env, "CANDIDATE_COUNT", DEFAULT_CANDIDATE_COUNT)

    # Only when reranking is on. With it off the reranker never runs, so
    # candidate_count is unused and has no business constraining TOP_K —
    # enforcing it unconditionally would forbid TOP_K=20, which is exactly the
    # setting the ceiling measurement needs.
    if reranker_model and candidate_count <= top_k:
        raise ValueError(
            f"CANDIDATE_COUNT must be larger than TOP_K when RERANKER_MODEL is set, "
            f"got CANDIDATE_COUNT={candidate_count} and TOP_K={top_k}. The reranker "
            f"cuts candidates down to TOP_K, so it would have nothing to choose "
            f"between and reranking would silently do nothing."
        )

    return Config(
        openrouter_api_key=api_key,
        # Deliberately not validated here. Raising would stop ingest and ask
        # working for anyone who has not set up a second provider, and neither
        # of them touches OpenAI. The evaluation commands check it themselves.
        openai_api_key=env.get("OPENAI_API_KEY") or None,
        embedding_model=env.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        answerer_model=_text(env, "ANSWERER_MODEL", DEFAULT_ANSWERER_MODEL),
        answerer_prompt=_text(env, "ANSWERER_PROMPT", DEFAULT_ANSWERER_PROMPT),
        generator_model=env.get("GENERATOR_MODEL") or None,
        judge_model=env.get("JUDGE_MODEL") or None,
        embedding_dimensions=_whole_number(
            env, "EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS
        ),
        chunk_size=_whole_number(env, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE),
        chunk_overlap=_whole_number(env, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP),
        data_folder=_text(env, "DATA_FOLDER", DEFAULT_DATA_FOLDER),
        top_k=top_k,
        reranker_model=reranker_model,
        candidate_count=candidate_count,
        qdrant_url=_text(env, "QDRANT_URL", DEFAULT_QDRANT_URL),
        postgres_user=_text(env, "POSTGRES_USER", DEFAULT_POSTGRES_USER),
        postgres_password=_text(env, "POSTGRES_PASSWORD", DEFAULT_POSTGRES_PASSWORD),
        postgres_host=_text(env, "POSTGRES_HOST", DEFAULT_POSTGRES_HOST),
        postgres_port=_whole_number(env, "POSTGRES_PORT", DEFAULT_POSTGRES_PORT),
        postgres_db=_text(env, "POSTGRES_DB", DEFAULT_POSTGRES_DB),
        langsmith_dataset=_text(env, "LANGSMITH_DATASET", DEFAULT_LANGSMITH_DATASET),
    )
