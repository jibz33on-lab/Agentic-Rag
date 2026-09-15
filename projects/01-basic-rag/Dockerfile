# The image for project 01's HTTP API.
#
# Built from the repo root, because pyproject.toml and uv.lock live there and
# nothing inside projects/01-basic-rag/ can reach up to them:
#
#   docker compose build api          # what you will actually run
#   docker build -f projects/01-basic-rag/Dockerfile -t agentic-rag-api .
#
# It runs the API and nothing else. No main.py, no corpus, no reranker. See
# designs/containerisation.md for why each of those is absent.


# ---------------------------------------------------------------------------
# The base: an official Python 3.12, with the extras stripped out.
#
# "slim" is the same Debian and the same Python as the full image with the
# documentation, headers and build tooling removed — about 50 MB rather than
# 350 MB. Everything this API needs ships as a prebuilt wheel, so no compiler
# is required at install time.
#
# The version is pinned to match .python-version and requires-python in
# pyproject.toml. An image that floats to a new Python is an image that can
# break without anyone changing a line.
# ---------------------------------------------------------------------------
FROM python:3.12-slim


# ---------------------------------------------------------------------------
# Bring in uv, the tool that reads uv.lock.
#
# COPY --from=<image> copies files out of *another* image instead of out of the
# build context. Astral publish one containing just the uv binaries, so this is
# two files rather than an install script, a download and a cleanup.
#
# Pinned to the version in use on the host (uv 0.9.15). uv reads the lockfile
# format, so a floating version is a floating reader of a pinned file.
# ---------------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.9.15 /uv /uvx /bin/


# ---------------------------------------------------------------------------
# Environment for the build and for the running process.
#
# ENV sets variables that persist into the image, unlike a shell export inside
# a RUN, which vanishes when that instruction ends.
# ---------------------------------------------------------------------------
ENV \
    # uv defaults to hardlinking packages from its cache into the venv. Across
    # Docker's layered filesystem that fails and warns on every build; copying
    # is what it falls back to anyway.
    UV_LINK_MODE=copy \
    # Precompile .pyc files at build time. Without it every module is compiled
    # on first import — and the process runs as a user that cannot write to
    # /app, so it would recompile on every single start.
    UV_COMPILE_BYTECODE=1 \
    # Never fetch a Python interpreter. Use the one this base image ships.
    # Without this, a mismatch would be silently papered over by a download.
    UV_PYTHON_DOWNLOADS=never \
    # Send Python's output straight to the terminal instead of buffering it.
    # Buffered logs are the reason a crashing container so often looks silent:
    # the traceback is still in a buffer when the process dies.
    PYTHONUNBUFFERED=1 \
    # Put the virtualenv's binaries first on PATH, so `uvicorn` is simply found
    # and no command needs wrapping in `uv run`.
    PATH="/app/.venv/bin:$PATH"


# ---------------------------------------------------------------------------
# The working directory: the repo root, mirrored.
#
# WORKDIR creates the directory and makes it the current directory for every
# instruction after it — and for the running process. The layout inside the
# image matches the layout of the repo on purpose, so that the command below is
# the one you would type on your own machine.
# ---------------------------------------------------------------------------
WORKDIR /app


# ---------------------------------------------------------------------------
# Dependencies, before the source. This ordering is the whole reason rebuilds
# are fast.
#
# Every instruction produces a layer, and Docker reuses a cached layer when that
# instruction's inputs are unchanged. Dependencies change rarely; api.py changes
# constantly. Installed first, editing api.py reuses this layer and rebuilds in
# about a second. Done the other way round, every edit reinstalls LangChain.
#
#   --frozen   use uv.lock exactly as written; do not re-resolve. This is what
#              makes the container's versions identical to the host's, which is
#              most of what an image is for.
#   --no-dev   leave out the dev group: pytest, pytest-cov, ruff.
#
# The rerank extra is NOT installed, which leaves out sentence-transformers and
# torch — roughly 2 GB. See the warning at the foot of this file.
# ---------------------------------------------------------------------------
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev


# ---------------------------------------------------------------------------
# The application: only what the API actually runs.
#
# Not main.py, not tests/, not conftest.py, not designs/ — this image serves
# HTTP and does nothing else. Forgetting a file here kills the container at
# startup with `No module named ...`, which is loud enough to be safe.
#
# asgi.py builds the pipeline at import; api.py is the app; src/ is the
# pipeline. asgi.py finds src/ relative to its own location, which is why the
# two must keep this arrangement.
# ---------------------------------------------------------------------------
COPY projects/01-basic-rag/asgi.py projects/01-basic-rag/api.py ./projects/01-basic-rag/
COPY projects/01-basic-rag/src/ ./projects/01-basic-rag/src/


# ---------------------------------------------------------------------------
# Drop root.
#
# A container is isolated processes on the host kernel, not a virtual machine,
# so uid 0 inside is uid 0 outside. This API reads its own files and makes
# outbound HTTPS calls; it needs none of root's privileges.
#
# Everything above stays owned by root and world-readable, which is what we
# want: the process can read the code and cannot modify it. Nothing here writes
# at run time.
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 app
USER app


# ---------------------------------------------------------------------------
# Documentation, not configuration. EXPOSE publishes nothing and opens nothing;
# it records which port the process listens on, for whoever reads the image
# later. Compose's `ports:` is what actually forwards it.
# ---------------------------------------------------------------------------
EXPOSE 8000


# ---------------------------------------------------------------------------
# The default command: what runs when a container starts.
#
#   --app-dir projects/01-basic-rag   where asgi.py lives, relative to /app
#   --host 0.0.0.0                    accept connections on every interface.
#                                     NOT optional. Uvicorn defaults to
#                                     127.0.0.1, which inside a container means
#                                     "reachable only from inside this
#                                     container" — the log says `Uvicorn
#                                     running` and the browser says connection
#                                     refused.
#
# No --reload: that watches files for changes, and the files in an image never
# change.
#
# The list form runs uvicorn directly as the container's main process, with no
# shell in between. A shell would swallow the stop signal, and `docker compose
# down` would wait ten seconds and then kill it.
# ---------------------------------------------------------------------------
CMD ["uvicorn", "asgi:app", "--app-dir", "projects/01-basic-rag", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# WARNING — this image cannot rerank.
#
# The rerank extra is deliberately not installed, because RERANKER_MODEL ships
# empty: reranking was measured in designs/reranking.md, missed its bar, and was
# switched off. Installing it anyway would add ~2 GB of torch to every build for
# a component nothing calls.
#
# Consequence: set RERANKER_MODEL in .env and this container DIES AT STARTUP
# with `No module named 'sentence_transformers'`. asgi.py calls build_reranker
# at import, and reranker.py imports sentence-transformers inside it.
#
# That is the intended fail-fast — designs/api.md argues a bad configuration
# should refuse to go live rather than serve 500s — but the message names a
# missing module rather than its cause, which is why it is written down here.
# To rerank in a container, add `--extra rerank` to the uv sync above and expect
# a much larger image.
# ---------------------------------------------------------------------------
