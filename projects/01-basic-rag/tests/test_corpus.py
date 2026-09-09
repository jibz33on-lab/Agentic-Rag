import hashlib

import pytest
from corpus import CorpusError, check_corpus, is_intact, parse_manifest

MANIFEST = """\
# sha256 of every file the benchmark was built from.
3839ec1d  agentic-systems-mental-model.docx
c3a59a7b  complete-langgraph-tutorial.pdf
"""


def _write(folder, name, text):
    (folder / name).write_text(text)
    return folder / name


def test_reads_a_name_and_a_hash_from_each_line():
    assert parse_manifest(MANIFEST) == {
        "agentic-systems-mental-model.docx": "3839ec1d",
        "complete-langgraph-tutorial.pdf": "c3a59a7b",
    }


def test_ignores_comments_and_blank_lines():
    assert parse_manifest("\n# a note\n\nabc123  one.pdf\n") == {"one.pdf": "abc123"}


def test_keeps_a_filename_that_contains_spaces():
    """shasum separates the hash from the name by exactly two spaces, and the
    name runs to the end of the line. Splitting on whitespace would truncate."""
    assert parse_manifest("abc123  system design fundamentals.pdf\n") == {
        "system design fundamentals.pdf": "abc123"
    }


def test_rejects_a_line_it_cannot_read():
    """A malformed manifest must not quietly verify nothing."""
    with pytest.raises(CorpusError):
        parse_manifest("this is not a checksum line\n")


def test_a_file_whose_contents_match_is_ok(tmp_path):
    _write(tmp_path, "one.pdf", "hybrid search")
    manifest = {"one.pdf": _sha256_of("hybrid search")}

    (check,) = check_corpus(tmp_path, manifest)

    assert (check.name, check.status) == ("one.pdf", "ok")
    assert is_intact(check_corpus(tmp_path, manifest))


def test_an_edited_file_is_changed_and_reports_both_hashes(tmp_path):
    _write(tmp_path, "one.pdf", "hybrid search, edited")
    manifest = {"one.pdf": _sha256_of("hybrid search")}

    (check,) = check_corpus(tmp_path, manifest)

    assert check.status == "changed"
    assert check.expected == manifest["one.pdf"]
    assert check.actual == _sha256_of("hybrid search, edited")
    assert not is_intact(check_corpus(tmp_path, manifest))


def test_a_file_in_the_manifest_but_not_on_disk_is_missing(tmp_path):
    (check,) = check_corpus(tmp_path, {"one.pdf": "abc123"})

    assert (check.status, check.actual) == ("missing", None)
    assert not is_intact([check])


def test_a_file_on_disk_but_not_in_the_manifest_is_untracked(tmp_path):
    """An extra document changes the chunks as surely as an edited one, so it
    fails the check rather than passing unnoticed."""
    _write(tmp_path, "extra.pdf", "something new")

    (check,) = check_corpus(tmp_path, {})

    assert (check.status, check.expected) == ("untracked", None)
    assert not is_intact([check])


def test_ignores_the_manifest_and_its_readme(tmp_path):
    """They live in the corpus folder and are the only two files there that are
    committed, so they cannot be part of what they describe."""
    _write(tmp_path, "README.md", "where these came from")
    _write(tmp_path, "corpus.sha256", MANIFEST)

    assert check_corpus(tmp_path, {}) == ()


def test_reports_the_manifest_order_first_then_the_untracked(tmp_path):
    """A stable order, so two runs can be diffed."""
    _write(tmp_path, "b.pdf", "b")
    _write(tmp_path, "z-extra.pdf", "z")

    checks = check_corpus(tmp_path, {"a.pdf": "aaa", "b.pdf": _sha256_of("b")})

    assert [(c.name, c.status) for c in checks] == [
        ("a.pdf", "missing"),
        ("b.pdf", "ok"),
        ("z-extra.pdf", "untracked"),
    ]


def test_a_missing_corpus_folder_is_an_error_not_an_empty_pass(tmp_path):
    with pytest.raises(CorpusError):
        check_corpus(tmp_path / "not-here", {"one.pdf": "abc123"})


def _sha256_of(text):
    return hashlib.sha256(text.encode()).hexdigest()
