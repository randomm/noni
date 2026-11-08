"""The writer's path token is the caller-cwd form, committed or not (issue #77, AC2).

A private state repository is named on the command line by name alone: a reader on
Route B types ``--repo .noni-state`` from the project directory. The pilot read that
route's ``--no-commit`` output as a stray ``noni/`` having appeared beside the
project, because the uncommitted line and the committed line named the same file in
two shapes -- one carrying the ``--repo`` component, one not.

``tests/test_session_relative_repo.py`` pins the *git* half of that route (which
pathspec reaches the commit); this file pins the *wording* half. For each of the six
writers, a run with a relative ``--repo`` names the file by the same token on the
committed line and on the ``left uncommitted`` line: ``--repo`` joined to the path
under the state root, which is the string that actually locates the file from the
directory the command ran in. Exit codes and the refusal wording of a commit git
declined are the other suite's business; nothing here re-asserts them.

Each pair runs against its own fixture tree, because the writers are not idempotent
across the pair: a close that landed leaves nothing for the next close to name, and
release removes the row the second run would ask for.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _harness import (
    CLAIM,
    CLOSE,
    DECIDE,
    INTENT,
    ORDER,
    REGISTER,
    RELEASE,
    _git_ok,
    run_from,
)
from order_fixtures import BASELINE_ID, NOW
from session_git_support import STATE_DIR, _nested_state

SID = "2026-10-01-cccccc"
TASK = "#1"

# Each writer's success line, spelled the way the writer spells it. ``_UNCOMMITTED``
# is the shared tail of every writer's --no-commit line.
_UNCOMMITTED = "left uncommitted"

# The paths a Route B caller must see named: --repo joined to the path under the
# state root. The state-root-relative spelling alone is what let a reader conclude a
# stray ``noni/`` had appeared beside the project.
SESSION_TOKEN = f"{STATE_DIR}/noni/sessions/{SID}.md"
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
    ``/``, the claim line carries ``;``) would cut the token short, so the caller
    names both bounds and the helper takes what lies between them.
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


# --- the four session writers -------------------------------------------------


def test_register_names_the_same_path_committed_and_uncommitted(tmp_path):
    """``registered session <id> -> <path>`` and ``<path> left uncommitted`` agree.

    register allocates a fresh id per run, so the two runs name two different files;
    what must agree is the form, and that neither one ever drops the ``--repo``
    component the bug dropped on one of the two routes.
    """
    project, _state, _session = _nested_state(tmp_path, SID, name="register")
    committed = _run_ok(project, REGISTER, "--repo", STATE_DIR, "--identity",
                        "developer")
    uncommitted = _run_ok(project, REGISTER, "--repo", STATE_DIR, "--identity",
                          "reviewer", "--no-commit")

    committed_path = _between(committed.stdout, "->")
    uncommitted_path = _between(_one_line(uncommitted.stdout, _UNCOMMITTED), " ",
                                " left uncommitted")
    # The claim stated plainly: both tokens are the state clone's sessions directory
    # as reached from the project cwd, and both are file names inside it. The id
    # differs between the runs (register mints one per run); the form may not.
    for label, token in (("committed", committed_path),
                         ("uncommitted", uncommitted_path)):
        assert token.startswith(f"{STATE_DIR}/noni/sessions/"), (label, token)
        assert token.endswith(".md"), (label, token)
        assert not token.startswith("/"), (label, token)
    assert committed_path.count("/") == uncommitted_path.count("/") == 3, (
        committed_path, uncommitted_path)


def test_close_names_the_same_path_committed_and_uncommitted(tmp_path):
    """``closed session <id> in <path>`` and ``<path> left uncommitted`` agree.

    Two fixture trees, one per route: a close that landed leaves the session closed,
    and the second close would report "already closed" instead of naming a path.
    """
    project_a, _state_a, _session_a = _nested_state(tmp_path, SID, name="close-committed")
    project_b, _state_b, _session_b = _nested_state(tmp_path, SID, name="close-no-commit")

    committed = _run_ok(project_a, CLOSE, "--repo", STATE_DIR, "--session-id", SID)
    uncommitted = _run_ok(project_b, CLOSE, "--repo", STATE_DIR, "--session-id", SID,
                          "--no-commit")
    assert _between(committed.stdout, " in ") == SESSION_TOKEN, committed.stdout
    assert _between(_one_line(uncommitted.stdout, _UNCOMMITTED), " ",
                    " left uncommitted") == SESSION_TOKEN, uncommitted.stdout


def test_release_names_the_same_path_committed_and_uncommitted(tmp_path):
    """``released <task> from <path>`` and ``<path> left uncommitted`` agree."""
    project_a, _state_a, _session_a = _nested_state(tmp_path, SID, name="rel-committed")
    project_b, _state_b, _session_b = _nested_state(tmp_path, SID, name="rel-no-commit")

    committed = _run_ok(project_a, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", TASK)
    uncommitted = _run_ok(project_b, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                          "--task", TASK, "--no-commit")
    assert _between(committed.stdout, " from ") == SESSION_TOKEN, committed.stdout
    assert _between(_one_line(uncommitted.stdout, _UNCOMMITTED), " ",
                    " left uncommitted") == SESSION_TOKEN, uncommitted.stdout


def test_claim_names_the_same_path_committed_and_uncommitted(tmp_path):
    """``committed claim <task> in <path>`` and ``appended ... to <path>`` agree.

    claim.py names its file on both lines; the shape that differs between them (the
    id-without-directory on one, the full path on the other) is exactly what AC2
    forbids, and what the pilot read as a second ``noni/`` tree.
    """
    project_a, _state_a, _session_a = _nested_state(tmp_path, SID, name="claim-committed")
    project_b, _state_b, _session_b = _nested_state(tmp_path, SID, name="claim-no-commit")

    committed = _run_ok(project_a, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#42")
    uncommitted = _run_ok(project_b, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                          "--task", "#7", "--no-commit")
    assert _between(committed.stdout, " in ") == SESSION_TOKEN, committed.stdout
    row = _one_line(uncommitted.stdout, _UNCOMMITTED)
    assert _between(row, " to ", "; left uncommitted") == SESSION_TOKEN, row


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
    # the two routes get their own clone, as the sessions pairs above do.
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
