"""Puts chunks into Qdrant, skipping anything already there."""

# Imported from a private module because langchain-community does not
# re-export it, and no maintained package supplies a SQL-backed record
# manager. langchain-postgres has PGVector but nothing equivalent. This is
# the most fragile import in the project — see the design doc.
from config import Config
from langchain_community.indexes._sql_record_manager import SQLRecordManager
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.indexing import index
from vector_store import open_vector_store


def index_chunks(chunks: list[Document], config: Config, embeddings: Embeddings) -> dict[str, int]:
    """Index `chunks`, skipping any whose content is already stored.

    cleanup="scoped_full" with source_id_key="source" means an edited file has
    its old chunks removed once the run finishes, rather than leaving both
    versions in the collection.
    """
    return index(
        chunks,
        _record_manager(config),
        open_vector_store(config, embeddings),
        # scoped_full, not incremental. Incremental cleans up after every
        # batch, so a file whose chunks straddle a batch boundary has its
        # tail deleted by one batch and re-added by the next, on every run.
        # scoped_full cleans up once at the end, still only touching the
        # sources actually seen.
        cleanup="scoped_full",
        source_id_key="source",
        # key_encoder stays SHA-1 despite LangChain warning about it. Qdrant
        # only accepts an integer or a UUID as a point ID, and sha256 or
        # blake2b produce digests too long to be either. Collision resistance
        # is not in our threat model: these are local files we control.
    )


def _record_manager(config: Config) -> SQLRecordManager:
    manager = SQLRecordManager(namespace=config.collection_name, db_url=config.postgres_url)
    manager.create_schema()
    return manager
