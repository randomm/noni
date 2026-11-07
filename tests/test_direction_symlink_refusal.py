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

import ast
import shutil
from pathlib import Path

from _harness import DECIDE, INTENT, ORDER
from direction_symlink_fixtures import (
    CREATES,
    NOW,
    OUTPUT_POSITIONS,
    PROBE_ID,
    RECORD_ID,
    WRITERS,
    _assert_refused,
    _assert_wrote_nothing,
    _decoy,
    _direction_state,
    _git_ok,
    _launch,
    _plant_link,
    _run_writers,
)


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
                                                     _run_writers(project, draft),
                                                     strict=True):
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
                                                    _run_writers(through, draft),
                                                    strict=True):
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
    what make that drift fail a check instead of a review. A writer may hold the seam
    that prints the refusal (``decide`` keeps its own, in :mod:`noni._decide_flags`,
    to stay within the file-size limit) but the seam must reach the one helper, so
    the walk is followed through the module that owns the seam's globals too.
    """
    from noni import _decide_flags, _path_kind, decide, intent, order

    # The seam module whose own source is searched for an open-coded walk: a writer
    # that keeps its printing in a module of its own is held to the same rule there.
    seams = {decide: _decide_flags, order: order, intent: intent}
    for module in (decide, order, intent):
        seam = module._refuse_linked_state
        assert _walks_the_guard(seam) is _path_kind, (
            f"{module.__name__} must reach the refusal through noni._path_kind, "
            f"not its own walk")
        source = Path(seams[module].__file__).read_text(encoding="utf-8")
        assert "os.lstat" not in source, (
            f"{seams[module].__name__} open-codes an lstat; the guard is "
            "noni._path_kind.direction_refusal")
        assert "S_ISLNK" not in source, (
            f"{seams[module].__name__} classifies path kinds itself")
    # The directories each writer guards, read off the modules rather than restated
    # here: a writer that stopped guarding the ledger it reads fails this line.
    assert order._GUARDED_DIRS == ("noni", "noni/direction", "noni/decisions")
    assert intent._GUARDED_DIRS == ("noni", "noni/direction", "noni/decisions")
    assert decide._GUARDED_DIRS == ("noni", "noni/decisions")


def _walks_the_guard(seam) -> object:
    """The module the refusal's walk is actually reached through, ``None`` if none.

    The seam's own module first (a writer whose seam calls ``_path_kind`` directly is
    done), then the package modules the seam imports by name -- which is how a seam
    that delegates its question one module deeper, as ``decide`` does through
    ``_decide_flags``, is still followed into the code that asks ``lstat``. The
    question is whether any of the code between the writer and the ``lstat`` is a walk
    of its own, not how many files the hop passes through.

    The imports are read from the seam's own source and resolved against its globals
    rather than scanned out of the module namespace: a module-level name that happens
    to hold a package module is not what the seam calls.
    """
    own = seam.__globals__.get("_path_kind")
    if own is not None:
        return own
    try:
        source = Path(seam.__globals__["__file__"]).read_text(encoding="utf-8")
    except OSError:
        return None
    for name in _imported_module_names(source):
        value = seam.__globals__.get(name)
        reached = getattr(value, "__dict__", {}).get("_path_kind")
        if reached is not None:
            return reached
    return None


def _imported_module_names(source: str) -> list[str]:
    """The module names this source imports from the package, innermost last.

    ``from . import _x`` and ``from ._y import _z`` both count; the leaf module of a
    dotted import is the one whose body asks the question, so ``_z`` is returned for
    the second form.
    """
    found: list[str] = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        for alias in node.names:
            found.append(alias.name.rsplit(".", 1)[-1])
    return found
