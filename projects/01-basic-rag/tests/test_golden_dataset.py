from evaluation.golden_dataset import choose_chunks, make_generator

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
