"""Compare latency with the model's reasoning on or off.

Talks to OpenRouter directly, with no LangChain in the way, so the reasoning
tokens are visible. LangChain only exposes `content` and silently drops
`reasoning`, which is why those chunks looked empty.

Run it from the repo root. Reasoning is on unless you say otherwise:

    uv run python scripts/raw_stream_test.py          # reasoning on
    uv run python scripts/raw_stream_test.py off      # reasoning off

Run each one several times. A single run tells you nothing — the whole problem
is that the same request sometimes takes 2 seconds and sometimes 20.
"""

import json
import sys
import time
import urllib.request

from dotenv import dotenv_values

env = dotenv_values(".env")
model_name = env.get("ANSWERER_MODEL") or "deepseek/deepseek-v4-flash-0731"
PROMPT = "In one sentence, what is a vector database?"

reasoning_off = len(sys.argv) > 1 and sys.argv[1].lower() == "off"

body = {
    "model": model_name,
    "messages": [{"role": "user", "content": PROMPT}],
    "temperature": 0,
    "stream": True,
}
if reasoning_off:
    body["reasoning"] = {"enabled": False}

request = urllib.request.Request(
    "https://openrouter.ai/api/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={
        "Authorization": f"Bearer {env['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
    },
)

start = time.monotonic()
first_reasoning_at = None
first_answer_at = None
reasoning_text = ""
answer_text = ""
reasoning_chunks = 0
answer_chunks = 0

with urllib.request.urlopen(request, timeout=180) as response:
    for raw in response:
        line = raw.decode("utf-8").rstrip("\n")
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            payload = json.loads(line[len("data: ") :])
        except json.JSONDecodeError:
            continue

        now = time.monotonic() - start
        for choice in payload.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("reasoning"):
                if first_reasoning_at is None:
                    first_reasoning_at = now
                reasoning_text += delta["reasoning"]
                reasoning_chunks += 1
            if delta.get("content"):
                if first_answer_at is None:
                    first_answer_at = now
                answer_text += delta["content"]
                answer_chunks += 1

total = time.monotonic() - start


def seconds(value):
    return f"{value:.2f}s" if value is not None else "never"


print(f"reasoning {'OFF' if reasoning_off else 'ON'}   model {model_name}")
print(f"  total time          {total:.2f}s")
print(f"  first answer word   {seconds(first_answer_at)}")
print(f"  reasoning chunks    {reasoning_chunks}   ({len(reasoning_text)} chars)")
print(f"  answer chunks       {answer_chunks}   ({len(answer_text)} chars)")
if reasoning_text:
    print(f"  thinking started at {seconds(first_reasoning_at)}")
    print(f"  what it thought     {reasoning_text[:200]!r}")
