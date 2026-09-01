# Agentic RAG

A growing series of self-contained mini projects exploring agentic retrieval-augmented
generation. Each project stands on its own; shared building blocks get promoted into
`shared/` only once two or more projects genuinely need them.

## Projects

| # | Project | What it explores | Status |
|---|---------|------------------|--------|
| — | _first project not started yet_ | — | — |

## Layout

```
.
├── projects/          # one folder per mini project (see projects/README.md)
├── shared/            # created on demand, when real repetition appears
├── docs/roadmap.md    # what's planned and why
└── pyproject.toml     # one environment for the whole repo
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups     # create .venv and install dev tooling
cp .env.example .env     # then fill in your keys
```

## Common commands

```bash
uv run ruff check .            # lint
uv run ruff format .           # format
uv run pytest                  # all tests
uv run pytest projects/01-x    # one project's tests
uv run pytest --cov            # coverage (fails under 80%)
uv add <package>               # add a dependency
```

## Conventions

- One environment for the whole repo — dependencies live in the root `pyproject.toml`.
- New projects are numbered in the order they are started, and the number never changes.
- Every project carries its own `README.md` explaining the idea and how to run it.
- Secrets go in `.env` (git-ignored); `.env.example` lists the keys without values.
