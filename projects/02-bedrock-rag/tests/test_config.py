import ast
from pathlib import Path

import bedrock_rag.config
import pytest
from bedrock_rag.config import load_config

# What a deployed stack publishes, as parameters.py returns it.
PARAMETERS = {"knowledge_base_id": "XEIGF4KXHU", "data_source_id": "JTJON9FPWG"}


def test_returns_the_ids_published_by_terraform():
    """The ids AWS generated reach the rest of the app through here.

    They arrive as an argument rather than being fetched, which is what keeps
    this module pure and its tests free of AWS.
    """
    config = load_config(env={}, parameters=PARAMETERS)

    assert config.knowledge_base_id == "XEIGF4KXHU"
    assert config.data_source_id == "JTJON9FPWG"


def test_defaults_the_region_to_us_east_1():
    """One region by design, matching project 01 and infra/core's var.region.

    A default that disagrees with the deployed stack would look up a
    knowledge_base that does not exist in that region, and the error names the
    id rather than the region -- a long way from the cause.
    """
    config = load_config(env={}, parameters=PARAMETERS)

    assert config.region == "us-east-1"


def test_reads_the_region_from_the_environment():
    """AWS_REGION, the name boto3 and the CLI already read, so a shell set up
    to talk to one region does not have this module silently pointing at
    another."""
    config = load_config(env={"AWS_REGION": "eu-west-1"}, parameters=PARAMETERS)

    assert config.region == "eu-west-1"


def test_defaults_top_k_to_8():
    """Eight because project 01 ships eight, and slice 3 has to hold it fixed.

    This is the Python-side name for Bedrock's `numberOfResults`; kb_client
    translates it at the AWS boundary. Keeping project 01's word for it is what
    makes the two pipelines legible side by side.
    """
    config = load_config(env={}, parameters=PARAMETERS)

    assert config.top_k == 8


def test_reads_top_k_from_the_environment():
    """Slice 1's verification wants a wider sample than slice 2's retrieval, so
    this has to be settable without editing code."""
    config = load_config(env={"TOP_K": "25"}, parameters=PARAMETERS)

    assert config.top_k == 25


def test_falls_back_to_the_default_when_top_k_is_empty():
    """An exported-but-empty variable is the normal state of a half-filled
    .env, and it must mean "unset" rather than "zero results"."""
    config = load_config(env={"TOP_K": ""}, parameters=PARAMETERS)

    assert config.top_k == 8


def test_raises_naming_top_k_when_it_is_not_a_whole_number():
    with pytest.raises(ValueError, match="TOP_K"):
        load_config(env={"TOP_K": "eight"}, parameters=PARAMETERS)


def test_imports_nothing_that_can_reach_the_network():
    """The design claim that "config does no I/O" has to be checkable, not
    aspirational.

    Reading the imports is how a person checks it, so this test reads them the
    same way. What it prevents is the helpful future change where config fetches
    its own parameters, which would make every caller -- and every test --
    require AWS credentials.
    """
    source = Path(bedrock_rag.config.__file__).read_text()

    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"boto3", "botocore", "parameters", "requests", "urllib", "http", "socket"}
    assert not imported & forbidden
