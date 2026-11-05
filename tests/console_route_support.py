"""Fixtures and the byte-comparison for the route-equivalence tests.

``tests/test_console_routes.py`` asserts that one tool prints the same bytes
however it was reached -- the in-place wrapper under ``skills/<skill>/scripts/``,
the ``noni`` console command, and ``python -m noni``. Its second half lives in
``tests/test_console_equivalence.py``, which covers the command above the tools;
both modules compare runs, both need the same throwaway tree and the same
comparison, and a fixture one of them quietly relaxed would make the other's green
meaningless. So the shared parts live here, in a
module pytest never collects (no ``test_*`` name), and neither test file carries a
private copy of them.

The comparison itself is on bytes and not on "both exited 0", for the reason the
comparison modules state: the census's fix hints, the writers' refusals and
argparse's usage lines all carry the program name, so a label that silently became
``cli.py`` or ``__main__.py`` on one route would keep every behavioural test green
while breaking the documentation the exit codes point at.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _harness import (
    _commit_file,
    _git,
    _git_env_with_identity,
    _init_repo,
    subprocess_env,
)

# One baseline repo per test: a committed decision record the order writer can
# cite, so the tools have real state to act on.
BASELINE_ID = "2026-10-01-baseline"

# A draft the intent writer accepts: the four sections and one stamp line. Written
# here rather than read from the shipped template, because these modules compare two
# routes and must not fail because a document changed its prose.
INTENT_DRAFT = """# Intent
Last-confirmed: 2026-10-01
## Purpose
Ship the beta.
## Principles
Prefer the boring technology.
## Never
Never force push.
## Ask first
Anything that costs money.
"""

# The identity the writers commit under. decide.py takes ``by`` from
# ``git config user.name`` and refuses exit 3 without it, so a launched writer
# needs the deterministic identity the harness uses everywhere else; a test that
# wants the missing-identity refusal passes its own env instead.
IDENTITY_ENV = {**_git_env_with_identity(),
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def identity_env() -> dict:
    """The harness env plus the deterministic git identity the writers commit under."""
    env = subprocess_env()
    env.update(IDENTITY_ENV)
    return env


def baseline_repo(tmp_path: Path) -> Path:
    """A throwaway tree holding one committed decided record the writers can cite."""
    repo = _init_repo(tmp_path / "repo")
    record = {
        "id": BASELINE_ID,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "team-lead",
        "questions": [{"id": "q1", "text": "Ship?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Operator",
        "scope": "release",
        "status": "decided",
        "supersedes": None,
    }
    _commit_file(repo, f"noni/decisions/{BASELINE_ID}.json", json.dumps(record, indent=2) + "\n")
    return repo


def identity_repo(tmp_path: Path) -> Path:
    """The baseline repo with a real git identity in its own config.

    ``decide.py`` takes ``by`` from ``git config user.name`` of the tree and
    refuses exit 3 without it, so a writer run that must reach the commit needs
    the identity in the repo, not only in the child env (the harness pins the
    author/committer vars, which answer the commit but not the attribution).
    """
    repo = baseline_repo(tmp_path)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    return repo


def sid_of_uncommitted(stdout: str) -> str:
    """The session id in a ``--no-commit`` register line.

    The line names the file it left in the work tree
    (``register.py: <path>/<id>.md left uncommitted``); the id is that path's
    stem, which is the session id.
    """
    tail = stdout.strip().split(" -> ")[-1].rsplit(" left uncommitted", 1)[0]
    return tail.rsplit("/", 1)[-1].removesuffix(".md")


def assert_same(left: subprocess.CompletedProcess[str],
                right: subprocess.CompletedProcess[str], label: str) -> None:
    """Both routes: same exit code, same stdout, same stderr, byte for byte.

    A traceback is itself a failure, before the comparison: a crash on both
    routes would compare equal, and the harness frames (``<frozen runpy>``, the
    dispatch module) differ between them for reasons that say nothing about the
    tool. So a crash is named as one rather than reported as a mismatch.

    The two names in the failure text are the generic "left" and "right" rather
    than "wrapper" and "console": the comparison is shared by every pair the two
    route modules build, and a helper that labelled a caller's routes wrongly
    would send a reader to the wrong launcher.
    """
    for name, proc in (("left", left), ("right", right)):
        assert "Traceback (most recent call last)" not in proc.stderr, (
            f"{label}: the {name} route crashed\n{proc.stderr}"
        )
    assert left.returncode == right.returncode, (
        f"{label}: exit codes differ ({left.returncode} vs {right.returncode})\n"
        f"left stdout: {left.stdout!r}\nright stdout: {right.stdout!r}\n"
        f"left stderr: {left.stderr!r}\nright stderr: {right.stderr!r}"
    )
    assert left.stdout == right.stdout, f"{label}: stdout differs\n{left.stdout!r}\n{right.stdout!r}"
    assert left.stderr == right.stderr, f"{label}: stderr differs\n{left.stderr!r}\n{right.stderr!r}"
