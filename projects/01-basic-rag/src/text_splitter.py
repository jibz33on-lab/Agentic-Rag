"""Cuts loaded documents into chunks sized for retrieval."""

from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_documents(documents, chunk_size, chunk_overlap):
    """Split `documents` into overlapping chunks.

    Sizes are in characters, not tokens. The splitter prefers to break at
    paragraphs, then lines, then spaces, and only cuts mid-word as a last
    resort. The overlap repeats the end of one chunk at the start of the next,
    so a sentence sitting across a boundary is still findable.

    Settings are passed in rather than read from config here, so that whatever
    indexes these chunks records the settings that actually produced them.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )
    return splitter.split_documents(documents)
