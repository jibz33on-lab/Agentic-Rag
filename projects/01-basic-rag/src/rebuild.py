"""Rebuilds a Qdrant collection from scratch, with no indexing state.

This is the AWS ingestion write path, and the deliberate alternative to
`indexing.index_chunks`. Where that consults a `SQLRecordManager` to work out
what changed, this drops the collection and writes everything — so there is no
state to keep, no Postgres to run, and nothing that can disagree with the store.

Why that trade is right here is argued in `designs/environments.md` under
"Decided: AWS ingestion drops the record_manager". In short: the corpus is 126
chunks, re-embedding it costs cents, and incremental indexing is correct only
while its state and the store agree. A rebuild has no state to disagree with,
which is the property a reproducible path actually needs.

Note what this module does not import. `indexing.py` pulls in `SQLRecordManager`
at module level; nothing here touches it, which is what keeps Postgres out of
the ingestion image entirely rather than merely unused.
"""

from config import Config
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from vector_store import open_vector_store


def rebuild_collection(
    chunks: list[Document],
    config: Config,
    embeddings: Embeddings,
    collection_name: str | None = None,
) -> int:
    """Drop `collection_name`, recreate it, and write every chunk. Returns the count.

    `collection_name` defaults to the one derived from the settings. The AWS
    task passes a staging name so a rebuild can be verified before the live
    collection is touched at all.

    The drop is unconditional and this is destructive by design — that is what
    "full rebuild" means. The caller decides which collection wears it.
    """
    if not chunks:
        # Refused rather than performed. An empty rebuild drops the collection
        # and writes nothing, leaving the API answering 200 OK with no chunks —
        # this project's signature silent failure. A loader that skipped every
        # file is the likely cause, and it should stop the run.
        raise ValueError("refusing to rebuild from zero chunks: it would empty the collection")

    name = collection_name or config.collection_name
    client = QdrantClient(url=config.qdrant_url)
    if client.collection_exists(name):
        client.delete_collection(name)

    store = open_vector_store(config, embeddings, collection_name=name)
    store.add_documents(chunks)
    return len(chunks)
