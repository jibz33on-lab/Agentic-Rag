"""Reads the ids Terraform published to SSM.

The only module in src/ that touches SSM. Keeping it alone in that role is what
lets "config.py does no I/O" stay checkable by reading imports: if nothing else
imports an AWS client, nothing else can reach the network while config is built.
"""

from collections.abc import Mapping
from typing import Any

# The paths are the committed constants, not the ids behind them. AWS generates
# the ids, so a destroy and re-apply produces different ones and no default can
# be written down -- but the path a deployed stack writes to never changes. See
# infra/core/parameters.tf, which creates both.
KNOWLEDGE_BASE_ID_PATH = "/bedrock-rag/knowledge-base-id"
DATA_SOURCE_ID_PATH = "/bedrock-rag/data-source-id"

_PATHS = {
    "knowledge_base_id": KNOWLEDGE_BASE_ID_PATH,
    "data_source_id": DATA_SOURCE_ID_PATH,
}


def load_parameters(ssm: Any) -> Mapping[str, str]:
    """Fetch every published id, or raise naming the paths that are absent.

    `ssm` is a boto3 SSM client, passed in rather than built here so a test can
    hand over a stand-in. Building it inside would make every caller reach AWS.

    One `get_parameters` call rather than one per path: it reports absent names
    in `InvalidParameters` instead of raising, so a fresh clone with no stack
    deployed gets a single error listing everything it needs rather than fixing
    one path and rediscovering the next.
    """
    response = ssm.get_parameters(Names=list(_PATHS.values()))

    missing = response["InvalidParameters"]
    if missing:
        raise ValueError(
            f"No value in SSM at {', '.join(sorted(missing))}. "
            "Apply infra/core, which publishes the ids there."
        )

    values = {parameter["Name"]: parameter["Value"] for parameter in response["Parameters"]}
    return {name: values[path] for name, path in _PATHS.items()}
