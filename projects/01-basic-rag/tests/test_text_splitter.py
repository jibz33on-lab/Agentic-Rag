from langchain_core.documents import Document
from text_splitter import split_documents


def test_splits_documents_into_chunks_of_the_configured_size():
    documents = [Document(page_content="word " * 200)]

    chunks = split_documents(documents, chunk_size=100, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(len(chunk.page_content) <= 100 for chunk in chunks)
