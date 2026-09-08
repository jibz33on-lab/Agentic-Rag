import json

from evaluation.evaluators import supports
from evaluation.golden_dataset import (
    choose_chunks,
    choose_related_groups,
    make_generator,
    make_multi_generator,
)

CHUNKS = (
    [{"source": "a.pdf", "text": f"a text {i}", "page": i} for i in range(40)]
    + [{"source": "b.pdf", "text": f"b text {i}", "page": i} for i in range(36)]
    + [{"source": "c.docx", "text": f"c text {i}", "page": None} for i in range(25)]
    + [{"source": "d.pdf", "text": f"d text {i}", "page": i} for i in range(25)]
)


def test_samples_the_requested_number_of_chunks():
    assert len(choose_chunks(CHUNKS, 20)) == 20


def test_represents_every_document():
    """The only constraint on the sample. Uniform random over 126 chunks would
    usually cover all four anyway, but 'usually' is not a property you want in
    the reference set every later comparison is measured against."""
    sample = choose_chunks(CHUNKS, 20)

    assert {c["source"] for c in sample} == {"a.pdf", "b.pdf", "c.docx", "d.pdf"}


def test_is_the_same_sample_every_time():
    """A golden dataset you cannot rebuild identically is not a fixed
    reference."""
    assert choose_chunks(CHUNKS, 20) == choose_chunks(CHUNKS, 20)


class FakeResponse:
    def __init__(self, content):
        message = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": message})()]


class FakeOpenAI:
    def __init__(self, content):
        class Completions:
            def create(self, **kwargs):
                return FakeResponse(content)

        self.chat = type("Chat", (), {"completions": Completions()})()


CHUNK = {"source": "a.pdf", "text": "Read replicas fix a database pegged by SELECTs.", "page": 3}


def test_generates_an_example_carrying_its_evidence():
    client = FakeOpenAI(
        '{"usable": true, "question": "What fixes a DB pegged by SELECTs?",'
        ' "expected_answer": "Read replicas.",'
        ' "quote": "Read replicas fix a database pegged by SELECTs."}'
    )

    example = make_generator(client, "test-model")(CHUNK)

    assert example["question"] == "What fixes a DB pegged by SELECTs?"
    assert example["quote"] == "Read replicas fix a database pegged by SELECTs."
    assert example["source"] == "a.pdf"


def test_discards_an_example_the_generator_refused_to_write():
    """A table of contents or a running header holds no self-contained fact.
    Refusing is a correct outcome, not a failure."""
    client = FakeOpenAI('{"usable": false, "reason": "table of contents"}')

    assert make_generator(client, "test-model")(CHUNK) is None


def test_discards_an_example_whose_quote_is_not_in_the_chunk():
    """Models tidy quotes rather than copying them. An unverifiable quote would
    score a miss for every configuration equally and look like bad retrieval
    rather than a bad example."""
    client = FakeOpenAI(
        '{"usable": true, "question": "q", "expected_answer": "a",'
        ' "quote": "read replicas are the fix for this problem"}'
    )

    assert make_generator(client, "test-model")(CHUNK) is None


def test_discards_an_example_whose_answer_just_repeats_the_quote():
    """The prompt asks for an answer in the model's own words; this is the
    constraint behind that request. An expected_answer identical to the quote
    means the judge compares the answer against the source text itself, which
    makes 'correct' far easier to score than it should be."""
    client = FakeOpenAI(
        '{"usable": true, "question": "What fixes a DB pegged by SELECTs?",'
        ' "expected_answer": "Read replicas fix a database pegged by SELECTs.",'
        ' "quote": "Read replicas fix a database pegged by SELECTs."}'
    )

    assert make_generator(client, "test-model")(CHUNK) is None


def test_discards_an_example_with_no_expected_answer():
    """Unlike the quote, expected_answer was never validated at all."""
    client = FakeOpenAI(
        '{"usable": true, "question": "q", "expected_answer": "",'
        ' "quote": "Read replicas fix a database pegged by SELECTs."}'
    )

    assert make_generator(client, "test-model")(CHUNK) is None


# --- multi-chunk examples ---------------------------------------------------

VECTOR_CHUNKS = [
    {"source": "a.pdf", "page": 1, "text": "alpha one", "vector": [1.0, 0.0]},
    {"source": "a.pdf", "page": 2, "text": "alpha two", "vector": [0.98, 0.2]},
    {"source": "a.pdf", "page": 3, "text": "alpha three", "vector": [0.95, 0.31]},
    {"source": "b.pdf", "page": 1, "text": "beta one", "vector": [0.0, 1.0]},
    {"source": "b.pdf", "page": 2, "text": "beta two", "vector": [0.2, 0.98]},
    {"source": "b.pdf", "page": 3, "text": "beta three", "vector": [0.31, 0.95]},
]


def test_groups_chunks_that_are_near_each_other():
    """Related, not random: a question spanning two unrelated chunks would be
    a question no sensible person asks."""
    groups = choose_related_groups(VECTOR_CHUNKS, groups=1, seed=0)

    sources = {c["source"] for c in groups[0]}
    assert len(sources) == 1


def test_group_sizes_vary_between_two_and_four():
    """Not every example should need four chunks — a two-chunk question is a
    different and easier test than a four-chunk one."""
    groups = choose_related_groups(VECTOR_CHUNKS, groups=2, seed=0)

    assert all(2 <= len(g) <= 4 for g in groups)


def test_groups_are_the_same_every_time():
    assert choose_related_groups(VECTOR_CHUNKS, groups=2, seed=0) == choose_related_groups(
        VECTOR_CHUNKS, groups=2, seed=0
    )


class ScriptedOpenAI:
    """Returns each scripted completion in turn: generation, then the check."""

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = 0
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls += 1
                return FakeResponse(outer.contents[min(outer.calls - 1, len(outer.contents) - 1)])

        self.chat = type("Chat", (), {"completions": Completions()})()


GROUP = [
    {"source": "a.pdf", "page": 1, "text": "Read replicas absorb SELECT traffic."},
    {"source": "a.pdf", "page": 2, "text": "Sharding splits writes across nodes."},
]

GENERATED = (
    '{"usable": true, "question": "How do read replicas and sharding differ?",'
    ' "expected_answer": "Read replicas absorb read traffic while sharding splits writes.",'
    ' "quotes": ["Read replicas absorb SELECT traffic.", "Sharding splits writes across nodes."]}'
)
NEEDS_ALL = '{"answerable_from_one": false, "which": -1}'


def test_generates_a_multi_chunk_example_carrying_every_quote():
    client = ScriptedOpenAI(GENERATED, NEEDS_ALL)

    example = make_multi_generator(client, "test-model")(GROUP)

    assert example["quotes"] == [
        "Read replicas absorb SELECT traffic.",
        "Sharding splits writes across nodes.",
    ]
    assert example["quote"] == example["quotes"][0]
    assert example["chunk_count"] == 2


def test_discards_a_question_a_single_chunk_already_answers():
    """The generator promising the question needs all the chunks is not
    evidence. This is the check behind the promise."""
    client = ScriptedOpenAI(GENERATED, '{"answerable_from_one": true, "which": 0}')

    assert make_multi_generator(client, "test-model")(GROUP) is None


def test_discards_a_multi_chunk_example_with_an_unverifiable_quote():
    generated = (
        '{"usable": true, "question": "q", "expected_answer": "a",'
        ' "quotes": ["Read replicas absorb SELECT traffic.", "not in either chunk"]}'
    )
    client = ScriptedOpenAI(generated, NEEDS_ALL)

    assert make_multi_generator(client, "test-model")(GROUP) is None


def test_discards_a_multi_chunk_example_missing_a_quote_for_a_chunk():
    """One quote per chunk. Fewer means at least one chunk is not actually
    required, and the example is not what it claims to be."""
    generated = (
        '{"usable": true, "question": "q", "expected_answer": "a",'
        ' "quotes": ["Read replicas absorb SELECT traffic."]}'
    )
    client = ScriptedOpenAI(generated, NEEDS_ALL)

    assert make_multi_generator(client, "test-model")(GROUP) is None


LONG_TEXT = "Read replicas absorb SELECT traffic across many nodes. " * 6
LONG_GROUP = [
    {"source": "a.pdf", "page": 1, "text": LONG_TEXT},
    {"source": "a.pdf", "page": 2, "text": "Sharding splits writes across nodes."},
]


def test_trims_an_over_long_quote_instead_of_discarding_the_example():
    """Models copy faithfully but ignore the character budget — measured at 245
    to 785 characters against a 200 limit, every one of them verbatim. A prefix
    of a verbatim span is still a verbatim span, so trimming keeps the quote
    matchable where rejecting would throw away a usable example."""
    generated = json.dumps(
        {
            "usable": True,
            "question": "How do read replicas and sharding differ?",
            "expected_answer": "Replicas absorb reads; sharding splits writes.",
            "quotes": [LONG_TEXT.strip(), "Sharding splits writes across nodes."],
        }
    )
    client = ScriptedOpenAI(generated, NEEDS_ALL)

    example = make_multi_generator(client, "test-model")(LONG_GROUP)

    assert example is not None
    assert len(example["quotes"][0]) <= 200
    assert supports(LONG_TEXT, example["quotes"][0])


def test_groups_can_be_asked_for_an_exact_size():
    """A benchmark wants a deliberate mix of 2-, 3- and 4-chunk questions, not
    whatever sizes the seed happened to draw."""
    groups = choose_related_groups(VECTOR_CHUNKS, groups=2, seed=0, size=2)

    assert [len(g) for g in groups] == [2, 2]
