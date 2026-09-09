"""Check the documents on disk against the corpus the benchmark was built from.

The corpus is load-bearing and nothing else notices when it changes.
`collection_name` is derived from the chunking settings alone — swap a PDF and
re-ingest, and the new chunks land in an identically named collection while the
benchmark's verbatim quotes quietly stop matching anything. The failure looks
like retrieval got worse.

The documents are third-party and not committed, so this is what the repo can
still say about them: their names and their hashes, and a loud complaint when
what is on disk is not what the numbers were measured on.

The manifest is `shasum -a 256` output, so `shasum -a 256 -c data/corpus.sha256`
checks it too, without this file.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "corpus.sha256"

# The only committed files in the corpus folder. They describe the corpus, so
# they cannot be part of it.
NOT_DOCUMENTS = frozenset({MANIFEST_NAME, "README.md", ".DS_Store"})

# shasum writes "<hash><two spaces><name>", and a name may contain spaces, so
# the split is on the separator rather than on whitespace.
SEPARATOR = "  "


class CorpusError(Exception):
    """The corpus cannot be checked at all, as opposed to failing the check."""


@dataclass(frozen=True)
class FileCheck:
    """One document's verdict. `ok`, `changed`, `missing` or `untracked`."""

    name: str
    status: str
    expected: str | None = None
    actual: str | None = None


def parse_manifest(text: str) -> dict[str, str]:
    """Read `shasum -a 256` output into a name -> hash mapping."""
    manifest = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if SEPARATOR not in line:
            raise CorpusError(f"{MANIFEST_NAME} line {number} is not a checksum line: {line!r}")
        digest, name = line.split(SEPARATOR, 1)
        manifest[name.strip()] = digest.strip()
    return manifest


def hash_file(path: Path) -> str:
    """The sha256 of a file, read in blocks so a large PDF is not held whole."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check_corpus(folder: Path, manifest: dict[str, str]) -> tuple[FileCheck, ...]:
    """Compare a folder against a manifest, in manifest order then extras.

    An extra document is reported, not ignored: it changes the chunks as surely
    as an edited one does.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise CorpusError(f"no corpus folder at {folder}")

    checked = tuple(_check(folder / name, expected) for name, expected in manifest.items())
    untracked = tuple(
        FileCheck(name=path.name, status="untracked", actual=hash_file(path))
        for path in sorted(folder.iterdir())
        if path.is_file() and path.name not in NOT_DOCUMENTS and path.name not in manifest
    )
    return checked + untracked


def is_intact(checks) -> bool:
    """Is every document present and unchanged, with nothing extra?"""
    return all(check.status == "ok" for check in checks)


def _check(path: Path, expected: str) -> FileCheck:
    if not path.is_file():
        return FileCheck(name=path.name, status="missing", expected=expected)
    actual = hash_file(path)
    status = "ok" if actual == expected else "changed"
    return FileCheck(name=path.name, status=status, expected=expected, actual=actual)
