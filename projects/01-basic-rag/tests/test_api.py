from api import build_answer_question, create_app
from fastapi.testclient import TestClient
from guardrails import NoAnswerError
from langchain_core.documents import Document
from rag_query import RagQueryResult

FAKE_ANSWER = "FAKE ANSWER"
# Named for what the test is guarding against: this is LangSmith's identifier,
# and it must not reach a client.
FAKE_RUN_ID = "langsmith-run-id-that-must-not-leak"


def _fake_answer_question(question: str) -> RagQueryResult:
    """Stands in for the whole pipeline: a question in, a RagQueryResult out.

    This is the API layer's only dependency, and faking it here is what keeps
    Qdrant and OpenRouter out of the test. Faking embeddings and the model
    would not be enough — rag_query calls retrieve, which calls
    open_vector_store, which opens a real connection.
    """
    return RagQueryResult(
        answer=FAKE_ANSWER,
        chunks=[
            Document(page_content="first chunk", metadata={"source": "a.pdf", "page": 0}),
            # A docx carries no page. Docx2txtLoader does not produce one, and
            # the corpus has one, so this is the real shape rather than an edge
            # case invented for the test.
            Document(page_content="second chunk", metadata={"source": "b.docx"}),
        ],
        run_id=FAKE_RUN_ID,
    )


def test_returns_the_pipelines_answer_as_json():
    """A POST to /query gives back what the pipeline produced, as JSON.

    Two assertions doing two different jobs. The status code proves the route
    exists and accepts a JSON body at all. The known string proves the route
    actually called the pipeline and returned its answer, rather than
    fabricating a reply or returning an empty shape that happens to parse.

    Without the second assertion a route that returned a hard-coded
    {"answer": ""} would pass, and every later test about chunks, request_id
    and status codes would be built on top of a route wired to nothing.
    """
    client = TestClient(create_app(_fake_answer_question))

    response = client.post("/query", json={"question": "What is a candidate?"})

    assert response.status_code == 200
    assert response.json()["answer"] == FAKE_ANSWER


def test_returns_the_retrieved_chunks_in_the_documented_shape():
    """The evidence comes back with the answer, translated out of LangChain's types.

    An answer without its evidence cannot be checked. The judge scores
    `grounded` by asking whether the answer is supported by the excerpts, so a
    UI that cannot show them is asking the person to trust the model instead.

    The translation is the point. `rag_query` returns LangChain `Document`s,
    which carry `page_content` and a `metadata` dict. Returning those unchanged
    would put LangChain's field names into the contract and every extra key
    LangChain happens to attach into the browser. The frontend should not know
    what a `Document` is.

    `page` is None for a source that has no pages rather than a missing key, so
    the client reads the same fields for every chunk.
    """
    client = TestClient(create_app(_fake_answer_question))

    response = client.post("/query", json={"question": "What is a candidate?"})

    assert response.json()["chunks"] == [
        # metadata page 0 is the first page of the PDF, exposed as page 1.
        {"text": "first chunk", "source": "a.pdf", "page": 1},
        {"text": "second chunk", "source": "b.docx", "page": None},
    ]


def test_issues_its_own_identifier_for_every_request():
    """Each response carries an id the API generated, not the pipeline's run_id.

    Without an id, a user reporting "the answer was wrong" gives you a sentence
    and nothing else — no way to find which of thousands of queries they mean,
    so no way to look at the trace. The id is what makes a complaint findable.

    Two assertions guarding two different mistakes.

    A different id per request rules out a constant, or one generated once when
    the app is built. Either would return the same string to everybody, which
    correlates nothing.

    Not equal to run_id rules out the easy shortcut. `RagQueryResult` already
    carries LangSmith's identifier and returning it would cost one word — but it
    puts an internal id and the name of our observability vendor into a browser.
    The client gets an opaque string of ours; our logs hold the pairing.
    """
    client = TestClient(create_app(_fake_answer_question))

    first = client.post("/query", json={"question": "one"}).json()
    second = client.post("/query", json={"question": "two"}).json()

    assert first["request_id"] != second["request_id"]
    assert first["request_id"] != FAKE_RUN_ID


def test_rejects_a_request_with_no_question_without_reaching_the_pipeline():
    """A body with no `question` is refused by validation, before our code runs.

    This passes without any implementation, because `question: str` on
    QueryRequest already makes it required — which is the point worth pinning
    rather than assuming. A later change that gave `question` a default, or made
    it optional, would turn a 422 into a 200 answering the empty string, and
    nothing else in the suite would notice.

    The second assertion is the one that teaches. Validation is a gate in front
    of the route, not a check inside it: the spy records every call, and it
    records none. No embedding is paid for, no LLM is called, nothing reaches
    Qdrant. A malformed request costs almost nothing — which is what makes 4xx
    the honest code. There is no work to retry.
    """
    asked = []

    def spy(question: str) -> RagQueryResult:
        asked.append(question)
        return _fake_answer_question(question)

    client = TestClient(create_app(spy))

    response = client.post("/query", json={})

    assert response.status_code == 422
    assert asked == []


def test_rejects_a_question_that_is_empty_or_only_whitespace():
    """A question with no actual text is refused before anything is spent.

    This is the case Pydantic cannot catch for us. `""` is a perfectly valid
    `str`, so `question: str` accepts it and the previous test's 422 never
    fires. `min_length=1` would not help either: `"   "` has length three.

    Left unchecked, an empty question is embedded, searched for and sent to the
    model, which answers something confident about nothing. It costs real money
    and produces a response the caller then has to interpret.

    The spy assertion is the same guard as the missing-question test: refusing
    at the edge means no embedding, no search, no LLM call. That is what makes
    4xx honest here — there is no work to retry.
    """
    asked = []

    def spy(question: str) -> RagQueryResult:
        asked.append(question)
        return _fake_answer_question(question)

    client = TestClient(create_app(spy))

    for blank in ("", "   ", "\n\t "):
        response = client.post("/query", json={"question": blank})
        assert response.status_code == 400, f"{blank!r} was not refused"

    assert asked == []


def test_validation_errors_use_the_standard_error_shape():
    """A failure the framework produced still comes back in our shape.

    Left alone, FastAPI answers a validation failure with its own
    `{"detail": [...]}`, where `detail` is a list of objects — while a refusal
    raised in the route answers `{"detail": "..."}`, where it is a string. Same
    key, two types. No single line of client code reads both.

    Owning the shape means a client writes one error path, not one per source of
    error.
    """
    client = TestClient(create_app(_fake_answer_question))

    response = client.post("/query", json={})

    assert response.status_code == 422
    body = response.json()
    # Nothing else at the top level: no leftover `detail` beside our `error`.
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == "invalid_request"
    # Which field was wrong has to survive the translation. Losing it would
    # leave a client knowing only that something was invalid.
    assert "question" in body["error"]["message"]
    assert body["error"]["request_id"]


def test_refusals_raised_in_the_route_use_the_standard_error_shape():
    """And so does a failure we raised ourselves, with the same three fields.

    request_id matters more here than in a success. When an answer is wrong a
    person might mention it; when a request fails they have nothing else to
    quote. An error response with no id is the one case where correlation is
    most needed and least available.
    """
    client = TestClient(create_app(_fake_answer_question))

    response = client.post("/query", json={"question": "   "})

    assert response.status_code == 400
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["message"] == "question must contain text"
    assert error["request_id"]


def test_an_empty_answer_from_the_model_is_a_server_failure():
    """NoAnswerError is a malfunction, not a refusal, and answers 5xx.

    guardrails.py says so outright — "this is not the model saying it does not
    know" — and lists the causes as a rate limit, a provider error, or the model
    simply stopping. Those are upstream failures, which is why this is 502
    rather than 500: nothing in our code broke, something we depend on returned
    nothing.

    Scored 200 instead, real provider failures would land in the metrics as
    successful queries while users watched a blank screen.
    """

    def returns_nothing(question: str) -> RagQueryResult:
        raise NoAnswerError("The model returned no answer.")

    client = TestClient(create_app(returns_nothing), raise_server_exceptions=False)

    response = client.post("/query", json={"question": "anything"})

    assert response.status_code == 502
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == "no_answer"
    assert error["request_id"]


def test_an_unexpected_failure_answers_500_without_leaking_its_details():
    """Anything unforeseen still comes back in our shape, and says nothing.

    An exception message is written for whoever reads the logs, not for the
    public. A dead Qdrant names a host and a port; a database error can carry a
    query. Passing str(exc) to a client publishes internal topology to anyone
    who can make the server fail.

    So the client gets a fixed sentence and the request_id, which is exactly
    enough to report the problem — and the detail belongs in logs, where the id
    is what joins the two.
    """

    def explode(question: str) -> RagQueryResult:
        raise ConnectionError("qdrant at 10.0.3.7:6333 refused the connection")

    client = TestClient(create_app(explode), raise_server_exceptions=False)

    response = client.post("/query", json={"question": "anything"})

    assert response.status_code == 500
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["request_id"]
    assert "10.0.3.7" not in response.text
    assert "6333" not in response.text


def test_a_model_that_declines_in_words_is_a_successful_answer():
    """ "I cannot answer from these excerpts" is an answer, not a failure.

    The judge has three verdicts and `declined` is correct behaviour when the
    excerpts genuinely lack the answer. A decline is several words long and
    nothing raises, so it is a 200 like any other answer.

    This passes without implementation. It is written down to stop a later,
    well-meant change — a check for "do not contain" that turns a correct
    refusal into a 5xx, and makes a working RAG system look broken in every
    dashboard.
    """
    decline = "The provided excerpts do not contain this."

    def declines(question: str) -> RagQueryResult:
        return RagQueryResult(answer=decline, chunks=[], run_id=FAKE_RUN_ID)

    client = TestClient(create_app(declines))

    response = client.post("/query", json={"question": "anything"})

    assert response.status_code == 200
    assert response.json()["answer"] == decline


def test_the_production_callable_forwards_every_dependency_to_rag_query():
    """The one-argument callable the app wants, built from the six rag_query needs.

    The API layer depends on `answer_question(question) -> RagQueryResult` and
    nothing else. This is where that shape is manufactured: a closure holding
    config, embeddings, model, reranker and the answerer's prompt, built once at
    startup.

    The assertion that matters is `reranker`. rag_query refuses a default for it
    on purpose — "a default of None would let a caller skip reranking by
    forgetting an argument, producing an evaluation_run labelled reranked that
    carries baseline numbers". A new caller is exactly the forgetting this
    guards against, so the test pins that it is forwarded rather than dropped.
    `prompt` is pinned here for the same reason: a dropped one would answer with
    whatever the answerer defaults to while the run claimed otherwise.

    `query` is injected the same way build_reranker takes `load` and
    build_bm25_retriever takes `client`. Production passes nothing and gets the
    real rag_query.
    """
    seen = {}

    def spy(question, config, embeddings, model, reranker, prompt) -> RagQueryResult:
        seen.update(
            question=question,
            config=config,
            embeddings=embeddings,
            model=model,
            reranker=reranker,
            prompt=prompt,
        )
        return _fake_answer_question(question)

    answer_question = build_answer_question(
        "CONFIG", "EMBEDDINGS", "MODEL", "RERANKER", "PROMPT", query=spy
    )

    result = answer_question("a question")

    assert seen == {
        "question": "a question",
        "config": "CONFIG",
        "embeddings": "EMBEDDINGS",
        "model": "MODEL",
        "reranker": "RERANKER",
        "prompt": "PROMPT",
    }
    assert result.answer == FAKE_ANSWER


def test_exposes_pdf_pages_as_human_page_numbers():
    """PyPDFLoader counts from zero; a person reading a PDF counts from one.

    `as_evidence` passed the raw number straight through, so a live response
    returned `"page": 20` for a chunk whose own text reads `Page 21`. A UI built
    on that sends the reader one page early — wrong in the way nobody checks,
    because the number looks perfectly plausible.

    Fixed here rather than in the client. A 0-based index is an implementation
    detail of the loader, and translating internals into the contract is the
    only reason this layer exists. Fixing it in the frontend would mean every
    future client has to know, and would silently be wrong until it did.

    None survives untouched. A docx has no pages, and `None + 1` would crash the
    whole query over a source that simply has none.
    """

    def pages_from_two_sources(question: str) -> RagQueryResult:
        return RagQueryResult(
            answer=FAKE_ANSWER,
            chunks=[
                Document(page_content="front", metadata={"source": "a.pdf", "page": 0}),
                Document(page_content="later", metadata={"source": "a.pdf", "page": 19}),
                Document(page_content="no pages", metadata={"source": "b.docx"}),
            ],
            run_id=FAKE_RUN_ID,
        )

    client = TestClient(create_app(pages_from_two_sources))

    response = client.post("/query", json={"question": "a question"})

    assert [chunk["page"] for chunk in response.json()["chunks"]] == [1, 20, None]


def test_health_reports_ok_without_touching_the_pipeline():
    """GET /health answers 200 while the pipeline stays untouched.

    The load balancer polls this every few seconds and kills the task when it
    stops answering. So it deliberately reports that the process is alive, not
    that it can answer questions: a check that called Qdrant would turn one
    slow dependency into every instance being replaced at once.

    `_fail_if_called` is what proves that. A health route wired to the pipeline
    would pass an assertion on the status code alone.
    """

    def _fail_if_called(question: str) -> RagQueryResult:
        raise AssertionError("/health must not reach the pipeline")

    client = TestClient(create_app(_fail_if_called))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
