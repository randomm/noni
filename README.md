# noni — attachable product direction for any Git project

**noni** is the product we are designing: a light layer you attach to any Git-based
software project that gives the agent(s) working in that project the skills to manage
**the project's backlog, product direction and release planning** — with the operator or
user in the loop, steering when they choose to.

The idea came from running a plan driver on a ticket-heavy project: a flood of
incoming tickets made it clear the project needed a clean, separate place where
product direction and release planning were decided — apart from the tracker that
carries the work. noni makes that place a product that attaches to any project.

## The purity rule

This repository holds only generic product direction: positioning, research, design,
specs, and the skills we ship. It holds **no project-specific content** — no tickets,
no backlog entries, no references to any attached project's content. When noni is taken
into use, it becomes an integral part of the project it attaches to: the *how* ships
from here, the *what* lives inside the attached project.

## Development

Install the pinned dev tools, then run the two gates. The versions are pinned
exactly in `pyproject.toml` and in CI, so local and CI run the same tools.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/ruff check .                                          # lint
.venv/bin/coverage run -m pytest                                # test under coverage
.venv/bin/coverage combine                                      # merge subprocess data
.venv/bin/coverage report                                       # report; fails below 80%
```

The coverage command measures the seven Python product modules and enforces
the at-least-80% rule from `AGENTS.md`. `coverage combine` is required, not
optional: `register.py`, `claim.py` and `census-sessions.py` run as
subprocesses, so their data lands in separate files that only combine merges.
See `docs/PUBLISHING.md` for the pre-publish public-repo scrub.

## Status

- Positioning & design complete: three verified research runs (competitor
  landscape, skill-first packaging, coordination substrate) plus a two-clone
  claim prototype settled the architecture. Read `docs/PRODUCT.md` — it is the
  product document; the epic issue set (E1–E5) is on GitHub, filed via the
  plan driver.
- Origin: the private backlog + reliability skill that grew this idea now live
  in a separate repository (full history preserved there); the driver's public
  work lives in its own repository.
