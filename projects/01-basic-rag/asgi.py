"""The production entry point: builds the real pipeline and hands it to the app.

    uv run uvicorn asgi:app --app-dir projects/01-basic-rag --reload

Separate from api.py because everything here happens at **import time**. Reading
.env and constructing the embedding client, the chat model and the reranker are
side effects, and api.py must stay importable without them — every test in
test_api.py imports it, and none of them should need a key or a running Qdrant.

So api.py holds the shape of the service, and this holds one specific way of
filling it in. Run from the repo root, like main.py, so .env resolves.

Everything is built once, here, before the first request:

  - An expensive client rebuilt per request would add its construction to every
    answer.
  - build_reranker raises when RERANKER_MODEL is set but unusable. Built here,
    the process never starts and a bad deploy refuses to go live. Built per
    request, the server looks healthy and returns 500 to everybody.

None of it is state. All four are derived from the environment, identical on
every instance, and rebuildable at any moment — so a second copy of this process
answers exactly the same way, which is what lets there be a second copy at all.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# The same line main.py carries, for the same reason: api.py and the pipeline it
# calls live in src/, and nothing else puts that on the path at runtime. Tests
# get it from conftest.py; uvicorn's --app-dir reaches this file but not the
# package beside it.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from answerer import build_chat_model
from api import build_answer_question, create_app
from config import load_config
from embeddings import build_embeddings
from reranker import build_reranker

load_dotenv(".env")  # third-party libraries read os.environ, not our config
_config = load_config(os.environ)

app = create_app(
    build_answer_question(
        _config,
        build_embeddings(_config),
        build_chat_model(_config),
        build_reranker(_config),
    )
)
