import zipfile

from document_loader import load_documents

DOCUMENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>"""


def _write_docx(path, text):
    """Write a minimal valid docx. docx2txt only needs word/document.xml."""
    body = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", DOCUMENT_TEMPLATE.format(body=body))


def test_ignores_files_that_are_not_pdf_or_docx(tmp_path):
    (tmp_path / "notes.txt").write_text("not a document we handle")

    assert load_documents(tmp_path).documents == []


def test_loads_text_from_a_docx(tmp_path):
    _write_docx(tmp_path / "notes.docx", "hybrid search combines keyword and vector results")

    result = load_documents(tmp_path)

    assert len(result.documents) == 1
    assert "hybrid search" in result.documents[0].page_content


def test_skips_a_file_that_cannot_be_read(tmp_path):
    _write_docx(tmp_path / "good.docx", "hybrid search")
    (tmp_path / "broken.pdf").write_bytes(b"this is not a pdf")

    result = load_documents(tmp_path)

    assert len(result.documents) == 1
    assert [failure.path.name for failure in result.failures] == ["broken.pdf"]
