"""The fixtures the direction-writer symlink suite plants and asserts.

Held out of ``tests/test_direction_symlink_refusal.py`` by the file-size limit, and
named as a helper module (never ``test_*``) so pytest does not collect the builders
as tests. The suite is the contract for issue #104 -- the three direction writers
refusing a symlinked ``noni/`` and a symlinked output directory -- and everything
about the state it plants lives here: the Route B pair of trees, the writer table
that drives both the sweep and the controls, the link planter, and the post-
conditions one refusal is owed.

Splitting the suite in two is a size decision, not a contract decision: the
assertions stay in the test file beside the shapes they refuse, and what moved here
is the fixture that builds a tree and the shared "a refused run did not write"
predicate those assertions read. Nothing was weakened to make the split -- the
writer table, the codes and the guarded-directory pin are read from these objects
by the tests, so a fixture that drifted fails them rather than passing quietly.
"""


from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import (
    DECIDE,
    INTENT,
    ORDER,
    _git,
    _git_ok,
    git_pin_date,
    subprocess_env,
)

# The state layout: a project repository, and the separate state repository docs/
# PRODUCT.md 7 calls Route B nested inside it and named in its .gitignore. The run
# is launched from the project with a RELATIVE --repo, as a reader types it.
STATE_DIR = "st"

RECORD_ID = "2026-10-01-baseline"
NOW = "2026-10-11T00:00:00Z"

# The record a first run mints, for the first-run control below: decide's slug plus
# the --now that names it. Deliberately NOT a name the sweep plants.
PROBE_SLUG = "first-run"
PROBE_ID = f"{NOW[:10]}-{PROBE_SLUG}"

# The four level-2 sections in order, after the stamp line: the smallest draft
# ``intent.py`` accepts.
GOOD_INTENT = ("# Intent\nLast-confirmed: 2026-10-01\n## Purpose\nShip the beta.\n"
               "## Principles\nPrefer the boring technology.\n## Never\nNever force "
               "push.\n## Ask first\nAnything that costs money.\n")

# Each writer, the wrapper the skill documents, the code docs/PRODUCT.md 7 owes it
# for a wrong path, and the argv beyond --repo. One table drives both the sweep and
# the controls, so "all three refuse the same shapes on their own codes" is one
# assertion over three rows rather than three tests that could each drift. The
# --no-commit form is deliberate: the committed route is the one that used to leak
# bytes outside the tree and then fail at `git add` with git's own words.
WRITERS = (
    ("order", ORDER, 2, ("add", "7", "--decision", RECORD_ID, "--now", NOW,
                         "--no-commit")),
    ("intent", INTENT, 2, ("set", "--from", "{draft}", "--decision", RECORD_ID,
                           "--now", NOW, "--no-commit")),
    ("decide", DECIDE, 3, ("--slug", "sweep-probe", "--date", NOW[:10],
                           "--scope", "release ordering",
                           "--asked-by", "developer", "--question", "q1=Which order?",
                           "--option", "q1=as listed", "--option", "q1=by risk",
                           "--answer", "q1=as listed", "--no-commit")),
)

# The file each writer would have created, so "nothing was written" names a file
# rather than asking the reader to eyeball a directory listing. The decide entry is
# the record its own ``--slug``/``--now`` produce, so the sweep plants no name that
# the fixture's committed content could be mistaken for.
CREATES = {"order": "order.json", "intent": "intent.md",
           "decide": "2026-10-11-sweep-probe.json"}

# The two positions planted as links below ``noni``: the order/intent artifact
# directory, and the ledger. A link at ``noni`` itself -- the third position, and the
# one a leaf-only check cannot see because ``lstat`` resolves every intermediate
# component -- gets its own test.
OUTPUT_POSITIONS = {"order": "noni/direction", "intent": "noni/direction",
                    "decide": "noni/decisions"}




def _record_body(record_id: str = RECORD_ID) -> str:
    """One decided record body: the citation ``add --decision`` and ``set`` accept."""
    return json.dumps({
        "id": record_id, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Which order?",
                       "options": ["as listed", "by risk"], "answer": "as listed"}],
        "by": "Replay", "scope": "release ordering", "status": "decided",
        "supersedes": None,
    }, indent=2) + "\n"


def _decoy(name: str) -> str:
    """A body the outside directory holds before the run, which no writer produces."""
    return f"decoy-{name}\n"


def _commit_state(state: Path, rel: str, body: str) -> None:
    """Commit one file into the state clone under the harness identity."""
    target = state / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(state, "add", rel)
    git_pin_date(state, NOW, "commit", "-q", "-m", f"fixture: {rel}")


def _direction_state(tmp_path: Path, name: str, *, with_noni: bool = True,
                     committed_intent: bool = True) -> tuple[Path, Path, Path]:
    """The Route B pair: (project, state root, draft file).

    The state clone carries the committed record the two writers cite and the
    committed intent the census's ``intent`` class reads. ``with_noni=False`` builds
    the first-run tree instead -- one committed README and no ``noni/`` at all, the
    state every writer must still accept.
    """
    project = tmp_path / name
    project.mkdir(parents=True)
    _git_ok(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _git_ok(project, "add", "README.md")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    (project / ".gitignore").write_text(f"{STATE_DIR}/\n", encoding="utf-8")
    _git_ok(project, "add", ".gitignore")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "ignore the state clone")

    state = project / STATE_DIR
    state.mkdir()
    _git_ok(state, "init", "-q", "-b", "main")
    _git_ok(state, "config", "user.name", "Replay")
    _git_ok(state, "config", "user.email", "replay@fixture.invalid")
    if with_noni:
        _commit_state(state, f"noni/decisions/{RECORD_ID}.json", _record_body())
        if committed_intent:
            _commit_state(state, "noni/direction/intent.md", GOOD_INTENT)
    else:
        _commit_state(state, "README.md", "state root\n")
    draft = tmp_path / f"{name}-draft.md"
    draft.write_text(GOOD_INTENT, encoding="utf-8")
    return project, state, draft


def _plant_link(state: Path, outside: Path, rel: str) -> Path:
    """Move ``state/rel`` outside the clone and leave a link where it was.

    Returns the planted link. When the position already holds committed content it is
    MOVED out rather than copied, so the outside directory carries the fixture's own
    bytes -- the record, in the ledger's case -- that a writer following the link
    would have read, and the byte comparison after the run is what says nobody did.
    The name under ``outside`` is ``rel``'s LAST component (``outside/decisions``
    for ``noni/decisions``): the link target is the directory the writer believes it
    is writing into, so the outside tree must be shaped like the position, and a
    fixture that flattened the ``noni`` level away would have made the outside
    directory look like a ``noni/`` and turned its own committed ``direction/intent.md
    `` into a false "the run wrote outside" failure.

    An absent position simply gets a link to an empty outside directory, which is the
    state a first run would have created.
    """
    target = state / rel
    inner = outside / Path(rel).name
    inner.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.move(str(target), str(inner))
    else:
        inner.mkdir()
    target.symlink_to(inner)
    return target


def _launch(project: Path, script: Path, argv: tuple[str, ...],
            draft: Path) -> subprocess.CompletedProcess[str]:
    """One writer launched from the project cwd, with --repo naming the state clone."""
    filled = tuple(part.replace("{draft}", str(draft)) for part in argv)
    return subprocess.run(
        [sys.executable, str(script), "--repo", STATE_DIR, *filled],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(project),
        timeout=120,
    )


def _run_writers(project: Path, draft: Path) -> list[subprocess.CompletedProcess[str]]:
    """Every writer, in the table's order, against one tree."""
    return [_launch(project, script, argv, draft)
            for _label, script, _code, argv in WRITERS]


def _assert_refused(proc, label: str, code: int, planted: Path, state: Path,
                    outside: Path, dirty_before: list[str], head_before: str,
                    what: str, *, committed: tuple[str, ...] = ()) -> None:
    """The shared post-conditions of one refusal, whatever shape was planted."""
    assert proc.returncode == code, (
        f"{label}: docs/PRODUCT.md 7 documents exit {code} for a wrong path, got "
        f"{proc.returncode}: {proc.stderr}"
    )
    err = proc.stderr.lower()
    assert "symlink" in err, f"{label}: the refusal must say what is wrong: {proc.stderr}"
    named = str(planted.relative_to(state))
    assert named in proc.stderr, (
        f"{label}: the refusal must name the offending path: {proc.stderr}")
    assert "fatal:" not in err and "pathspec" not in err, (
        f"{label}: an opaque git error, not a noni diagnostic: {proc.stderr}")
    assert "traceback" not in err, f"{label}: a crash, not a refusal: {proc.stderr}"
    assert planted.is_symlink(), f"{label}: the run unmade the planted link"
    _assert_wrote_nothing(state, outside, f"{label}: a refused run",
                          committed=committed)
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == dirty_before, (
        f"{label}: a refused run dirtied the state clone beyond the planted {what}")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before, (
        f"{label}: a refused run committed into the state clone")


def _assert_wrote_nothing(state: Path, root: Path, prefix: str, *,
                          committed: tuple[str, ...] = ()) -> None:
    """Neither tree holds a file any of the three writers composes.

    The names are the table's, so a refusal by one writer is also checked against the
    other two artifacts: a run that stopped early but wrote the wrong file still
    fails here. ``root`` is scanned by NAME, so the case directory above the state
    clone -- which holds the fixture's own committed files, the draft, and the
    outside directory the links point at -- does not have to be clean, only free of
    the names a writer of this run could have produced.

    ``committed`` names the paths the FIXTURE committed under its own name -- the
    ledger record and the intent -- which a sweep would otherwise report as "the run
    wrote it": the fixture's committed intent sits under a linked
    ``noni/direction``, and the first-run control commits the record ``order`` and
    ``intent`` cite. Those bytes are asserted unchanged where they live, not asserted
    away here.
    """
    wanted = set(CREATES.values()) - {Path(rel).name for rel in committed}
    for base, where in ((root, "outside the repo"), (state, "into the state root")):
        found = sorted(str(p.relative_to(base)) for p in base.rglob("*")
                       if ".git" not in p.parts and p.name in wanted)
        assert not found, f"{prefix} wrote {found} {where}"
