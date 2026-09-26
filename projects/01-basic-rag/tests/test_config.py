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


def test_does_not_raise_when_the_openai_api_key_is_missing():
    """Deliberately unlike OPENROUTER_API_KEY, which raises three lines away.

    ingest and ask never touch OpenAI, and must keep working for anyone who has
    not set up a second provider. The evaluation commands check for it when they
    run. Without this test the inconsistency looks like an oversight and gets
    'fixed', and then reading PDFs starts demanding an OpenAI key.
    """
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.openai_api_key is None


def test_returns_the_openai_api_key_when_present():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test", "OPENAI_API_KEY": "sk-test"})

    assert config.openai_api_key == "sk-test"


def test_reads_the_answerer_model():
    """ANSWERER_MODEL, not LLM_MODEL — the answerer is the thing it configures,
    and DOMAIN_TERMS.md already has a word for that."""
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test", "ANSWERER_MODEL": "vendor/model"})

    assert config.answerer_model == "vendor/model"


def test_reads_the_generator_and_judge_models():
    """The apparatus, pinned separately from the answerer under test."""
    config = load_config(
        env={
            "OPENROUTER_API_KEY": "sk-or-test",
            "GENERATOR_MODEL": "openai/generator",
            "JUDGE_MODEL": "openai/judge",
        }
    )

    assert config.generator_model == "openai/generator"
    assert config.judge_model == "openai/judge"


def test_names_the_langsmith_dataset_the_experiments_run_against():
    """The dataset is the fixed reference every experiment is measured against,
    and it lives in LangSmith rather than in this repo.

    The default is the benchmark, not the superseded golden set: every question
    in the latter was written from a single chunk, so every metric sat at 1.000
    and no retrieval change could move it."""
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.langsmith_dataset == "01-basic-rag-benchmark"


def test_defaults_the_answerer_prompt_to_baseline():
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test"})

    assert config.answerer_prompt == "baseline"


def test_reads_the_answerer_prompt():
    """The name only. Whether it exists is answerer.py's to say, at startup."""
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test", "ANSWERER_PROMPT": "v1"})

    assert config.answerer_prompt == "v1"


def test_rejects_a_candidate_count_no_larger_than_top_k_when_reranking():
    """A reranker fetches CANDIDATE_COUNT candidates and cuts them to TOP_K.
    When the fetch is no wider than the cut there is nothing to choose between,
    so reranking silently becomes a no-op — a wrong configuration, not merely
    an unhelpful one."""
    with pytest.raises(ValueError, match="CANDIDATE_COUNT"):
        load_config(
            env={
                "OPENROUTER_API_KEY": "sk-or-test",
                "RERANKER_MODEL": "BAAI/bge-reranker-base",
                "CANDIDATE_COUNT": "4",
                "TOP_K": "4",
            }
        )


def test_allows_top_k_to_equal_candidate_count_when_reranking_is_off():
    """The other half of the rule. The ceiling measurement runs TOP_K=20 with no
    reranker, against a default CANDIDATE_COUNT of 20 — enforcing the rule then
    would forbid the very experiment that decides whether reranking is worth
    building."""
    config = load_config(env={"OPENROUTER_API_KEY": "sk-or-test", "TOP_K": "20"})

    assert config.reranker_model is None
    assert config.candidate_count == 20
    assert config.top_k == 20
