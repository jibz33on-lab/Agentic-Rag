"""The S3 side of AWS ingestion: fetch the corpus, then prove it is the corpus.

No boto3 client is built here. `fetch_corpus` takes one, so these run with a
fake and never touch the network — the same shape as the fake embeddings the
indexing tests use.
"""

import pytest
from corpus import CorpusError
from corpus_source import fetch_corpus

BUCKET = "basic-rag-corpus-test"
PREFIX = "corpus/"


class FakeS3:
    """The three calls `fetch_corpus` makes, backed by a dict."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.downloaded: list[str] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        assert Bucket == BUCKET
        keys = [k for k in sorted(self.objects) if k.startswith(Prefix)]
        return [{"Contents": [{"Key": k, "Size": len(self.objects[k])} for k in keys]}]

    def download_file(self, Bucket, Key, Filename):
        self.downloaded.append(Key)
        with open(Filename, "wb") as handle:
            handle.write(self.objects[Key])


def manifest_for(**files: bytes) -> bytes:
    """A manifest matching `files`, built the way shasum writes one."""
    import hashlib

    lines = [f"{hashlib.sha256(body).hexdigest()}  {name}" for name, body in sorted(files.items())]
    return ("\n".join(lines) + "\n").encode()


def test_fetches_every_object_under_the_prefix(tmp_path):
    files = {"one.pdf": b"first document", "two.docx": b"second document"}
    client = FakeS3(
        {
            f"{PREFIX}one.pdf": files["one.pdf"],
            f"{PREFIX}two.docx": files["two.docx"],
            f"{PREFIX}corpus.sha256": manifest_for(**files),
        }
    )

    folder = fetch_corpus(client, BUCKET, PREFIX, tmp_path)

    assert (folder / "one.pdf").read_bytes() == files["one.pdf"]
    assert (folder / "two.docx").read_bytes() == files["two.docx"]
    assert len(client.downloaded) == 3


def test_rejects_a_corpus_that_does_not_match_its_manifest(tmp_path):
    """The whole point. A changed document must stop the rebuild, not chunk it.

    `collection_name` is derived from the chunking settings and not from the
    corpus, so a swapped document would otherwise be embedded into an
    identically named collection and the benchmark's quotes would quietly stop
    matching.
    """
    client = FakeS3(
        {
            f"{PREFIX}one.pdf": b"the document that is actually there",
            f"{PREFIX}corpus.sha256": manifest_for(**{"one.pdf": b"the document we expected"}),
        }
    )

    with pytest.raises(CorpusError, match="does not match"):
        fetch_corpus(client, BUCKET, PREFIX, tmp_path)


def test_rejects_an_extra_document_not_in_the_manifest(tmp_path):
    """An extra file changes the chunks as surely as an edited one."""
    client = FakeS3(
        {
            f"{PREFIX}one.pdf": b"first document",
            f"{PREFIX}surprise.pdf": b"nobody asked for this",
            f"{PREFIX}corpus.sha256": manifest_for(**{"one.pdf": b"first document"}),
        }
    )

    with pytest.raises(CorpusError, match="does not match"):
        fetch_corpus(client, BUCKET, PREFIX, tmp_path)


def test_refuses_a_prefix_with_no_manifest(tmp_path):
    """Without a manifest there is nothing to verify against, so refuse."""
    client = FakeS3({f"{PREFIX}one.pdf": b"first document"})

    with pytest.raises(CorpusError, match=r"no corpus\.sha256"):
        fetch_corpus(client, BUCKET, PREFIX, tmp_path)


def test_ignores_the_directory_placeholder_objects_the_console_creates(tmp_path):
    """Uploading a folder in the S3 console leaves a zero-byte key ending in /."""
    files = {"one.pdf": b"first document"}
    client = FakeS3(
        {
            PREFIX: b"",
            f"{PREFIX}one.pdf": files["one.pdf"],
            f"{PREFIX}corpus.sha256": manifest_for(**files),
        }
    )

    folder = fetch_corpus(client, BUCKET, PREFIX, tmp_path)

    assert (folder / "one.pdf").read_bytes() == files["one.pdf"]
    assert PREFIX not in client.downloaded
