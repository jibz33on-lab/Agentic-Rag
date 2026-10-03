import pytest
from bedrock_rag.parameters import DATA_SOURCE_ID_PATH, KNOWLEDGE_BASE_ID_PATH, load_parameters


class FakeSSM:
    """Stands in for a boto3 SSM client, returning what the real one returns.

    `get_parameters` reports the names it could not find in `InvalidParameters`
    rather than raising, which is the behaviour load_parameters depends on to
    name every missing path at once. Faking that shape is the point of this
    class; faking a client that raised instead would let an implementation pass
    here and fail against AWS.
    """

    def __init__(self, values: dict[str, str]):
        self.values = values

    def get_parameters(self, Names: list[str], **kwargs):
        return {
            "Parameters": [{"Name": n, "Value": self.values[n]} for n in Names if n in self.values],
            "InvalidParameters": [n for n in Names if n not in self.values],
        }


def deployed_stack(**overrides: str) -> FakeSSM:
    """An SSM holding what a successful `terraform apply` writes."""
    return FakeSSM(
        {
            KNOWLEDGE_BASE_ID_PATH: "XEIGF4KXHU",
            DATA_SOURCE_ID_PATH: "JTJON9FPWG",
            **overrides,
        }
    )


def without(path: str) -> FakeSSM:
    """A deployed stack with one parameter removed."""
    ssm = deployed_stack()
    del ssm.values[path]
    return ssm


def test_returns_the_knowledge_base_and_data_source_ids():
    parameters = load_parameters(deployed_stack())

    assert parameters == {
        "knowledge_base_id": "XEIGF4KXHU",
        "data_source_id": "JTJON9FPWG",
    }


def test_raises_naming_the_path_when_the_knowledge_base_id_is_missing():
    with pytest.raises(ValueError, match=KNOWLEDGE_BASE_ID_PATH):
        load_parameters(without(KNOWLEDGE_BASE_ID_PATH))


def test_raises_naming_the_path_when_the_data_source_id_is_missing():
    with pytest.raises(ValueError, match=DATA_SOURCE_ID_PATH):
        load_parameters(without(DATA_SOURCE_ID_PATH))


def test_names_every_missing_path_when_no_stack_is_deployed():
    with pytest.raises(ValueError) as raised:
        load_parameters(FakeSSM({}))

    message = str(raised.value)
    assert KNOWLEDGE_BASE_ID_PATH in message
    assert DATA_SOURCE_ID_PATH in message
