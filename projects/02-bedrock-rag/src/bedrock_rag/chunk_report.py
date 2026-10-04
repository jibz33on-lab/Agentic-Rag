"""Summarises a sample of `chunk`s, so the first ingestion_job can be checked.

Bedrock chunks by tokens and project 01 chunks by characters, so `maxTokens:
250` is a translation of its 1000-character CHUNK_SIZE and nothing more. The
design says to check that translation after the fact rather than trust it, and
this is what produces the number to check.

What it summarises is a *sample*: `Retrieve` returns what ranked highest for the
queries asked, not the population. Enough to see whether 250 tokens landed near
1000 characters; not "project 02's chunk distribution".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from bedrock_rag.kb_client import Chunk


@dataclass(frozen=True)
class ChunkSummary:
    count: int
    shortest: int
    longest: int
    median: int
    # Every distinct document the sample came from, sorted. The corpus is four
    # files; one missing here is how a silently un-ingested document shows up.
    sources: tuple[str, ...]


def summarise_chunks(chunks: Sequence[Chunk]) -> ChunkSummary:
    """Describe the character lengths of a sample, and where it came from.

    An empty sample summarises to zeros rather than raising. A `Retrieve` before
    an `ingestion_job` finishes returns nothing, and the caller has to be able to
    report that; `count` is what tells the two apart.
    """
    if not chunks:
        return ChunkSummary(count=0, shortest=0, longest=0, median=0, sources=())

    lengths = [len(chunk.text) for chunk in chunks]

    return ChunkSummary(
        count=len(chunks),
        shortest=min(lengths),
        longest=max(lengths),
        # Rounded because a character count is a whole number, and an even
        # sample medians to a .5 that would print beside project 01's 1000 as
        # though it were more precise.
        median=round(median(lengths)),
        sources=tuple(sorted({chunk.source for chunk in chunks})),
    )
