"""Reads the PDFs and docx files sitting in a folder."""

from dataclasses import dataclass
from pathlib import Path

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader

SUPPORTED_SUFFIXES = {".pdf", ".docx"}


@dataclass(frozen=True)
class LoadFailure:
    path: Path
    reason: str


@dataclass(frozen=True)
class LoadResult:
    documents: list
    failures: list


def load_documents(folder):
    """Load every supported file directly inside `folder`.

    Top level only — subfolders are not looked at, and anything that is not a
    PDF or a docx is ignored, which keeps macOS's .DS_Store out.

    A file that cannot be read is recorded as a failure and stepped over. One
    corrupt PDF must not cost you the other files in the folder, and a silent
    skip would leave you searching a corpus quietly missing a document.
    """
    documents = []
    failures = []
    for path in supported_files(folder):
        try:
            documents.extend(_load_one(path))
        # Deliberately broad: pypdf, docx2txt and the filesystem fail in many
        # ways, and naming them one by one means the next one kills the run.
        except Exception as error:
            failures.append(LoadFailure(path=path, reason=str(error)))
    return LoadResult(documents=documents, failures=failures)


def supported_files(folder):
    return sorted(
        path
        for path in Path(folder).iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _load_one(path):
    if path.suffix.lower() == ".pdf":
        return PyPDFLoader(str(path)).load()
    return Docx2txtLoader(str(path)).load()
