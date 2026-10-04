from bedrock_rag.chunk_report import summarise_chunks
from bedrock_rag.kb_client import Chunk


def chunks(*lengths: int, source: str = "s3://bucket/doc.pdf") -> list[Chunk]:
    return [Chunk(text="x" * length, source=source) for length in lengths]


def test_counts_the_chunks_it_was_given():
    assert summarise_chunks(chunks(10, 20, 30)).count == 3


def test_reports_the_shortest_and_longest_chunk():
    """The spread is what says whether FIXED_SIZE behaved. Project 01's
    RecursiveCharacterTextSplitter produces variable-length chunks; Bedrock cuts
    at token boundaries and should be far more uniform."""
    summary = summarise_chunks(chunks(400, 1000, 1600))

    assert summary.shortest == 400
    assert summary.longest == 1600


def test_reports_the_median_character_length():
    """The number the whole slice turns on: 250 tokens was a guess at project
    01's 1000-character CHUNK_SIZE, and this is what checks it. The median
    rather than the mean, because a single short trailing chunk per document
    drags a mean down and would make the translation look worse than it is."""
    assert summarise_chunks(chunks(900, 1000, 1100)).median == 1000


def test_rounds_the_median_of_an_even_sample_to_a_whole_number():
    """An even sample medians to a .5, and a character count is a whole number.
    Left as a float it would print as 1000.0 beside project 01's 1000."""
    assert summarise_chunks(chunks(900, 1000, 1100, 1200)).median == 1050


def test_lists_each_distinct_source_once_in_order():
    """The corpus is four documents. This is how a silently un-ingested file
    shows up: it simply never appears in the sample, and a sorted list of what
    did makes the gap obvious at a glance."""
    summary = summarise_chunks(
        chunks(100, source="s3://bucket/system-design.pdf")
        + chunks(200, source="s3://bucket/agentic.docx")
        + chunks(300, source="s3://bucket/system-design.pdf")
    )

    assert summary.sources == ("s3://bucket/agentic.docx", "s3://bucket/system-design.pdf")


def test_summarises_an_empty_sample_without_crashing():
    """A Retrieve before an ingestion_job finishes returns nothing, and the
    verification command has to report that rather than fall over. count is 0 so
    the caller can tell this apart from a real distribution and say which it is."""
    summary = summarise_chunks([])

    assert summary.count == 0
    assert summary.median == 0
    assert summary.sources == ()
