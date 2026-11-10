"""The writer's path token is the caller-cwd form, committed or not (issue #77, AC2).

A private state repository is named on the command line by name alone: a reader on
Route B types ``--repo .noni-state`` from the project directory. The pilot read that
route's ``--no-commit`` output as a stray ``noni/`` having appeared beside the
project, because the uncommitted line and the committed line named the same file in
two shapes -- one carrying the ``--repo`` component, one not.

This file pins the *wording* half of that route. For each of the three writers that
survive -- ``order``, ``intent`` and ``decide`` -- a run with a relative ``--repo``
names the file by the same token on the committed line and on the ``left uncommitted``
line: ``--repo`` joined to the path under the state root, which is the string that
actually locates the file from the directory the command ran in. Exit codes and the
refusal wording of a commit git declined are the state-root suite's business; nothing
here re-asserts them.

Each pair runs against its own fixture tree, because the writers are not idempotent
across the pair: a write that landed leaves nothing for the next run to name, so the
committed and ``--no-commit`` routes each get a fresh clone.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _harness import DECIDE, INTENT, ORDER, _git_ok, run_from
from order_fixtures import BASELINE_ID, NOW

# Each writer's success line, spelled the way the writer spells it. ``_UNCOMMITTED``
# is the shared tail of every writer's --no-commit line.
_UNCOMMITTED = "left uncommitted"

# The paths a Route B caller must see named: --repo joined to the path under the
# state root. The state-root-relative spelling alone is what let a reader conclude a
# stray ``noni/`` had appeared beside the project.
STATE_DIR = ".noni-state"
ORDER_TOKEN = f"{STATE_DIR}/noni/direction/order.json"
INTENT_TOKEN = f"{STATE_DIR}/noni/direction/intent.md"

_DECIDE = ["--slug", "help-usage", "--scope", "cli", "--asked-by", "developer",
           "--question", "q1=Which form?", "--option", "q1=repo joined",
           "--option", "q1=state relative", "--answer", "q1=repo joined"]
# The same argument list with a different slug: the pair of runs one test needs when
# the writer refuses to write the same record id twice.
_DECIDE_SECOND = ["--slug", "corrected", "--scope", "cli", "--asked-by", "developer",
                  "--question", "q1=Which form?", "--option", "q1=repo joined",
                  "--option", "q1=state relative", "--answer", "q1=repo joined"]


def _one_line(stdout: str, label: str) -> str:
    """The single output line that carries ``label``, or the failure that says so.

    Exactly one match is a precondition of every comparison below: two lines would
    make it ambiguous which one agreed, and none would make it vacuous.
    """
    matching = [row for row in stdout.splitlines() if label in row]
    assert len(matching) == 1, f"expected one {label!r} line, got {matching}"
    return matching[0]


def _between(text: str, start: str, end: str | None = None) -> str:
    """The token ``text`` carries between two of its own literals.

    Splitting on a separator the surrounding prose also contains (a path carries
    ``/``) would cut the token short, so the caller names both bounds and the helper
    takes what lies between them.
    """
    assert start in text, f"{start!r} not in {text!r}"
    tail = text.split(start, 1)[1]
    if end is not None:
        tail = tail.split(end, 1)[0]
    return tail.strip()


def _run_ok(cwd: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer whose exit code has to be 0, with its output in the message.

    ``--repo`` is passed exactly as a Route B reader types it -- a bare directory
    name -- so this is the pair the ticket names: same command, same relative
    ``--repo``, the flag flipped and the path text required to stay put.
    """
    proc = run_from(cwd, script, *args)
    assert proc.returncode == 0, f"{script.name} {args}: {proc.returncode} " \
        f"\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    return proc


def _decide_date(project: Path) -> str:
    """The UTC day decide.py stamps its record's id with, for this run.

    The id is ``<date>-<slug>`` and the date is the run's UTC day unless ``--date``
    names one, so a test that asserts the printed file name reads the clock through
    the writer's own rule rather than pinning a date the fixture assumed.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _with_date(argv: list[str], day: str) -> list[str]:
    """``argv`` with ``--date`` inserted where the writer wants it.

    A supersede names its own day, so the two runs of a supersede pair are given
    the same ``--date`` here to make the second one's id land on the first one's
    filename; the flag has to sit beside the other option flags rather than after
    the repeatables.
    """
    argv = list(argv)
    at = argv.index("--question")
    return argv[:at] + ["--date", day] + argv[at:]


# --- the two direction writers and the ledger writer --------------------------


def test_order_names_the_same_path_committed_and_uncommitted(tmp_path):
    """``committed <path>`` and ``wrote <path>; left uncommitted`` name one path.

    This is the pilot's misreading directly: the uncommitted line used to print only
    the state-root-relative artifact name, so on Route B it looked like a path under
    the project rather than under the state clone.
    """
    project, state = _direction_trees(tmp_path, "order")
    committed = _run_ok(project, ORDER, "--repo", STATE_DIR, "add", "7",
                        "--decision", BASELINE_ID, "--now", NOW)
    uncommitted = _run_ok(project, ORDER, "--repo", STATE_DIR, "add", "8",
                          "--decision", BASELINE_ID, "--now", NOW, "--no-commit")

    assert _between(committed.stdout, "committed ", " (") == ORDER_TOKEN, \
        committed.stdout
    assert _between(_one_line(uncommitted.stdout, _UNCOMMITTED), "wrote ",
                    "; left uncommitted") == ORDER_TOKEN, uncommitted.stdout


def test_intent_names_the_same_path_committed_and_uncommitted(tmp_path):
    """The intent writer's ``committed`` and ``wrote`` lines name one path."""
    project, state = _direction_trees(tmp_path, "intent")
    draft = tmp_path / "intent-draft.md"
    draft.write_text(_intent_draft(), encoding="utf-8")
    argv = ["--repo", STATE_DIR, "set", "--from", str(draft), "--decision",
            BASELINE_ID, "--now", NOW]

    project_b, _state_b = _direction_trees(tmp_path, "intent-nc")
    committed = _run_ok(project, INTENT, *argv)
    # The committed route lands the file, so a --no-commit run over the same clone
    # would find identical bytes and answer "unchanged" instead of naming a path:
    # the two routes get their own clone, as the pairs below do.
    uncommitted = _run_ok(project_b, INTENT, *argv, "--no-commit")
    assert _between(committed.stdout, "committed ", " (decision") == INTENT_TOKEN, \
        committed.stdout
    assert _between(_one_line(uncommitted.stdout, _UNCOMMITTED), "wrote ",
                    "; left uncommitted") == INTENT_TOKEN, uncommitted.stdout


def test_decide_names_the_same_path_committed_and_uncommitted(tmp_path):
    """The record path ``wrote`` prints is the same token on both routes.

    ``--no-commit`` once printed the state-root-relative rel while the committed
    route printed an absolute machine path: two forms inside one writer.
    """
    project_a, state_a = _direction_trees(tmp_path, "decide-committed")
    project_b, state_b = _direction_trees(tmp_path, "decide-no-commit")
    day = _decide_date(project_a)
    record_rel = f"noni/decisions/{day}-help-usage.json"

    committed = _run_ok(project_a, DECIDE, "--repo", STATE_DIR, *_DECIDE)
    uncommitted = _run_ok(project_b, DECIDE, "--repo", STATE_DIR, *_DECIDE,
                          "--no-commit")
    assert _between(committed.stdout, "wrote ") == f"{STATE_DIR}/{record_rel}", \
        committed.stdout
    assert _between(_one_line(uncommitted.stdout, _UNCOMMITTED), "wrote ",
                    "; left uncommitted") == f"{STATE_DIR}/{record_rel}", \
        uncommitted.stdout


def test_decide_supersede_names_both_paths_on_both_routes(tmp_path):
    """A supersede names the new record and the target, in one form, on both routes.

    AC2 says every writer, one form; the supersede is the single line that carries
    two paths, so it is where a per-route formatting difference would hide.
    """
    project, state = _direction_trees(tmp_path, "decide-supersede")
    day = _decide_date(project)
    first = _run_ok(project, DECIDE, "--repo", STATE_DIR, *_DECIDE)
    assert _between(first.stdout, "wrote ").endswith(f"{day}-help-usage.json")

    superseded = _run_ok(project, DECIDE, "--repo", STATE_DIR,
                         *_with_date(_DECIDE_SECOND, day),
                         "--supersedes", f"{day}-help-usage")
    # The second supersede's slug, with every other flag of the pair kept: the
    # writer takes the id from --date/--slug, so the slug is the one argument this
    # line may change.
    second = ["--slug", "corrected-nc", *_with_date(_DECIDE_SECOND, day)[2:]]
    uncommitted = _run_ok(project, DECIDE, "--repo", STATE_DIR, *second,
                          "--supersedes", f"{day}-corrected", "--no-commit")

    committed_paths = _between(superseded.stdout, "wrote ")
    for wanted in (f"{STATE_DIR}/noni/decisions/{day}-corrected.json",
                   f"{STATE_DIR}/noni/decisions/{day}-help-usage.json"):
        assert wanted in committed_paths, superseded.stdout
    named = _between(_one_line(uncommitted.stdout, _UNCOMMITTED), "wrote ",
                     "; left uncommitted")
    for wanted in (f"{STATE_DIR}/noni/decisions/{day}-corrected-nc.json",
                   f"{STATE_DIR}/noni/decisions/{day}-corrected.json"):
        assert wanted in named, uncommitted.stdout


# --- fixtures -----------------------------------------------------------------


def _direction_trees(tmp_path, name: str) -> tuple[Path, Path]:
    """A project cwd and a nested state clone holding one committed record.

    Both direction writers refuse a ``--decision`` no record carries and decide.py
    takes ``by`` from the tree's own ``user.name``, so the clone needs a committed
    record and an identity before any of the three can run. The clone is ignored by
    the project, which is the layout docs/QUICKSTART.md Route B tells a reader to
    build; ``name`` keeps one test's trees from colliding with another's.
    """
    project = tmp_path / f"project-{name}"
    state = project / STATE_DIR
    project.mkdir(parents=True, exist_ok=True)
    _git_ok(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _git_ok(project, "add", "README.md")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    (project / ".gitignore").write_text(f"{STATE_DIR}/\n", encoding="utf-8")
    _git_ok(project, "add", ".gitignore")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "ignore the state clone")

    state.mkdir(parents=True, exist_ok=True)
    _git_ok(state, "init", "-q", "-b", "main")
    _git_ok(state, "config", "user.name", "Replay")
    _git_ok(state, "config", "user.email", "replay@fixture.invalid")
    record = state / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({
        "id": BASELINE_ID, "date": f"{BASELINE_ID[:10]}T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Which order?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "ordering", "status": "decided", "supersedes": None,
    }, indent=2) + "\n", encoding="utf-8")
    _git_ok(state, "add", f"noni/decisions/{BASELINE_ID}.json")
    _git_ok(state, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"steering: {BASELINE_ID}")
    return project, state


def _intent_draft() -> str:
    """A draft the intent writer's own shape check accepts.

    The four level-2 headings in their required order plus one Last-confirmed line:
    the contract ``skills/direction/references/intent-template.md`` states.
    """
    return ("## Purpose\n\nShip the queue.\n\n"
            "## Principles\n\nOne writer per file.\n\n"
            "## Never\n\nNever answer for the operator.\n\n"
            "## Ask first\n\nAnything that spends money.\n\n"
            "Last-confirmed: 2026-01-01\n")
