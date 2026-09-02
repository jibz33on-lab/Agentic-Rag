"""Reads settings from the environment and checks them before anything runs."""

from dataclasses import dataclass

DEFAULT_EMBEDDING_MODEL = "baai/bge-m3"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    embedding_model: str
    embedding_dimensions: int
    chunk_size: int
    chunk_overlap: int

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


def _whole_number(env, name, default):
    raw = env.get(name) or default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def load_config(env):
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    return Config(
        openrouter_api_key=api_key,
        embedding_model=env.get("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions=_whole_number(
            env, "EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS
        ),
        chunk_size=_whole_number(env, "CHUNK_SIZE", DEFAULT_CHUNK_SIZE),
        chunk_overlap=_whole_number(env, "CHUNK_OVERLAP", DEFAULT_CHUNK_OVERLAP),
    )
