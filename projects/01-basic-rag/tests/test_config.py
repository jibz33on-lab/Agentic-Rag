import pytest
from config import load_config


def test_raises_when_openrouter_api_key_is_missing():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_config(env={})


def test_returns_the_openrouter_api_key_when_present():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.openrouter_api_key == "sk-or-test"


def test_raises_when_embedding_dimensions_is_not_a_number():
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS"):
        load_config(
            env={"OPENROUTER_API_KEY": "sk-or-test", "EMBEDDING_DIMENSIONS": "not-a-number"}
        )


def test_defaults_embedding_dimensions_to_1024():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.embedding_dimensions == 1024


def test_builds_collection_name_from_settings():
    config = load_config(
        env={
            "OPENROUTER_API_KEY": "sk-or-test",
            "EMBEDDING_MODEL": "baai/bge-m3",
            "CHUNK_SIZE": "500",
        }
    )

    assert config.collection_name == "bge-m3-500-200"


def test_uses_default_collection_when_no_settings_given():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.collection_name == "bge-m3-1000-200"


def test_collection_name_changes_when_overlap_changes():
    env = {"OPENROUTER_API_KEY": "sk-or-test", "CHUNK_OVERLAP": "400"}

    assert load_config(env).collection_name == "bge-m3-1000-400"


def test_builds_postgres_url_from_parts():
    config = load_config(
        env={
            "OPENROUTER_API_KEY": "sk-or-test",
            "POSTGRES_USER": "agentic",
            "POSTGRES_PASSWORD": "agentic",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "agentic_rag",
        }
    )

    assert config.postgres_url == "postgresql+psycopg://agentic:agentic@localhost:5432/agentic_rag"


def test_escapes_special_characters_in_the_postgres_password():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test", "POSTGRES_PASSWORD": "p@ss/word"})

    assert "p%40ss%2Fword" in config.postgres_url
