# Contributing to noni

noni is a Python 3.11 project with two gates: `ruff` for linting and `pytest`
under `coverage` for tests. Both run locally and in CI on the same pinned tool
versions.

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

The coverage command measures the Python product modules and enforces
the at-least-80% rule from `AGENTS.md`. `coverage combine` is required, not
optional: `register.py`, `claim.py` and `census-sessions.py` run as
subprocesses, so their data lands in separate files that only combine merges.
See `docs/PUBLISHING.md` for the pre-publish public-repo scrub.

## What belongs in a contribution

- The README is for someone deciding whether to attach noni to their project.
  The product document, `docs/PRODUCT.md`, is the deep reference and stays that
  way: put depth there, not here.
- Every invariant a document claims needs a script with an honest exit code or a
  census check behind it. Prose alone is convention, not enforcement.
- The README's try-it block runs in a test (`tests/test_readme.py`). A command
  that does not name a script in this repository, or that stops producing the
  documented outcome, fails that test.
- `docs/PRODUCT.md` sections 3, 6 and 7 are binding for all epics.

## Purity

The repository holds only generic product direction: positioning, research,
design, specs, and the skills we ship. It holds no project-specific content: no
tickets, no backlog entries, no references to any attached project's content.
Core skills carry neither project content nor vocabulary from any specific
driver, tracker or project; adapters live under `integrations/`, one clearly
marked directory per project, and the core must stay viable with none installed.
`tests/test_purity.py` enforces both tiers.
