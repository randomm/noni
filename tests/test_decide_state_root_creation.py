"""The creator half of the state-root refusal: ``decide`` and its ``--init`` flag.

Split from ``tests/test_state_root_refusal.py``, which holds the entry points' exit
codes and the reader table. These are the runs that create state rather than read it:
the unflagged run that used to commit direction content into a public project
checkout, the same run with ``--init`` that lands it in a state root the caller
meant, and ``--no-commit``, which is no longer a way past the question. The fixtures
come from the refusal table so one tree builder describes the pilot's mistake on
both pages.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _harness import (
    CENSUS,
    DECIDE,
    INTENT,
    ORDER,
    _git,
    subprocess_env,
)
from decide_fixtures import _porcelain
from direction_symlink_fixtures import (
    NOW,
    PROBE_ID,
    RECORD_ID,
    WRITERS,
    _direction_state,
    _launch,
)
from test_state_root_refusal import (
    _INTENT_DRAFT,
    NOT_A_STATE_ROOT_WORDS,
    _code_repo,
    _commit_file,
    _launch_against,
)

from noni import _path_kind


def _code_repo_with_identity(tmp_path: Path, name: str) -> Path:
    """``_code_repo`` plus the identity ``decide`` commits under.

    ``_launch_against`` passes no identity env, so a run that reaches the
    attribution check answers with the missing-identity refusal instead of the
    state-root answer under test. The repo's own config carries it here, which is
    what the launcher-built rows of the refusal table rely on too.
    """
    repo = _code_repo(tmp_path, name)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    return repo


def _argv_naming(record_id: str) -> tuple[str, ...]:
    """``decide``'s argv for one record id, in the Route B fixture's own shape.

    Same flags as ``tests/direction_symlink_fixtures`` spells for its decide row, so
    this file's seeder writes the same bytes that suite's sweep expects -- the
    ``--init`` the seeder needs is added by the caller, not baked in here.
    """
    day, slug = record_id[:10], record_id[11:]
    return ("--slug", slug, "--date", day, "--scope", "release ordering",
            "--asked-by", "developer", "--question", "q1=Which order?",
            "--option", "q1=as listed", "--option", "q1=by risk",
            "--answer", "q1=as listed", "--no-commit")


def test_decide_creates_noni_on_a_tree_with_none_when_asked(tmp_path):
    """The first-run exception holds for every verb §7 names as a creator.

    A refusal that refused these too would be the same bug with the opposite exit
    code: the first order entry and the
    first intent file both legitimately bring ``noni/`` into being, and QUICKSTART's own
    command blocks are first runs. Each run below is against a committed tree with
    no ``noni/`` at all, so the only thing that lets it through is the exception.
    ``decide``'s first run is admitted the same way once the caller has said so with
    ``--init`` (issue #162), so its row carries the flag.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    draft = tmp_path / "intent-draft.md"
    draft.write_text(_INTENT_DRAFT, encoding="utf-8")

    cases = (
        (DECIDE, ("--slug", "first", "--scope", "first record", "--asked-by",
                  "dev", "--question", "q1=Ship?", "--option", "q1=yes",
                  "--option", "q1=no", "--answer", "q1=yes", "--init"),
         "noni/decisions"),
    )
    for script, argv, created in cases:
        repo = _code_repo(tmp_path, f"creator-{script.stem}")
        assert not (repo / "noni").exists(), (
            f"{script.stem}: the fixture built the very directory under test")
        proc = _launch_against(script, repo, cwd, *argv)
        assert proc.returncode == 0, (
            f"{script.stem}: the sanctioned creator was refused on a tree with no "
            f"noni/ -- {proc.returncode}: {proc.stderr}")
        assert (repo / created).is_dir(), (
            f"{script.stem}: exited 0 but did not create {created}: {proc.stdout}")
        assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, (
            f"{script.stem}: a first run must not meet the state-root refusal")


def test_a_first_record_is_admitted_where_the_second_would_commit_into_nothing(
        tmp_path):
    """A first record creates the ledger; a run that is not first is refused.

    The two runs are the same command against the same kind of tree, and only the
    ledger's own state tells them apart. The first is the caller's own
    ``--init`` run: it sees no ``noni/decisions`` at all, is admitted on the creator
    exception, and exits 0 with the directory it made -- which is how ``noni/`` ever
    comes to exist, and what QUICKSTART's command blocks do. The second finds that
    directory holding a committed record, so it is not a first run: it is naming a tree
    noni has written to, and the state-root refusal must not be the thing that stops it
    either way -- the run reaches its own answer (exit 4, the name is taken). Asserting
    both from one test is the point: a refusal that refused ``--init`` runs, or an
    exception that let commits into a recordless tree through, fails one half.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Probe?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01", "--init")
    repo = _code_repo(tmp_path, "first-record")
    first = _launch_against(DECIDE, repo, cwd, *argv)
    assert first.returncode == 0, f"{first.returncode}: {first.stderr}"
    assert (repo / "noni" / "decisions" / "2026-10-01-probe.json").is_file(), first.stdout
    assert NOT_A_STATE_ROOT_WORDS[0] not in first.stderr, first.stderr

    second = _launch_against(DECIDE, repo, cwd, *argv)
    assert second.returncode == 4, f"{second.returncode}: {second.stderr}"
    assert NOT_A_STATE_ROOT_WORDS[0] not in second.stderr, (
        f"a tree holding a record is a state root, not a wrong --repo: "
        f"{second.stderr}")


def test_a_tree_holding_a_noni_directory_is_a_state_root(tmp_path):
    """A tree with a ``noni/`` is a state root, whatever that directory holds.

    The contrast the refusal lives by, and the half the ticket's own reproduction does
    not reach: the wrong ``--repo`` with a ``noni/`` in it -- a ledger an aborted run
    left a file in -- is a tree noni has been told
    to look in, and the writer answers it with its normal reading of that state rather
    than with the state-root sentence. Only a tree with no ``noni/`` at all is the wrong
    tree: there is nothing under it to read or to arbitrate, which is the misleading
    message the ticket was filed about. The empty-``noni/`` case is the census's
    ``absent``/``empty`` distinction (``skills/census/SKILL.md``) and is pinned there; a
    second, contradicting account in a writer would be the same bug the ticket reported,
    told two ways.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Probe?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01")
    for name, rel in (("stray-ledger", "noni/decisions/left-behind.txt"),
                      ("stray-order", "noni/direction/left-behind.txt")):
        repo = _code_repo(tmp_path, name)
        held = repo / rel
        held.parent.mkdir(parents=True)
        held.write_text("state of somebody's\n", encoding="utf-8")
        proc = _launch_against(DECIDE, repo, cwd, *argv)
        assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, (
            f"{name}: a tree with a noni/ was refused as no state root: {proc.stderr}")


def test_a_direction_only_tree_is_a_state_root_that_still_answers_for_its_cite(tmp_path):
    """A ``noni/`` holding ``direction/`` and no ledger is a state root, not a residue.

    The pair the ledger question has to get right. ``intent set`` and ``order add`` are
    sanctioned creators of ``noni/direction``, so a caller who ran one of them first and
    has steered nothing yet has a tree with no ledger under it: that is a state root, and
    ``decide`` must not answer it with the state-root or the no-ledger refusal. What still
    refuses the run is the record ``intent set`` cites, which is that writer's own exit 4,
    and a plain ``decide`` into the same tree simply writes the first record.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Probe?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01")
    repo = _code_repo_with_identity(tmp_path, "direction-only")
    _commit_file(repo, "noni/direction/order.json", "{}\n")

    proc = _launch_against(DECIDE, repo, cwd, *argv)
    assert proc.returncode == 0, (
        f"a tree holding noni/direction is a state root, so the first record lands: "
        f"{proc.returncode}: {proc.stderr}")
    assert (repo / "noni" / "decisions" / "2026-10-01-probe.json").is_file(), proc.stdout
    for words in (NOT_A_STATE_ROOT_WORDS, ("no noni/decisions ledger",)):
        for word in words:
            assert word not in proc.stderr, (
                f"a state root holding a direction artifact met {word!r}: {proc.stderr}")
    assert _porcelain(repo) == "", f"left dirty: {_porcelain(repo)}"


def test_a_no_commit_run_needs_the_flag_too(tmp_path):
    """``--no-commit`` is not a creator exception: a first record needs ``--init``.

    The exception used to be the flag rather than the caller's word: any
    ``--no-commit`` run was admitted on a tree holding no ``noni/``, so the pilot's
    mistake was reproducible without committing at all -- the record landed and the
    caller's own commit is what took it. The route the exception was credited with
    (minting a record with no commit of its own) is gone. Both halves are asserted: the
    run is refused at 3 with the path named and nothing written, and the same run with
    ``--init`` lands the file uncommitted, which is what its caller then commits.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Ship?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01", "--no-commit")
    repo = _code_repo(tmp_path, "no-commit")
    proc = _launch_against(DECIDE, repo, cwd, *argv)
    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    for word in NOT_A_STATE_ROOT_WORDS:
        assert word in proc.stderr, f"the refusal must say {word!r}: {proc.stderr}"
    assert str(repo) in proc.stderr, proc.stderr
    assert not (repo / "noni").exists(), (
        f"a refused run created {repo / 'noni'}")

    admitted = _launch_against(DECIDE, repo, cwd, *argv, "--init")
    assert admitted.returncode == 0, f"{admitted.returncode}: {admitted.stderr}"
    made = repo / "noni" / "decisions" / "2026-10-01-probe.json"
    assert made.is_file(), admitted.stdout
    assert NOT_A_STATE_ROOT_WORDS[0] not in admitted.stderr, admitted.stderr


def test_the_seeder_of_a_new_state_root_is_the_one_run_that_carries_the_flag(
        tmp_path):
    """A ``--no-commit`` seeder that mints the record the other writers cite needs
    ``--init``, and it is the only run in the Route B fixture that does.

    The fixture behind ``tests/test_direction_symlink_refusal.py`` starts a private
    state clone with no ``noni/`` and has ``decide --no-commit`` mint the record
    ``order add`` and ``intent set`` then cite. Those two writers create
    ``noni/direction`` themselves, so only the seeder is a creator of the tree, and the
    table's decide row (which plants links at ``noni/decisions``) never runs on a
    recordless tree at all. Each half is asserted here rather than left to the sweep:
    without the flag the seeder is refused and writes nothing, with it the record lands
    and the two writers that follow read as they always did.
    """
    case = tmp_path / "seed"
    case.mkdir()
    project, state, draft = _direction_state(case, "project", with_noni=False)
    assert not (state / "noni").exists()

    plain = _launch(project, DECIDE, _argv_naming(f"{NOW[:10]}-plain"), draft)
    assert plain.returncode == 3, f"{plain.returncode}: {plain.stderr}"
    assert NOT_A_STATE_ROOT_WORDS[0] in plain.stderr, plain.stderr
    assert not (state / "noni").exists(), "a refused seeder created noni/"

    seed = _launch(project, DECIDE, _argv_naming(PROBE_ID) + ("--init",), draft)
    assert seed.returncode == 0, f"{seed.returncode}: {seed.stderr}"
    assert (state / "noni" / "decisions" / f"{PROBE_ID}.json").is_file(), seed.stdout

    order_argv = tuple(part.replace(RECORD_ID, PROBE_ID) for part in WRITERS[0][3])
    intent_argv = tuple(part.replace(RECORD_ID, PROBE_ID) for part in WRITERS[1][3])
    order_run = _launch(project, ORDER, order_argv, draft)
    intent_run = _launch(project, INTENT, intent_argv, draft)
    assert order_run.returncode == 0, order_run.stderr
    assert intent_run.returncode == 0, intent_run.stderr
    assert (state / "noni" / "direction" / "order.json").is_file()
    assert (state / "noni" / "direction" / "intent.md").is_file()


def test_the_creator_rule_asks_the_tree_first_and_opens_the_ledger_for_the_flag(tmp_path):
    """decide's creator rule: the tree refuses a wrong ``--repo``, the flag opens it.

    The rule is ``init and ledger_is_first(root)`` and both halves are pinned. The tree
    half, which is what the ticket names: a committed code repository whose ``noni`` is
    a plain file is no tree this run brings into being, so the run is refused (exit 3,
    the path named, its fix line named) and nothing is written -- and the refusal is
    reached *before* the ledger allocation, so the ``noni`` leaf that would have been
    mkdir'd is still absent afterwards, with or without ``--no-commit`` and with or
    without ``--init``. The flag half: a run into a tree that holds no ``noni/`` at all
    is the sanctioned first record once ``--init`` is given, and the file still lands
    uncommitted on a ``--no-commit`` run.

    A tree that already holds a ledger is not part of this pair: it is a state root and
    its run reaches its own answer, which
    :func:`test_a_first_record_is_admitted_where_the_second_would_commit_into_nothing`
    pins.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Ship?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01")

    for tag, extra in (("commit", ()), ("nc", ("--no-commit",)),
                       ("init", ("--init",)), ("init-nc", ("--init", "--no-commit"))):
        repo = _code_repo(tmp_path, f"creator-file-{tag}")
        (repo / "noni").write_text("not a directory\n", encoding="utf-8")
        proc = _launch_against(DECIDE, repo, cwd, *argv, *extra)
        assert proc.returncode == 3, (
            f"noni-as-a-file/{tag}: a tree whose noni is no directory is refused as a "
            f"wrong --repo: {proc.returncode}: {proc.stderr}")
        assert str(repo) in proc.stderr, proc.stderr
        assert "--repo" in proc.stderr or "fix:" in proc.stderr, proc.stderr
        assert not (repo / "noni" / "decisions").exists(), (
            f"noni-as-a-file/{tag}: the refused run allocated the ledger anyway")

    for tag, extra in (("commit", ("--init",)),
                       ("nc", ("--init", "--no-commit"))):
        repo = _code_repo(tmp_path, f"first-record-{tag}")
        proc = _launch_against(DECIDE, repo, cwd, *argv, *extra)
        assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
        assert (repo / "noni" / "decisions" / "2026-10-01-probe.json").is_file(), (
            proc.stdout)
        assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, proc.stderr


def test_an_uninspectable_repo_is_never_read_as_holding_no_noni(tmp_path):
    """A declined ``lstat`` is not evidence that a tree holds no state.

    The sibling directory guards in this module already refuse a declined answer rather
    than call it absent; the state-root question asks the same ``lstat`` and must give
    the same reading. Two things follow and both are asserted: the creator is not
    admitted on a fault (so no writer is let loose on a tree it could not inspect), and
    the fault is not worded as the missing-``noni/`` sentence -- the reader meets the
    direction guard's own refusal, which names the fault instead of guessing at it.
    """
    unreadable = tmp_path / "unreadable"
    (unreadable / "noni" / "direction").mkdir(parents=True)
    os.chmod(unreadable, 0o000)
    try:
        if _lstat_blocked(unreadable / "noni"):
            assert _path_kind.has_no_noni(unreadable) is False, (
                "an lstat the filesystem declined was read as an absent noni/, so a "
                "writer would be admitted to a tree it could not inspect")
            assert _path_kind.state_root_refusal(unreadable) is None, (
                "a tree that could not be inspected is not reported as a missing "
                "noni/: the fault belongs to the direction guard, which names it")
            assert "could not be inspected" in str(
                _path_kind.direction_refusal(unreadable, ("noni",))), (
                "the direction guard does not name the declined answer either")
    finally:
        os.chmod(unreadable, 0o755)


def test_a_writer_never_prints_a_refusal_that_is_not_one_line(tmp_path):
    """A ``--repo`` whose name carries a newline cannot split a refusal into two.

    Every path a writer prints goes through the one path renderer, so a crafted name
    shows as ``\\n`` and stays one line: the census's own contract is that its note
    opens the report and its verdict closes it, and a second, unprefixed line of
    operator text in between is what a consumer that splits on ``note: `` reads as a
    row. All three tools are run against the same crafted tree.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    crafted = tmp_path / "nl\nrepo"
    crafted.mkdir()
    crafted.joinpath("noni").write_text("not a directory\n", encoding="utf-8")
    cases = ((DECIDE, ("--slug", "probe", "--scope", "s", "--asked-by", "dev",
                       "--question", "q1=X?", "--option", "q1=yes",
                       "--option", "q1=no", "--answer", "q1=yes")),
             (ORDER, ("move", "7", "--to", "1", "--now", "2026-10-02T00:00:00Z")))
    for script, argv in cases:
        proc = _launch_against(script, crafted, cwd, *argv)
        lines = proc.stderr.splitlines()
        assert lines, f"{script.name}: the refused run printed nothing: {proc.stderr}"
        assert all(line.startswith(f"{script.stem}.py: ") for line in lines), (
            f"{script.name}: a refusal line carries no tool prefix, so the path broke "
            f"the line: {lines}")
        assert "\\n" in proc.stderr, (
            f"{script.name}: the crafted newline is printed raw: {lines}")
    (crafted / "no-state").mkdir()
    census_proc = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(crafted / "no-state")],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120)
    note_lines = [line for line in census_proc.stdout.splitlines()
                  if line.startswith("note: ")
                  and "no noni/ directory was found" in line]
    assert len(note_lines) == 1, (
        f"the note must be exactly one line: {census_proc.stdout.splitlines()[:4]}")
    assert census_proc.stdout.splitlines()[-1].startswith("summary: "), (
        census_proc.stdout.splitlines()[-1:])


def _lstat_blocked(path: Path) -> bool:
    """Whether this user genuinely cannot ``lstat`` ``path`` (root can lstat anything)."""
    try:
        os.lstat(path)
    except OSError:
        return True
    return False
