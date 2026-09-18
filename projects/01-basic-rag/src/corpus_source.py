"""Fetches the corpus from S3 and refuses to hand back one that has changed.

The AWS ingestion task has no `data/` folder and no laptop behind it, so the
documents arrive from an S3 prefix instead. What does not change is the check:
`corpus.sha256` travels with them and is verified before a single document is
loaded.

That check matters more here than it does locally. `collection_name` is derived
from the chunking settings and never from the corpus, so a swapped document is
embedded into an identically named collection and nothing errors — the
benchmark's verbatim quotes simply stop matching and it reads as retrieval
getting worse. Verifying before the rebuild turns that into a loud failure
before any money is spent on embeddings.

The boto3 client is passed in rather than built here, so the tests run against
a fake and never touch the network.
"""

from pathlib import Path

from corpus import MANIFEST_NAME, CorpusError, check_corpus, is_intact, parse_manifest


def fetch_corpus(client, bucket: str, prefix: str, destination: Path) -> Path:
    """Download every object under `prefix` into `destination` and verify it.

    Returns the folder, so the caller can hand it straight to
    `load_documents`. Raises `CorpusError` if the manifest is absent or the
    downloaded files do not match it.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    keys = _list_objects(client, bucket, prefix)
    if not keys:
        raise CorpusError(f"nothing under s3://{bucket}/{prefix}")

    for key in keys:
        # Flattened deliberately: load_documents reads one folder and does not
        # descend, so a nested key would be downloaded and then never loaded.
        client.download_file(Bucket=bucket, Key=key, Filename=str(destination / Path(key).name))

    manifest_path = destination / MANIFEST_NAME
    if not manifest_path.is_file():
        raise CorpusError(
            f"no {MANIFEST_NAME} under s3://{bucket}/{prefix} — there is nothing to verify "
            "the documents against, and an unverified corpus indexes silently into the "
            "collection the benchmark was measured on"
        )

    checks = check_corpus(destination, parse_manifest(manifest_path.read_text()))
    if not is_intact(checks):
        raise CorpusError(
            f"s3://{bucket}/{prefix} does not match its {MANIFEST_NAME}:\n"
            + "\n".join(
                f"  {check.status:<9} {check.name}" for check in checks if check.status != "ok"
            )
        )
    return destination


def _list_objects(client, bucket: str, prefix: str) -> list[str]:
    """Every key under `prefix`, minus the folder placeholders.

    Uploading a folder through the S3 console creates a zero-byte object whose
    key ends in `/`. Downloading one writes an empty file that the manifest
    check would then report as untracked.
    """
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            if not item["Key"].endswith("/"):
                keys.append(item["Key"])
    return keys
