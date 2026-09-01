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
