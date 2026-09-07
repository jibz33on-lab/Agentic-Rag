import os
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import load_config

FAKE_DIMENSIONS = 8
REPO_ROOT = Path(__file__).parents[2]


@pytest.fixture
def config():
    """Config pointing at a throwaway collection, so runs never collide."""
    return load_config(
        env={
            "OPENROUTER_API_KEY": "not-used-with-fake-embeddings",
            "EMBEDDING_MODEL": f"test/{uuid.uuid4().hex[:12]}",
            "EMBEDDING_DIMENSIONS": str(FAKE_DIMENSIONS),
        }
    )


@pytest.fixture
def services(config):
    """Skip unless Qdrant and Postgres are actually up."""
    import urllib.request

    from sqlalchemy import create_engine

    try:
        urllib.request.urlopen(config.qdrant_url, timeout=2)
    except Exception:
        pytest.skip("Qdrant is not running")
    try:
        create_engine(config.postgres_url).connect().close()
    except Exception:
        pytest.skip("Postgres is not running")


@pytest.fixture
def live_openrouter_config():
    """Config carrying the real OpenRouter key, or skip.

    Reads .env directly, the way the scripts do, so the test runs locally
    without anything being exported first. CI has no .env and no key, so it
    skips there rather than failing — the same shape as `services`.
    """
    env = {**dotenv_values(REPO_ROOT / ".env"), **os.environ}
    if not env.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY is not set")
    return load_config(env)
