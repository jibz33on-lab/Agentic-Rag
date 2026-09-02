"""Measure how a streamed answer actually arrives from OpenRouter.

This does not touch the RAG pipeline. It sends one short, fixed prompt to the
same model, with the same API key and base URL that answerer.py uses, and
reports the timing of every chunk that comes back.

Run it from the repo root:

    uv run python scripts/latency_test.py
"""

import time

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

# The same three settings as projects/01-basic-rag/src/answerer.py
BASE_URL = "https://openrouter.ai/api/v1"
PROMPT = "In one sentence, what is a vector database?"

env = dotenv_values(".env")
model_name = env.get("LLM_MODEL") or "deepseek/deepseek-v4-flash-0731"

print(f"model     {model_name}")
print(f"base url  {BASE_URL}")
print(f"prompt    {PROMPT!r}")
print()

model = ChatOpenAI(
    model=model_name,
    api_key=env["OPENROUTER_API_KEY"],
    base_url=BASE_URL,
    temperature=0,
)

# Everything below is measured from this moment.
start = time.monotonic()

first_chunk_at = None
first_text_at = None
last_chunk_at = None
chunk_count = 0
empty_count = 0

for chunk in model.stream(PROMPT):
    now = time.monotonic() - start
    chunk_count += 1

    if first_chunk_at is None:
        first_chunk_at = now
    if chunk.content and first_text_at is None:
        first_text_at = now
    if not chunk.content:
        empty_count += 1
    last_chunk_at = now

    # Everything the chunk carries, not just its text. The empty chunks are
    # the thing under investigation, so we need to see what else is in them.
    print(f"--- chunk {chunk_count}  at {now:.3f}s " + "-" * 30)
    print(f"  repr             {chunk!r}")
    print(f"  content          {chunk.content!r}")
    print(f"  additional_kwargs {chunk.additional_kwargs!r}")
    print(f"  response_metadata {chunk.response_metadata!r}")
    print(f"  usage_metadata   {getattr(chunk, 'usage_metadata', None)!r}")

total = time.monotonic() - start


def seconds(value):
    """Format a measurement, or say so when it never happened."""
    return f"{value:.3f}s" if value is not None else "never"


print()
print("  total request time       ", seconds(total))
print("  time to first chunk      ", seconds(first_chunk_at))
print("  time to first text       ", seconds(first_text_at))
print("  time to final chunk      ", seconds(last_chunk_at))
print("  chunks received          ", chunk_count)
print("  of which empty           ", empty_count)
