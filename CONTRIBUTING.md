# Contributing to noni

noni is a Python 3.11 project with two gates: `ruff` for linting and `pytest`
under `coverage` for tests. Both run locally and in CI on the same pinned tool
versions.

The shipped code is the `noni` package under `src/noni/`. The entry points under
`skills/<skill>/scripts/` and `scripts/public_safety.py` are thin wrappers that
import it, so the package must be installed (or on `PYTHONPATH`) before the
suite or a wrapper will run; the editable install below does that.

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

The coverage command measures the Python product modules listed in
`[tool.coverage.report] include` in `pyproject.toml`, and enforces the
at-least-80% rule from `AGENTS.md`. `coverage combine` is required, not
optional: some product modules are reached only as subprocesses (see the
`[tool.coverage.run]` comment in `pyproject.toml`), so their data lands in
separate files that only combine merges.

## Packaging

One distribution, one command. `[project.scripts]` declares
`noni = "noni.cli:main"`, and `src/` is the only directory setuptools looks in,
so the wheel ships `noni/` and its metadata and nothing else. Three tests hold
that, and CI runs all three against the built wheel in a fresh venv:

- `tests/test_wheel_contents.py` — the wheel's entry list is a whitelist: no
  `tests/`, `skills/`, `integrations/`, `docs/`, `.github/` or this repository's
  own `noni/` state, and every package module is present.
- `tests/test_console_equivalence.py` — each tool prints the same bytes through
  its wrapper and through the console command, including `--help`, where a
  program-name label would drift first.
- `tests/test_gate_wiring.py` — the CI pins match `pyproject.toml`, the coverage
  `include` list matches `PRODUCT_MODULES` in `tests/_harness.py`, and the wheel
  job calls the installed `noni` script rather than only `python -m noni.cli`.

The program names the tools print come from `src/noni/labels.py`, not from
`__file__`, which is what lets the two routes agree. A new tool needs an entry
there, a subcommand in `src/noni/cli.py`, a wrapper under its skill, and an entry
in both `PRODUCT_MODULES` and the coverage `include` list; the gate tests fail
loudly when any of the four is missing.

## What belongs in a contribution

- The README is for someone deciding whether to attach noni to their project.
  The product document, `docs/PRODUCT.md`, is the deep reference and stays that
  way: put depth there, not here.
- Every invariant a document claims needs a script with an honest exit code or a
  census check behind it. Prose alone is convention, not enforcement.
- The README's try-it block runs in a test (`tests/test_readme.py`) against a
  materialised clone of this repository and a separate scratch repository, so a
  command that does not name a script the clone carries, or that stops producing
  the documented outcome on the clone path a reader actually takes, fails that
  test.
- The try-it block in the README replays one scenario repo in one run. Keep it
  that way: extra scenarios under coverage measurement multiply the cost of the
  two launches rather than the work they test.
- `docs/PRODUCT.md` sections 3, 6 and 7 are binding for all epics.

## Purity

The repository holds only generic product direction: positioning, research,
design, specs, and the skills we ship. It holds no project-specific content: no
tickets, no backlog entries, no references to any attached project's content.
Core skills carry neither project content nor vocabulary from any specific
driver, tracker or project; adapters live under `integrations/`, one clearly
marked directory per project, and the core must stay viable with none installed.
`tests/test_purity.py` enforces both tiers. The committed check covers
machine-local paths and secret shapes; operator names, external project or tool
names and hostnames are covered only by the untracked deny-list, so a green run
without it is not a scrub-clean guarantee. See
[docs/PUBLISHING.md](docs/PUBLISHING.md) for the pre-publish public-repo scrub.
