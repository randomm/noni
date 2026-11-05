"""Shared builders for the ``intent`` feature's tests: the file, the record, the runs.

The artifact (``noni/direction/intent.md``), one committed decision record for its
citation to name, and the runners that drive the census for it. Held in a
non-test module so the intent test files share one set of builders and pytest
never collects them as tests. Mirrors ``tests/ordering_fixtures.py``, whose shape
this group follows.

The shape tables are deliberately not here: ``tests/intent_shapes.py`` is read by
the writer's suite too, so it stays where both sides can see it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import REPO, _git, _init_repo, git_pin_date, subprocess_env

from noni.intentschema import LAST_CONFIRMED_PREFIX

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

INTENT_REL = "noni/direction/intent.md"

RECORD_ID = "2026-10-01-alpha"

NOW = "2026-10-27T12:00:00Z"

# The UTC day ``NOW`` falls on: what the writer stamps when a run is driven with
# ``--now NOW``, and therefore what a fixture must carry for a re-run of the
# writer to be a no-op. Derived from NOW rather than written beside it, so the
# two cannot drift apart.
STAMP_DAY = NOW[:10]

# The four sections, each once, in order, after one stamp line: the draft both
# suites start from. Deliberately unstamped: whoever installs it decides who
# stamps it (see ``install_intent`` and ``write_intent``).
GOOD_INTENT = """# Intent
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


def record(*, decision: str = RECORD_ID, status: str = "decided",
           supersedes: str | None = None) -> dict:
    """One ledger record body, cited by name in the tests."""
    return {
        "id": decision, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Direction?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "standing intent", "status": status,
        "supersedes": supersedes,
    }


def repo_with_record(tmp_path: Path, subdir: str = "repo", *,
                     records: tuple[dict, ...] | None = None,
                     raw: dict[str, str] | None = None) -> Path:
    """A throwaway tree holding a committed ledger record (or several).

    ``records`` are ``record()`` bodies committed under their own ids; ``raw``
    commits bodies at the given relative paths verbatim, which is how a test
    states a record the ledger cannot read.
    """
    repo = _init_repo(tmp_path / subdir)
    for body in records if records is not None else (record(),):
        _commit(repo, f"noni/decisions/{body['id']}.json",
                json.dumps(body, indent=2) + "\n")
    for rel, body in (raw or {}).items():
        _commit(repo, rel, body)
    return repo


def planted_ledger_link(tmp_path: Path, name: str, *, parent: bool = False) -> Path:
    """A committed repo whose ledger directory (or ``noni/``) is a link outside it.

    One committed record, an intent citing it, then the directory the record lives
    in replaced by a symlink to an outside directory holding a superseded body for
    the same id — the state in which a leaf classification calls the record an
    ordinary file and the read follows the parent link. ``parent`` links ``noni/``
    itself instead of ``noni/decisions``. Returns the repo.
    """
    repo = repo_with_record(tmp_path, name)
    install_intent(repo)
    commit_intent(repo)
    # The body the link leads to, planted outside the audited tree but inside the
    # fixture root: outside the repo is the state under test, and a name carrying the
    # cited id is what a leaf classification would accept as the record.
    inner = repo.parent / name / "ledger-lives-here"
    inner.mkdir(parents=True)
    (inner / f"{RECORD_ID}.json").write_text(
        json.dumps(record(status="superseded", supersedes=RECORD_ID)),
        encoding="utf-8")
    target = repo / "noni" if parent else repo / "noni" / "decisions"
    if parent:
        # ``noni/`` holds the intent too, so the link leads to a copy of both
        # directories: the run must still be owed the read of the intent, and still
        # refuse the record that stands behind the link.
        shutil.copytree(repo / "noni" / "direction", inner / "direction")
    shutil.rmtree(target)
    target.symlink_to(inner)
    return repo


def _commit(repo: Path, rel: str, body: str, date: str = NOW) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", f"direction: {rel}")


def restamp(text: str, day: str) -> str:
    """``text`` with its stamp line replaced by ``day``, the writer's own rule."""
    line = f"{LAST_CONFIRMED_PREFIX} {day}"
    return "\n".join(line if raw.startswith(LAST_CONFIRMED_PREFIX) else raw
                      for raw in text.split("\n"))


def install_intent(repo: Path, text: str = GOOD_INTENT,
                   day: str = STAMP_DAY) -> Path:
    """The file ``intent.py`` would have written, on disk and uncommitted.

    The stamp is restamped to ``day`` the way the writer restamps it, so a
    fixture that means "the writer installed this" produces the bytes the writer
    produces, and a test that compares a re-run against it compares two runs
    rather than a run against a hand-written draft.
    """
    return _put(repo, restamp(text, day))


def write_intent(repo: Path, text: str = GOOD_INTENT) -> Path:
    """The ``text`` given, verbatim, in the working tree and uncommitted.

    For the tests that state a shape the writer would refuse: a fixture that ran
    the bytes through the writer's own restamp would quietly repair the draft it
    is meant to install unchanged.
    """
    return _put(repo, text)


def _put(repo: Path, body: str) -> Path:
    target = repo / INTENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def commit_intent(repo: Path, *, decision: str = RECORD_ID,
                  subject: str | None = None, date: str = NOW) -> None:
    """Commit the working-tree intent with the writer's subject shape.

    ``subject`` overrides the headline for a test that wants a commit which does
    not cite, or cites something the ledger does not hold: history records what
    happened, and these tests state history rather than repair it.
    """
    _git(repo, "add", INTENT_REL)
    git_pin_date(repo, date, "commit", "-q", "-m",
                 subject if subject is not None else f"intent: {decision}")


def planted_record_link(tmp_path: Path, name: str, *,
                       target: Path | None = None, is_dir: bool = False,
                       hardlink_to: Path | None = None,
                       dangling: bool = False) -> Path:
    """A committed repo whose cited record stands as a planted path, ready for a run.

    The one state every cited-record test needs: a record committed at its id, an
    intent committed against it, and then the path replaced by something that is not
    an ordinary file.

    - ``target`` -- a symlink to it, so the census must refuse to follow it.
    - ``dangling`` -- a symlink to nothing, which is not an absent record.
    - ``is_dir`` -- a directory at the path (a device or fifo is the same answer).
    - ``hardlink_to`` -- a hardlink, a state ``lstat`` cannot tell from an ordinary
      file, kept so the limit is asserted and not assumed.
    - none of them -- the record left exactly as committed, for a test that plants
      the state itself (a swap that happens after the classification).

    Returns the repo. The subdir is named per caller so two states can stand in one
    ``tmp_path`` without colliding.
    """
    repo = repo_with_record(tmp_path, name)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    if is_dir:
        record_path.unlink()
        record_path.mkdir()
    elif hardlink_to is not None:
        record_path.unlink()
        os.link(hardlink_to, record_path)
    elif target is not None:
        record_path.unlink()
        record_path.symlink_to(target)
    elif dangling:
        record_path.unlink()
        record_path.symlink_to(tmp_path / "no-such-record.json")
    return repo


def _run(repo: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the intent class only, as NDJSON plus raw streams."""
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--json", "--now", NOW,
            "--only", "intent", *extra]
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, [r for r in rows if r.get("kind") == "finding"], \
        proc.stdout, proc.stderr


def _human(repo: Path, *extra: str) -> tuple[int, str, str]:
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--now", NOW,
            "--only", "intent", *extra]
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def _rows(repo: Path, *extra: str) -> list[dict]:
    """The findings of a run whose ``--only``/``--skip`` flags the caller owns.

    ``_run`` pins the run to the intent class, which is what the row-shape tests
    want and what a filter test cannot use: the question there is what a run sees
    when its filter named some class that is not this one. This launcher adds the
    caller's flags verbatim and drops the default ``--only``, exactly as
    ``ordering_fixtures._only_args`` does for the ordering group, so a caller that
    named no filter gets the whole census.
    """
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--json", "--now", NOW,
            *extra]
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == "finding"]


def subjects(rows: list[dict]) -> list[str]:
    """The subjects this run reported, in row order."""
    return [row["subject"] for row in rows]


def _intent_rows(rows: list[dict]) -> list[dict]:
    """The intent class's own rows of a run that reported other classes too.

    The ledger group always reports its own row beside a planted link, and that row
    is correct existing behaviour: the assertion under test is this class's alone.
    """
    return [row for row in rows if row["check"] == "intent"]


def _json_rows(stdout: str) -> list[dict]:
    """The finding rows an in-process run printed, as dicts.

    ``findings_of`` answers for one class and keeps only three fields; the tests
    that inspect a row's text or its visibility marker need the whole row.
    """
    return [row for row in (json.loads(line) for line in stdout.splitlines()
                            if line.strip())
            if row.get("kind") == "finding"]


def intent_kind_answers(verdict: str, problem: str | None = None, *,
                        answers: dict[Path, tuple[str, str | None]] | None = None):
    """A ``_file_kind`` replacement that answers ``(verdict, problem)`` for the
    intent path, ``(kind, problem)`` for any path named in ``answers``, and
    classifies every other path for real.

    Two tests need the census to meet a path it cannot describe: a parent whose
    ``lstat`` was declined, and a chain of links that loops. Neither is portable as
    a fixture -- an unreadable directory is simply readable when the suite runs as
    root, and whether a loop reaches the run through the classifier or the reader
    depends on how the link was written -- so the state the tests mean to ask about
    is installed at the census's own classifier instead. The gate and the class both
    reach that one seam, so what is under test is the run's answer to a faulting
    path and not the filesystem's cooperation.

    ``kind`` positional, like every caller: ``census._ledger_probe`` hands the
    classifier to ``probe_ledger``, which calls it as ``file_kind(ledger,
    kind="dir")``, so a keyword-only signature is not the seam the run uses.
    """
    import noni.census as census

    real = census._file_kind

    def answer(path, kind="file"):
        if Path(path).name == "intent.md":
            return verdict, problem
        if answers and Path(path) in answers:
            # A path the test wants classified as something the tree does not
            # hold, asked through the classifier a direct caller uses when the
            # run hands it no probe at all.
            return answers[Path(path)]
        return real(path, kind)

    return answer


def run_census_in_process(repo: Path, *args: str) -> tuple[int, str, str]:
    """``census.main`` in this interpreter, so a seam the test patched is the seam
    the run uses.

    ``_run`` and ``_rows`` launch a subprocess, which is what a row-shape test wants
    and what a patched-seam test cannot use. This launcher exists for the seams.
    """
    import importlib
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = importlib.import_module("census").main(
            ["--repo", str(repo), "--json", "--now", NOW, *args])
    return rc, out.getvalue(), err.getvalue()


def findings_of(stdout: str, check: str) -> list[tuple[str, str, str]]:
    """The ``(check, subject, severity)`` of every ``check`` row a JSON run printed."""
    return [(row["check"], row["subject"], row["severity"])
            for row in (json.loads(line) for line in stdout.splitlines() if line.strip())
            if row.get("kind") == "finding" and row["check"] == check]


def probe_state_answers(state: str, *, fault: bool = False):
    """A ``census._ledger_probe`` replacement that answers one ``state`` for any ledger.

    ``probe_ledger`` is the run's own answer for the two levels above a cited
    record: it classifies the ledger and ``noni/`` and reports ``"symlink"`` for a
    link at either. A test that means "the run was told the ledger is a link" (or
    was told a word the ledger module has not invented yet) puts one of these on
    that seam, so the state under test is the probe's word and not a symlink the
    host filesystem happens to allow, and the intent group's refusal is exercised
    through the seam ``census_run._check_intent`` actually uses.

    ``fault`` gives the probe the ``problem`` half an ``OSError`` forced, which is
    the text a row must never quote. ``listing_fault`` stays None unless a caller
    says otherwise: the finding under test is the intent class's row, not a second
    group's blindness.
    """
    def answer(_ledger):
        return _ProbeAnswer(state, fault)

    return answer


class _ProbeAnswer:
    """The fields of a ``LedgerProbe`` the census reads off the probe."""

    def __init__(self, state: str, fault: bool = False) -> None:
        self.state = state
        # Text of the kind a stat fault produces: a path and a long tail, which no
        # row may carry. Deliberately machine-local in shape.
        self.problem = "/home/operator/secret-dir" + "x" * 400 if fault else None
        self.listing_fault = None
        self.names = None


class BlindListing:
    """A ``names`` argument that makes a group list the ledger itself.

    The census hands every ledger-reading group the run's one listing, so a test
    that wants to watch a group read the directory (and judge what it makes of a
    record it finds there) has to take that listing away. Replacing the run's
    probe with this leaves ``names`` as None, which is the state in which the
    group does its own readdir: the fault and the answer are then the group's,
    and the row under test is the one this run produced rather than one the
    ledger group happened to report.
    """

    state = "ok"
    listing_fault = None
    names = None
