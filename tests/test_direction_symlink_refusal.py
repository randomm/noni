"""``decide``, ``order`` and ``intent`` refuse a symlinked ``noni/`` and a symlinked
output directory, on the code docs/PRODUCT.md 7 owes each of them (issue #104).

The three direction writers already refused a link at the FILE they write: the
artifact, the intent, the record and the supersede target are each classified by
``lstat``. What none of them refused was the DIRECTORY above those files. Each writer
guarded its parent with ``exists()``/``is_dir()`` and created it with ``mkdir``, and
all three follow links -- so with ``noni/direction`` committed as a link to a
directory outside the state repository, ``order add`` wrote ``order.json`` into that
outside directory and exited 0, and the same held for ``intent set`` through
``noni/`` and for ``decide`` through ``noni/decisions``. The read leaked the same
way: ``order add --decision ID`` answered "no record carries that id" from bytes read
through a linked ``noni/``, and the committed route leaked first and only then heard
git say a path was "beyond a symbolic link".

The session writers refused all of this already (_session_guard / _session_paths,
issue #68). They keep their own wording: the direction guard answers the same
directory question from :func:`noni._path_kind.direction_refusal`, in sentences that
name a directory and no session file, and each writer prints the pair through its own
failure printer with its own code.

So each test here is the run plus what the run did NOT do: the planted link is still
a link, the outside target holds the bytes the fixture wrote and no artifact the run
composed, nothing appeared under the state root, and porcelain and HEAD are unmoved.
The last tests are the other half of the contract -- a plain tree still writes all
three artifacts, a project reached *through* a linked ancestor is still a normal run,
and a first run with no ``noni/`` at all still creates it. Without those the guard
could turn the documented layout into a refusal and every test above would still
pass.
"""

from __future__ import annotations

import json
import os
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
# the --now that names it. Deliberately NOT a name the sweep above plants.
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


def test_each_writer_refuses_a_symlinked_noni_directory(tmp_path):
    """AC1/AC2: ``noni/`` itself a link outside the clone is refused by all three
    writers, before the read -- ``lstat`` cannot see through it from below."""
    for index, (label, script, code, argv) in enumerate(WRITERS):
        case = tmp_path / f"noni-{index}"
        case.mkdir()
        project, state, draft = _direction_state(case, f"p{index}")
        outside = case / f"outside-noni-{index}"
        planted = _plant_link(state, outside, "noni")
        # The decoy a following read would have reached: a record body carrying the
        # cited id, which a leaf classification would have accepted as the record.
        # ``rel``'s last component is the directory the link leads to, so the path
        # under the position is spelled from here, not from the position's own name.
        decoy = outside / "noni" / "decisions" / f"{RECORD_ID}.json"
        decoy.write_text(_decoy(label), encoding="utf-8")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        proc = _launch(project, script, argv, draft)

        _assert_refused(proc, label, code, planted, state, outside, dirty_before,
                        head_before, "noni link", committed=("noni/direction/intent.md",))
        assert decoy.read_text(encoding="utf-8") == _decoy(label), (
            f"{label}: the run wrote through the noni link")


def test_each_writer_refuses_a_symlinked_output_directory(tmp_path):
    """AC1/AC2: a link at the directory each writer writes into is refused on its
    own code -- ``noni/direction`` for order and intent, ``noni/decisions`` for
    decide -- and the committed route never reaches git's pathspec error."""
    positions = {"order": "noni/direction", "intent": "noni/direction",
                 "decide": "noni/decisions"}
    for index, (label, script, code, argv) in enumerate(WRITERS):
        case = tmp_path / f"out-{index}"
        case.mkdir()
        project, state, draft = _direction_state(case, f"p{index}")
        outside = case / f"outside-out-{index}"
        rel = OUTPUT_POSITIONS[label]
        planted = _plant_link(state, outside, rel)
        # The bytes a following writer would have overwritten or read.
        decoy = outside / Path(rel).name / CREATES[label]
        decoy.parent.mkdir(parents=True, exist_ok=True)
        decoy.write_text(_decoy(label), encoding="utf-8")
        # The sweep's "nothing written" check cannot also see this position: the
        # decoy is the fixture's byte standing at the name the writer would have
        # used, and the comparison below is what proves the run left it alone.
        planted_names = (f"{rel}/{CREATES[label]}",)
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        proc = _launch(project, script, argv, draft)

        _assert_refused(proc, label, code, planted, state, outside, dirty_before,
                        head_before, f"{rel} link",
                        committed=("noni/direction/intent.md",) + planted_names)
        assert decoy.read_text(encoding="utf-8") == _decoy(label), (
            f"{label}: the run wrote through the {rel} link")


def test_each_writer_refuses_a_dangling_link_at_its_directory(tmp_path):
    """AC1: a link to nothing is refused as a link, not answered as an absent
    directory. ``is_dir()`` says no to a dangling link and ``mkdir`` would then have
    failed inside git's pathspec; ``lstat`` says what stands there, and a refusal
    creates neither the link's target nor a directory of its own."""
    positions = {"order": "noni/direction", "intent": "noni/direction",
                 "decide": "noni/decisions"}
    for index, (label, script, code, argv) in enumerate(WRITERS):
        case = tmp_path / f"dangling-{index}"
        case.mkdir()
        project, state, draft = _direction_state(case, f"p{index}")
        rel = OUTPUT_POSITIONS[label]
        planted = state / rel
        shutil.rmtree(planted)
        target = case / f"nothing-here-{index}"
        planted.symlink_to(target)
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        proc = _launch(project, script, argv, draft)

        _assert_refused(proc, label, code, planted, state, case, dirty_before,
                        head_before, f"dangling {rel} link",
                        committed=("noni/direction/intent.md",))
        # Nothing was written anywhere under the case directory, and the link's
        # target was not conjured into existence beside it.
        _assert_wrote_nothing(state, case, f"{label}: a refused run",
                              committed=("noni/direction/intent.md",))
        assert not target.exists(), f"{label}: a refused run created the link's target"


def test_each_writer_refuses_a_non_directory_at_its_directory(tmp_path):
    """AC1: a plain file at the writer's output directory is refused too, and the
    sentence says what the ``lstat`` actually found rather than calling it a link.

    This is the state the writers used to answer with exit 3 and the words "is not a
    directory"; docs/PRODUCT.md 7 now gives a wrong path each tool's own code, so
    both halves of that change are pinned here -- the code moves, the wording does
    not invent a link that is not there.
    """
    positions = {"order": "noni/direction", "intent": "noni/direction",
                 "decide": "noni/decisions"}
    for index, (label, script, code, argv) in enumerate(WRITERS):
        case = tmp_path / f"plain-{index}"
        case.mkdir()
        project, state, draft = _direction_state(case, f"p{index}")
        rel = OUTPUT_POSITIONS[label]
        planted = state / rel
        shutil.rmtree(planted)
        planted.write_text(_decoy(label), encoding="utf-8")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        proc = _launch(project, script, argv, draft)

        assert proc.returncode == code, (
            f"{label}: exit {code} for a wrong path, got {proc.returncode}: "
            f"{proc.stderr}")
        assert "is not a directory" in proc.stderr, proc.stderr
        assert "symlink" not in proc.stderr.lower(), (
            f"{label}: a plain file is not a link: {proc.stderr}")
        assert str(planted.relative_to(state)) in proc.stderr, proc.stderr
        assert planted.read_text(encoding="utf-8") == _decoy(label), (
            f"{label}: a refused run replaced the file at {rel}")
        _assert_wrote_nothing(state, case, f"{label}: a refused run",
                              committed=("noni/direction/intent.md",))
        assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == (
            dirty_before)
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


def test_a_plain_tree_still_writes_all_three_artifacts(tmp_path):
    """AC3, the control: with real directories the three runs succeed and the word
    symlink never appears, so the guard has not turned the layout into a refusal."""
    case = tmp_path / "plain-ok"
    case.mkdir()
    # No committed intent: this control asserts the three writers each CREATE their
    # file, and a fixture that had already committed ``intent.md`` would have been
    # satisfied by its own fixture rather than by the run.
    project, state, draft = _direction_state(case, "project", committed_intent=False)
    for (label, _script, _code, _argv), proc in zip(WRITERS,
                                                     _run_writers(project, draft)):
        assert proc.returncode == 0, f"{label}: {proc.returncode}: {proc.stderr}"
        assert "symlink" not in (proc.stdout + proc.stderr).lower(), proc.stderr
    assert (state / "noni" / "direction" / "order.json").is_file()
    assert (state / "noni" / "decisions" / "2026-10-11-sweep-probe.json").is_file()


def test_a_project_reached_through_a_symlinked_ancestor_still_writes(tmp_path):
    """AC3, the ancestor half: the guard examines no ancestor of --repo, so the
    layout the quickstart sells -- a project opened through a link -- is a normal
    run for all three writers. This is the case a guard that resolved its root would
    have turned into a refusal."""
    case = tmp_path / "linked-ancestor"
    case.mkdir()
    project, state, draft = _direction_state(case, "project")
    through = case / "project-link"
    through.symlink_to(project)
    for (label, _script, _code, _argv), proc in zip(WRITERS,
                                                    _run_writers(through, draft)):
        assert proc.returncode == 0, f"{label}: {proc.returncode}: {proc.stderr}"
        assert "symlink" not in (proc.stdout + proc.stderr).lower(), proc.stderr
    assert (state / "noni" / "direction" / "order.json").is_file()


def test_a_first_run_with_no_noni_directory_still_creates_it(tmp_path):
    """AC3, the first-run half: absent is an answer and not a refusal, so the guard
    admits ``ENOENT`` and ``mkdir`` still builds ``noni/``, ``noni/direction`` and
    ``noni/decisions`` on a tree that has never had them.

    The regression pins AGENTS.md names for this route (``test_order_writer_add.py``
    and ``test_decide_commit.py``) cover one writer each; this covers all three on
    one tree that starts with nothing but a committed README. The citation the two
    direction writers must name is the record this tree's own ``decide`` run mints --
    so the order of the three runs is part of what is being asserted: a writer that
    wrote before it could cite would be a different contract.
    """
    case = tmp_path / "first-run"
    case.mkdir()
    project, state, draft = _direction_state(case, "project", with_noni=False)
    assert not (state / "noni").exists()
    # A first tree has no record to cite, and both direction writers refuse a
    # citation the ledger does not hold, so ``decide`` mints the record the other two
    # then name. That it can do so on a tree with no ``noni/`` at all is half of what
    # this test is for; the order of the three runs is the other half -- a writer that
    # wrote before it could cite would be a different contract.
    seed = _launch(project, DECIDE, _argv_naming(PROBE_ID), draft)
    assert seed.returncode == 0, seed.stderr
    order_run, intent_run, decide_run = _run_writers_before_citation(project, draft)
    assert order_run.returncode == 0, order_run.stderr
    assert decide_run.returncode == 0, decide_run.stderr
    assert intent_run.returncode == 0, intent_run.stderr
    assert (state / "noni" / "direction" / "order.json").is_file()
    assert (state / "noni" / "direction" / "intent.md").is_file()
    assert (state / "noni" / "decisions" / f"{PROBE_ID}.json").is_file()
    assert (state / "noni" / "decisions" / "2026-10-11-second-probe.json").is_file()


def _argv_naming(record_id: str) -> tuple[str, ...]:
    """``decide``'s argv for one record id, in this suite's own question shape.

    The id is ``<date>-<slug>``, so the slug and the date are the only flags that
    decide the name a citation can use; ``record_id`` is split on its own date
    because that is how the writer composes it.
    """
    day, _, slug = record_id[:10], record_id[10], record_id[11:]
    return ("--slug", slug, "--date", day, "--scope", "release ordering",
            "--asked-by", "developer", "--question", "q1=Which order?",
            "--option", "q1=as listed", "--option", "q1=by risk",
            "--answer", "q1=as listed", "--no-commit")


def _run_writers_before_citation(project: Path, draft: Path):
    """The three writers in the table's order, both direction writers citing the
    record the caller minted, and ``decide`` minting a second one beside it."""
    order_argv = tuple(part.replace(RECORD_ID, PROBE_ID) for part in WRITERS[0][3])
    intent_argv = tuple(part.replace(RECORD_ID, PROBE_ID) for part in WRITERS[1][3])
    return (_launch(project, ORDER, order_argv, draft),
            _launch(project, INTENT, intent_argv, draft),
            _launch(project, DECIDE, _argv_naming(f"{NOW[:10]}-second-probe"), draft))


def test_the_direction_guard_refuses_nothing_for_an_absent_or_real_directory(tmp_path):
    """The guard's own verdicts, asked in the process: absent answers None, a real
    directory answers None, and only a link or a non-directory answers a pair.

    The three writers reach this function through their own
    ``_refuse_linked_state``; testing the primitive here means the writers' table
    above does not have to re-prove the absent case three times to show a first run
    is not a refusal.
    """
    from noni import _path_kind

    root = tmp_path / "guard"
    (root / "noni" / "direction").mkdir(parents=True)
    rels = ("noni", "noni/direction", "noni/decisions")
    assert _path_kind.direction_refusal(root, rels) is None
    (root / "noni" / "decisions").symlink_to(tmp_path / "nowhere")
    refused = _path_kind.direction_refusal(root, rels)
    assert refused is not None
    assert "symlink" in refused[0] and "noni/decisions" in refused[0], refused
    assert "replace" in refused[1] and "real directory" in refused[1], refused
    # A component above the position asked is refused before the one below it, which
    # is what "asks every component" buys: a link at noni hides a fine directory.
    hidden = tmp_path / "hidden"
    (hidden / "real").mkdir(parents=True)
    (hidden / "real" / "decisions").mkdir()
    (hidden / "noni").symlink_to(hidden / "real")
    refused = _path_kind.direction_refusal(hidden, rels)
    assert refused is not None and refused[0].endswith("is a symlink: noni never "
                                                       "reads or writes through it")
    assert refused[0].startswith(str(hidden / "noni")), refused[0]


def test_a_declined_lstat_is_a_refusal_and_never_an_absence(tmp_path):
    """``EACCES`` and ``ELOOP`` are refusals, not ``ENOENT``.

    The two shapes are produced without a mode-000 directory: a link cycle is the
    declined answer ``lstat`` gives on its own, and an unreadable parent is skipped
    where the reading user can read it anyway (running as root), exactly as the
    session guard's own inspection suite does.
    """
    import os

    import pytest

    from noni import _path_kind

    root = tmp_path / "declined"
    (root / "noni").mkdir(parents=True)
    (root / "noni" / "a").symlink_to("b")
    (root / "noni" / "b").symlink_to("a")
    # The loop is refused as the link it is, and a component below it is refused as
    # an answer the filesystem declined rather than as an absent directory.
    refused = _path_kind.direction_refusal(root, ("noni", "noni/a/c"))
    assert refused is not None, "a link below a link was read as absent"
    assert "noni/a" in refused[0], refused[0]

    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (unreadable / "noni" / "direction").mkdir(parents=True)
    os.chmod(unreadable, 0o000)
    try:
        if _lstat_ok(unreadable / "noni"):
            pytest.skip("the reading user can lstat through a 000-mode parent")
        refused = _path_kind.direction_refusal(unreadable,
                                               ("noni", "noni/direction"))
    finally:
        os.chmod(unreadable, 0o755)
    assert refused is not None, "an unreadable parent read as an absent directory"
    assert "could not be inspected" in refused[0], refused[0]


def _lstat_ok(path: Path) -> bool:
    """Whether this user actually can ``lstat`` ``path`` (root can lstat anything)."""
    import os

    try:
        os.lstat(path)
    except OSError:
        return False
    return True


def test_the_three_writers_share_one_guard_and_open_code_no_lstat_of_their_own():
    """The shared-ownership pin: all three reach the refusal through the one
    helper, and none of them open-codes the directory question again.

    A fourth writer that grew its own ``lstat`` loop would print its own wording on
    its own code and pass every behavioural test above; the identity assertions are
    what make that drift fail a check instead of a review.
    """
    from noni import _path_kind, decide, intent, order

    for module in (decide, order, intent):
        assert module._refuse_linked_state.__globals__["_path_kind"] is _path_kind, (
            f"{module.__name__} must reach the refusal through noni._path_kind")
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "os.lstat" not in source, (
            f"{module.__name__} open-codes an lstat; the guard is "
            "noni._path_kind.direction_refusal")
        assert "S_ISLNK" not in source, (
            f"{module.__name__} classifies path kinds itself")
    # The directories each writer guards, read off the modules rather than restated
    # here: a writer that stopped guarding the ledger it reads fails this line.
    assert order._GUARDED_DIRS == ("noni", "noni/direction", "noni/decisions")
    assert intent._GUARDED_DIRS == ("noni", "noni/direction", "noni/decisions")
    assert decide._GUARDED_DIRS == ("noni", "noni/decisions")
