# Roadmap

Where this is heading, and why. Kept short and rewritten freely — this records
intent, not commitments.

## Ideas backlog

- **Evaluation.** Clustering and sampling over the corpus, an LLM generating
  synthetic `golden_example`s from it, then LLM-as-judge scoring. A project in its
  own right, and it wants its own design session.
- **The same thing in LlamaIndex.** Project 02. Built in parallel with 01 rather
  than swapped in, so each framework is written in its own natural style. The
  comparison is the point.
- **Agentic RAG.** Add the `agent`, `tool_call`s and a `trace` on top of what 01
  builds. The reason this repo has that name.
- **Multi-agent work in a separate repo**, same workspace, plugged into this one to
  solve a real business problem. Early and unconfirmed — nothing is designed for it.
- **Frontend and backend repos** wrapping this later. The reason project 01 keeps
  its logic in components rather than inside the terminal command.

## Open questions

- Which vector store to standardise on, if any. Project 01 uses Qdrant; whether
  later projects follow is open. Whatever is chosen has to delete by `document`.
- Which evaluation approach to use across projects, so results stay comparable.
  Sketched in the backlog above, not designed.

## Log

| Date | Note |
|------|------|
| 2026-09-01 | Repo created: monorepo layout, uv + ruff + pytest, CI on push and PR. |
| 2026-09-01 | Project 01 designed: a plain RAG skeleton, seven thin components end to end. |
| 2026-09-02 | Switched 01 to LangChain used directly. Purpose is now comparing frameworks, so vocabulary moved to LangChain's names. |
