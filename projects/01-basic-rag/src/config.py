"""Reads settings from the environment and checks them before anything runs."""

from dataclasses import dataclass

DEFAULT_EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    embedding_dimensions: int


def load_config(env):
    api_key = env.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    raw_dimensions = env.get("EMBEDDING_DIMENSIONS") or DEFAULT_EMBEDDING_DIMENSIONS
    try:
        dimensions = int(raw_dimensions)
    except ValueError:
        raise ValueError(
            f"EMBEDDING_DIMENSIONS must be a whole number, got {raw_dimensions!r}"
        ) from None

    return Config(openrouter_api_key=api_key, embedding_dimensions=dimensions)
