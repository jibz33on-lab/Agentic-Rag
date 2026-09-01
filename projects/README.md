# Projects

One folder per mini project, numbered in the order it was started. Numbers are
permanent — they are how projects are referred to elsewhere in the repo.

## Structure

```
projects/NN-short-name/
├── README.md      # the idea, how to run it, what was learned
├── conftest.py    # makes src/ importable in this project's tests
├── designs/       # one file per design session
├── src/
└── tests/
```

## Starting a new one

```bash
mkdir -p projects/NN-short-name/{designs,src,tests}
```

Add a `conftest.py` at the project root so its `src/` is importable from its tests
without any packaging ceremony:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
```

Then add a row to the table in the top-level `README.md`.

## Design docs

Each design session produces one file in `designs/`, written at the end of a
`grill-me` session. List them in the project's own `README.md` under a `## Designs`
heading:

```markdown
## Designs

- ingestion — designs/ingestion.md
- retrieval — designs/retrieval.md
```

The list lives with the project rather than at the repo root, so finishing a design
means editing a file in the folder you are already working in.

## Promoting shared code

When a second project needs something a first one already has, move it to
`shared/` and import it from both. Not before — duplicated code that is still
being figured out is cheaper than the wrong abstraction.
