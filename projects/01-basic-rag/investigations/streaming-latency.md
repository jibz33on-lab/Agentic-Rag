# Investigation: latency before the first visible answer token

Conducted 2026-09-02 against project 01. All numbers below were measured; none
are estimated. Where something is inferred rather than observed, it says so.

## 1. Executive summary

Answering a question took anywhere from 2 to 26 seconds, with no pattern in the
input. Retrieval was consistently ~1–2s and was never the problem.

The cause is **reasoning tokens**. `deepseek-v4-flash` reasons before answering,
by a provider default that this repo never set. During reasoning the HTTP stream
is active and delivering events, but none of them carry answer text. LangChain
parses that stream, keeps the `content` field and drops `reasoning`, so the
application receives objects that are genuinely empty and has no way to know the
model is working.

In the most extreme run measured, 506 of 547 chunks carried no answer content,
and the first answer character arrived at 19.065s of a 20.3s request.

Disabling reasoning roughly halved latency on the real application: median 8.3s
to 5.3s, worst case 16.0s to 8.1s, across eleven runs.

## 2. Problem statement

The pipeline is:

```
question → embed → Qdrant search → LLM → stream → terminal
```

Observed latency for comparable questions ranged from 2.5s to 26.3s. Nothing in
the application logs, in LangChain's objects, or in LangSmith's traces explained
the difference. Identical questions produced different totals.

## 3. Initial hypotheses

1. **Retrieval** — embedding the query or searching Qdrant was slow.
2. **Provider routing** — OpenRouter serves this model from ~31 providers; a
   slow one was being picked on some requests.
3. **Model choice** — `deepseek-v4-flash` was simply a slow model.
4. **Token throughput** — generation was slow once started.

All four were tested. All four were wrong.

## 4. Test methodology

Three instruments, in increasing directness:

**a. Application-level timing.** `main.py` prints time-to-first-word and total
under every answer, split from retrieval.

**b. `scripts/latency_test.py`.** Sends one fixed short prompt through LangChain,
outside the RAG pipeline, and records the arrival time and full object of every
streamed chunk — `content`, `additional_kwargs`, `response_metadata`,
`usage_metadata`.

**c. `scripts/raw_stream_test.py`.** Sends the same prompt to OpenRouter over
plain HTTP with **no LangChain in the path**, and prints the raw server-sent
events. Takes `off` as an argument to disable reasoning.

The prompt was fixed — *"In one sentence, what is a vector database?"* — and
runs were taken back to back to limit time-of-day effects.

## 5. Experimental results

### Retrieval is not the problem

| source | measurement |
|---|---|
| LangSmith trace, `VectorStoreRetriever` | 0.59s |
| application timing | 1.2s, 2.1s |
| embedding one query alone | 1.71s |

Consistently 0.6–2.1s, and excluded entirely from the stream tests below.

### Through LangChain — nine runs, identical prompt

| total | 1st chunk | 1st text | chunks | empty |
|---|---|---|---|---|
| 1.19s | 0.65s | 1.02s | 27 | 20 |
| 2.39s | 1.05s | 1.15s | 25 | 7 |
| 2.55s | 1.59s | 2.18s | 24 | 17 |
| 3.25s | 1.55s | 1.63s | 23 | 5 |
| 3.37s | 1.23s | 1.32s | 30 | 8 |
| 5.50s | 3.81s | 5.13s | 42 | 22 |
| 5.96s | 5.75s | 5.94s | 27 | 13 |
| **20.32s** | 1.34s | 1.34s | **547** | **506** |
| **20.68s** | 5.03s | 5.03s | **380** | **340** |

The two slow runs received 13–20× more chunks, over 90% of which carried no text.

### Provider pinning — no effect

Format is *first token → total*.

| configuration | run 1 | run 2 |
|---|---|---|
| OpenRouter default | 5.0s → 6.0s | 6.4s → 6.6s |
| pinned to DeepInfra | 6.3s → 7.0s | 4.2s → 4.4s |
| pinned to Together | 5.9s → 6.3s | 1.7s → 1.8s |

Both the fastest and a middling run came from the same provider. Hypothesis 2
not supported.

### Model comparison — the current model was the best

Totals, three runs each:

| model | runs |
|---|---|
| `deepseek-v4-flash-0731` | 2.7s, 3.3s, 2.0s |
| `minimax-m3:free` | 9.4s, 3.0s, 8.3s |
| `nemotron-3.5-lightning:free` | 25.1s, 55.5s, 91.5s |
| `gemma-4-31b:free` | failed — rate limited |

Hypothesis 3 not supported; switching model would have made it worse.

## 6. Raw stream evidence

Reading OpenRouter's stream directly, the delta fields present were:

```
['content', 'reasoning', 'reasoning_details', 'role']
```

`reasoning` and `reasoning_details` are real fields carrying real text. Examples
captured verbatim:

```
"Final response in one sentence. Keep it concise."

"We need to answer 'In one sentence, what is a vector database?'
 The user wants a single sentence definition. Keep it concise and clear."
```

The same stream also contains OpenRouter keep-alive comment lines:

```
: OPENROUTER PROCESSING
```

### The same chunks, seen through LangChain

```python
AIMessageChunk(
    content='',
    additional_kwargs={},
    response_metadata={'model_provider': 'openai'},
    tool_calls=[], invalid_tool_calls=[], tool_call_chunks=[]
)
```

Nothing in `additional_kwargs`, `response_metadata` or `usage_metadata`. The
reasoning text present on the wire is absent from the object.

### Timeline of the 20.3-second run

```
0.000s   request sent
   |
   |     retrieval not included in this test
   |
1.342s   first raw stream event          ' '
   |
   |     503 events, ~30ms apart, no answer content
   |     the connection is active throughout
   |
19.065s  first answer content            'A'
   |
   |     39 answer events
   |
20.257s  answer complete                 '.'
20.312s  stream closed
```

**Eighteen seconds of active streaming carrying no answer text, then a 1.2-second
answer.**

### Before and after, on the real application

Same question, back to back, totals in seconds:

| | runs | median | best | worst |
|---|---|---|---|---|
| reasoning ON | 7.0, 8.3, 8.7, 8.8, 16.0 | 8.3s | 7.0s | 16.0s |
| reasoning OFF | 3.4, 3.4, 4.0, 6.0, 6.6, 8.1 | **5.3s** | **3.4s** | **8.1s** |

The worst reasoning-off run is roughly the reasoning-on median.

### A correctness failure, not only a latency one

One reasoning-enabled run produced **zero answer chunks**. Its entire output was:

```
- 1. "A thinking" is a phrase that is a phrase. This is a test of the AI.<｜end▁of▁sentence｜>
```

Degenerate reasoning ending in a leaked DeepSeek control token, and no answer at
all. Through the application this would have printed a blank line with no error.

## 7. What the evidence proves

Directly observed, reproducible:

- **Reasoning events exist in the stream.** Read off the wire, with text.
- **They can consume the overwhelming majority of a request.** 506 of 547
  chunks; 18 of 20.3 seconds.
- **The connection is active during that period.** Events arrive every ~30ms.
- **LangChain does not surface them.** The same chunks appear as `content=''`
  with nothing in any other field.
- **Retrieval is not the cause.** 0.6–2.1s consistently, and excluded from the
  stream measurements entirely.
- **Provider choice is not the cause.** Three configurations, same spread.
- **Model choice is not the cause.** The alternatives were worse.
- **Disabling reasoning reduces latency here.** Eleven runs, consistent
  direction, median 8.3s → 5.3s.
- **Reasoning can produce no answer at all.** Observed once in roughly ten runs.

## 8. What the evidence does NOT prove

- **That the original 26.3-second run was caused by reasoning.** That run
  predates the instrumentation. The mechanism explains it and everything is
  consistent, but it was not observed.
- **That disabling reasoning eliminates the long tail.** No run over 20s occurred
  in either configuration during the before/after comparison. Absence over eleven
  runs is weak evidence.
- **That eleven runs establish the size of the improvement.** The direction is
  consistent; the magnitude is not precisely characterised.
- **That reasoning never helps.** Every measurement used one short prompt. The
  real RAG prompt is ~1,300 tokens with four excerpts and asks the model to
  answer only from them. Reasoning was not evaluated on that task.
- **That LangChain adds no latency of its own.** Not measured. Raw and LangChain
  runs were not paired on the same request.

## 9. Root cause / current best explanation

**Labelled as explanation, not fact.**

The model emits two kinds of streamed event: reasoning and answer content. When
reasoning is enabled, reasoning events may be emitted first, sometimes for many
seconds. The stream is active throughout — the client is receiving data — but
none of it is answer text. The application sees nothing until the model
transitions to answer content.

LangChain compounds this. It parses the stream, exposes `content`, and discards
`reasoning`, so reasoning events reach the application as empty chunks. The
delay is therefore invisible at every level the application can see.

### This is NOT "the network waits until all tokens arrive"

That description is wrong and would send an investigation in the wrong direction.
The stream is neither idle nor buffered. Events arrive continuously at ~30ms
intervals for the entire delay. The accurate description is:

> The model and provider stream multiple event types. Reasoning events may be
> emitted before answer-content events. The raw stream is active during this
> period, but the application receives no visible answer content until the model
> transitions to answer content. LangChain's parsing further hides the reasoning
> from the application's content stream.

## 10. Why latency appears random

The amount of reasoning varies enormously for identical input:

| reasoning chunks | characters |
|---|---|
| 6 | 48 |
| 12 | 93 |
| 18 | 135 |
| 21 | 212 |
| 38 | 306 |
| ~506 | not captured |

Same prompt, same model, same settings. Nothing on the client side changes.
Latency tracks how much the model decides to think, which is not controllable
from here and not predictable in advance.

This is why every client-side comparison — providers, models, sampling — showed
noise rather than signal.

## 11. Role of reasoning vs answer generation

These are separate phases with very different costs.

**Answer generation is fast and stable.** Every run wrote its answer in roughly
1–1.4 seconds, whether the total was 2 seconds or 20.

**Reasoning is slow and unbounded.** 0.05s to 18s for the same prompt.

Consequently, optimisations aimed at generation — a smaller model, shorter
answers, fewer input tokens — address the part that was never slow.

## 12. Role of LangChain's stream parsing

LangChain's `ChatOpenAI.stream()` yields `AIMessageChunk` objects built from the
provider's events. Fields it does not model are dropped silently. `reasoning` and
`reasoning_details` are dropped.

Consequences:

- Reasoning arrives as chunks whose `content` is `''`.
- No exception, warning or metadata indicates anything was discarded.
- The reasoning text is unrecoverable through the LangChain interface.
- LangSmith traces inherit the gap, since they record what LangChain produced.

This is the expected behaviour of an abstraction, not a defect. It is worth
recording because this repository exists to compare LangChain against LlamaIndex,
and how each handles unrecognised provider fields is a genuine point of
comparison.

## 13. Impact on agentic RAG UX

**Streaming does not mitigate this.** Streaming is meant to let the user read
while the answer is produced. Here no visible text exists until the answer is
essentially complete — in the 20.3s run, second 19 of 20. The user watches a
blank screen and then receives everything at once.

**Silent failure is worse than slowness.** The zero-answer run reached the
terminal as an empty line and no error.

**The cost multiplies in agentic systems.** This is a single LLM call. An agent
making five tool calls would pay the reasoning delay five times, with the
variance compounding.

## 14. Recommended next investigation

1. **Catch a >20s run with instrumentation attached**, closing the gap in §8.
   Run `scripts/raw_stream_test.py` in a loop until one occurs and record the
   reasoning character count.
2. **Evaluate reasoning on the real RAG prompt**, not the short test prompt.
   1,300 tokens, four excerpts, answer-only-from-excerpts. Compare answer quality
   with reasoning on and off against a fixed set of `golden_example`s.
3. **Measure LangChain's own overhead** by issuing paired raw and LangChain
   requests and comparing time-to-first-event.
4. **Establish the distribution properly** — 30+ runs per configuration, reported
   as P50/P95/P99 rather than medians of five.

## 15. Instrumentation and metrics to add

Currently the application reports time-to-first-word and total. That was enough
to notice the problem and not enough to explain it.

Worth adding:

| metric | why |
|---|---|
| time to first raw stream event | separates provider queueing from reasoning |
| reasoning duration and character count | the actual variable |
| time to first answer-content token | what the user experiences |
| answer generation duration | shown here to be stable; confirms it stays so |
| count of empty vs content chunks | the signature of this failure |
| provider that served the request | OpenRouter returns this; not currently captured |

The first, second and last are not obtainable through LangChain and require
reading the raw stream or OpenRouter's generation metadata.

## 16. Conclusion

High latency was caused by reasoning tokens emitted before answer content, made
invisible by LangChain dropping the `reasoning` field. It was not retrieval, not
provider routing, not model choice, and not token throughput — each tested and
excluded.

Reasoning is now disabled in `answerer.py` via
`extra_body={"reasoning": {"enabled": False}}`, which is the only route available
since it is an OpenRouter feature LangChain has no parameter for. Median latency
on the real application fell from 8.3s to 5.3s across eleven runs.

A guardrail was added in `guardrails.py` raising on an empty answer, since the
same investigation found a run that produced no answer and reported no error.

The mechanism is established by direct observation. The link to the original
26.3-second run is a strong inference, not a measurement.

## Open questions

- Why does reasoning length vary so dramatically between identical requests?
- Is that variability controlled by the model, the provider, or OpenRouter's
  routing between providers?
- Does LangChain introduce buffering or latency of its own? Unmeasured.
- Does OpenRouter's adapter alter reasoning handling per provider?
- Could reasoning be streamed to the UI separately, turning dead time into
  visible progress?
- Is disabling reasoning right for simple RAG queries but wrong for complex
  agentic or tool-use tasks?
- Should reasoning be enabled per call rather than per application?
