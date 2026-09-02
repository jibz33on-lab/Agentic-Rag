"""Reads settings from the environment and checks them before anything runs."""

from dataclasses import dataclass
from urllib.parse import quote

DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200

# Defaults match docker-compose.yml at the repo root.
DEFAULT_LLM_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_POSTGRES_USER = "agentic"
DEFAULT_POSTGRES_PASSWORD = "agentic"
DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DB = "agentic_rag"


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    embedding_model: str
    llm_model: str
    embedding_dimensions: int
    chunk_size: int
    chunk_overlap: int
    qdrant_url: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int
    postgres_db: str

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


def _whole_number(env, name, default):
    raw = env.get(name) or default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def _text(env, name, default):
    return env.get(name) or default


def load_config(env):
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    return Config(
        openrouter_api_key=api_key,
        embedding_model=env.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        llm_model=_text(env, "LLM_MODEL", DEFAULT_LLM_MODEL),
        embedding_dimensions=_whole_number(
            env, "EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS
        ),
        chunk_size=_whole_number(env, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE),
        chunk_overlap=_whole_number(env, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP),
        qdrant_url=_text(env, "QDRANT_URL", DEFAULT_QDRANT_URL),
        postgres_user=_text(env, "POSTGRES_USER", DEFAULT_POSTGRES_USER),
        postgres_password=_text(env, "POSTGRES_PASSWORD", DEFAULT_POSTGRES_PASSWORD),
        postgres_host=_text(env, "POSTGRES_HOST", DEFAULT_POSTGRES_HOST),
        postgres_port=_whole_number(env, "POSTGRES_PORT", DEFAULT_POSTGRES_PORT),
        postgres_db=_text(env, "POSTGRES_DB", DEFAULT_POSTGRES_DB),
    )
