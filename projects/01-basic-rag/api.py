"""Serves the RAG pipeline over HTTP.

Beside main.py rather than inside src/, because it is the same kind of thing.
main.py translates terminal commands into calls on the pipeline; this translates
HTTP requests. Neither is pipeline code, and src/ is where the pipeline lives.

The app is built from one callable, not from config, embeddings, model and
reranker. It never uses those — it would only carry them across the room and
hand them to rag_query — and depending on them would mean a test could not run
without Qdrant, because rag_query calls retrieve, which opens a real
vector_store connection.
"""

import uuid
from collections.abc import Callable
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from guardrails import NoAnswerError
from langchain_core.documents import Document
from pydantic import BaseModel
from rag_query import RagQueryResult, rag_query
from starlette.exceptions import HTTPException as StarletteHTTPException


class QueryRequest(BaseModel):
    """What a client is allowed to send.

    Only the question. No TOP_K, no model name, no filters: configuration is an
    implementation decision rather than user intent, and a client that can set
    TOP_K can multiply the bill from a browser console and leave the benchmark
    describing something other than what is running.
    """

    question: str


def as_evidence(chunk: Document) -> dict:
    """One retrieved `chunk`, in the shape the contract promises.

    A translation, not a pass-through. `Document` is LangChain's type, carrying
    `page_content` and a `metadata` dict that also holds whatever else LangChain
    and Qdrant attached along the way. Returning it unchanged would put those
    field names into the contract and that extra metadata into a browser.

    `page` is None rather than absent for a source that has no pages — a docx
    carries none, and the corpus has one. The client then reads the same three
    fields for every chunk instead of testing for a missing key.

    And it is the page a person would turn to, not the loader's index.
    PyPDFLoader counts from zero, so passing the number through returned
    `"page": 20` for a chunk whose own text reads `Page 21` — a UI built on that
    sends the reader one page early, wrong in the way nobody checks because the
    number looks plausible. A 0-based index is the loader's detail, and
    translating details into the contract is the only reason this function
    exists.

    None survives the arithmetic. `None + 1` would fail the whole query over a
    source that simply has no pages.
    """
    metadata = chunk.metadata or {}
    page = metadata.get("page")
    return {
        "text": chunk.page_content,
        "source": metadata.get("source"),
        "page": None if page is None else page + 1,
    }


def error_response(status_code: int, code: str, message: str, request: Request) -> JSONResponse:
    """Every failure, in one shape.

    Without this there are two. FastAPI answers a validation failure with
    `{"detail": [...]}`, a list of objects, and a route's own HTTPException with
    `{"detail": "..."}`, a string — the same key holding two different types, so
    no single line of client code can read both.

    `request_id` is included deliberately. A person whose answer was merely
    wrong can quote the question; a person whose request failed has nothing else
    to quote. The one case where correlation matters most is the one where a
    bare framework error supplies least.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def build_answer_question(
    config,
    embeddings,
    model,
    reranker,
    prompt,
    query: Callable[..., RagQueryResult] = rag_query,
) -> Callable[[str], RagQueryResult]:
    """Make the one-argument callable the app depends on.

    The app wants `answer_question(question) -> RagQueryResult` and nothing
    else. rag_query needs six arguments. This closes over the five that are
    built once at startup, so the route never learns that embeddings or a vector
    store exist.

    `reranker` is forwarded explicitly, never defaulted. rag_query refuses a
    default for it on purpose: forgetting the argument would produce a run
    labelled reranked that carries baseline numbers. A new caller is exactly
    that forgetting, so it is passed here and asserted in the tests.

    `query` is injected the way build_reranker takes `load` and
    build_bm25_retriever takes `client`. Callers pass nothing and get rag_query.
    """

    def answer_question(question: str) -> RagQueryResult:
        return query(question, config, embeddings, model, reranker, prompt)

    return answer_question


def create_app(answer_question: Callable[[str], RagQueryResult]) -> FastAPI:
    """The HTTP app, given something that answers questions.

    A factory rather than a module-level `app`, so a test can pass a fake and
    exercise the HTTP layer with no Qdrant and no OpenRouter. The same shape as
    build_reranker's `load` and build_bm25_retriever's `client`.
    """
    app = FastAPI()

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        """One id per request, before anything else runs.

        It cannot be generated in the route. A validation failure is answered
        before the route is called at all, so an id made there would not exist
        for exactly the responses that need one. Middleware runs first, and the
        route and both handlers read the same value — one request, one id.
        """
        request.state.request_id = str(uuid.uuid4())
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        """Pydantic's complaint, in our shape, without losing which field."""
        first = exc.errors()[0]
        # loc is like ("body", "question"); drop the location kind and keep the
        # path, so the message names the field rather than only the problem.
        field = ".".join(str(part) for part in first["loc"][1:])
        message = f"{field}: {first['msg']}" if field else first["msg"]
        return error_response(422, "invalid_request", message, request)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        """Registered on Starlette's class, not FastAPI's subclass.

        FastAPI's HTTPException inherits from it, so this catches ours — and
        also the ones Starlette raises itself, such as the 404 for an unknown
        path. Registering on the subclass would leave those answering in the
        default shape, which is the inconsistency this handler exists to remove.
        """
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return error_response(exc.status_code, code, str(exc.detail), request)

    @app.exception_handler(NoAnswerError)
    async def handle_no_answer(request: Request, exc: NoAnswerError):
        """The model wrote nothing. A malfunction, not a refusal.

        502 rather than 500: nothing in our code broke — something upstream
        returned nothing. guardrails.py is explicit that this is "not the model
        saying it does not know", and lists the causes as a rate limit, a
        provider error, or the model stopping.

        The message is safe to pass on because it is ours, fixed text written
        for a person rather than anything the provider handed back.
        """
        return error_response(502, "no_answer", str(exc), request)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        """Anything unforeseen, in our shape, saying nothing.

        Without this the response is not merely the wrong shape — it is not JSON
        at all. Starlette answers an unhandled exception with plain text, so a
        client parsing the error contract gets a decoder error on top of a
        failure.

        The message is fixed. An exception message is written for whoever reads
        the logs: a dead Qdrant names a host and a port, a database error can
        carry a query. Returning str(exc) publishes internal topology to anyone
        who can make the server fail. The client gets the request_id, which is
        enough to report it; the detail is still logged, because Starlette
        re-raises after this handler has produced the response.
        """
        return error_response(
            500,
            "internal_error",
            "The request could not be completed.",
            request,
        )

    # No dependency on answer_question, unlike /query. The load balancer polls
    # this every few seconds to decide whether this instance should keep
    # receiving traffic, so it answers from the process itself: it reports that
    # the server is up, not that Qdrant and OpenRouter are reachable.
    #
    # That split is deliberate. A check that called the pipeline would report a
    # slow Qdrant as every instance being unhealthy, and the load balancer would
    # replace all of them at once over a dependency that replacing them cannot
    # fix.
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # `def`, not `async def`. rag_query is synchronous, and FastAPI runs a plain
    # `def` route in a thread pool — so slow calls do not block anything else.
    # An `async def` route calling the same blocking function would freeze the
    # whole server for the duration of every question.
    @app.post("/query")
    def query(payload: QueryRequest, request: Request) -> dict:
        # Pydantic cannot catch this one. `""` is a valid `str`, so
        # `question: str` accepts it, and `min_length=1` would not help either
        # because `"   "` has length three. Checked here, where whitespace can
        # be stripped first.
        #
        # 400 rather than the 422 a missing field returns. Both are the client
        # sending something unusable, so this is a deliberate split — 422 for a
        # shape the schema rejects, 400 for a value the schema allows but the
        # route will not act on.
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must contain text")

        # The stripped question, not the original: what was validated is what
        # gets answered, so there is only ever one notion of "the question".
        result = answer_question(question)
        return {
            "answer": result.answer,
            "chunks": [as_evidence(chunk) for chunk in result.chunks],
            # From the middleware, not generated here, so a success and a
            # failure on the same request carry the same id.
            "request_id": request.state.request_id,
        }

    return app
