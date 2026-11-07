"""The documented exit code for a --repo that is no noni state root (issues #39, #120).

docs/PRODUCT.md §7 names one code per tool for a wrong path, and it names two states
that wrong path comes in: a `--repo` that is not a directory at all, and a `--repo`
that is a directory holding no `noni/`. The second is the one a caller actually
arrives at (a code repository where the state clone was meant), and it is the one no
test covered: every case here used to name a path that does not exist, so a directory
that merely lacked `noni/` fell through to the readers and answered "no decision
record ... is in the ledger" about a tree holding no ledger.

One table, one run per row: the point is the code, so the assertion is the code plus a
message that names the path the caller passed. Each run is launched from a cwd that is
not the state root, so a refusal that arrived from somewhere else would have to
produce the number as well. The first-run creators are asserted from the same table,
because a refusal that also refused `decide`'s first record would pass every row
above.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _harness import (
    CENSUS,
    CLAIM,
    CLOSE,
    DECIDE,
    INTENT,
    ORDER,
    REGISTER,
    RELEASE,
    _commit_file,
    _git,
    _init_repo,
    subprocess_env,
)

from noni import _path_kind

# The refusal's code and the tool that owes it, exactly as §7 states them. This
# tuple is the prose transcribed: a change on either side breaks this test.
STATE_ROOT_REFUSAL = (
    (ORDER, 2),
    (REGISTER, 2),
    (DECIDE, 3),
    (CLAIM, 4),
    (CLOSE, 4),
    (RELEASE, 4),
)

# The tools §7 gives code 2, and the ones it gives 3 and 4: the prose test below
# reads the numbers off the page rather than trusting this table alone.
DOCUMENTED = {
    2: ("`order`", "`register`", "census"),
    3: ("`decide`",),
    4: ("`claim`", "`close`", "`release`"),
}

# One minimum argv beyond --repo per tool: enough to get past argparse to the
# state-root check, and values no assertion depends on, since the run is refused
# before any of them is read.
ARGV = {
    CLAIM: ("--session-id", "2026-10-01-aaaaaa", "--task", "#42"),
    CLOSE: ("--session-id", "2026-10-01-aaaaaa"),
    RELEASE: ("--session-id", "2026-10-01-aaaaaa", "--task", "#42"),
    REGISTER: ("--identity", "developer"),
    DECIDE: ("--slug", "state-root", "--scope", "release ordering",
             "--asked-by", "developer", "--question", "q1=Probe?",
             "--option", "q1=yes", "--option", "q1=no", "--answer", "q1=yes"),
    ORDER: ("add", "7", "--decision", "2026-10-01-absent", "--now",
            "2026-10-02T00:00:00Z"),
}

# The verbs and runs that reach the state-root question, with the code §7 gives each,
# and whether the run is a sanctioned creator of `noni/` (so it must be admitted rather
# than refused -- the first run has to be allowed to make the tree).
# `order add` is a creator and so is `intent set`; every other verb here only reads
# state it expects to already exist, so a tree holding none is a wrong --repo. `decide`
# has no verb to ask, so its rows carry the shape that makes the run one or the other:
# `no-commit` and an empty ledger are creators, a run that would commit into a tree
# whose `noni/` already holds a record is not.
NO_NONI_REFUSAL: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("order", ("move", "7", "--to", "1", "--now", "2026-10-02T00:00:00Z"), 2),
    ("order", ("remove", "7", "--now", "2026-10-02T00:00:00Z"), 2),
    # The bug the ticket reproduced live: confirm with no issue arg wrote a valid
    # empty order.json and exited 0 on a tree with no noni/. Nothing legitimate is
    # created by it, so it is refused.
    ("order", ("confirm", "--now", "2026-10-02T00:00:00Z"), 2),
)

# The words the refusal owes the operator for this one state: the path is named, the
# state is named as a noni state root the path is not, and the fix names the flag the
# caller passed wrong. Spelled as the phrases a reader scans for rather than a full
# sentence, so the product may rewrap the line without breaking the contract.
NOT_A_STATE_ROOT_WORDS = ("is not a noni state root", "no noni/")


def _launch(script: Path, missing: Path, cwd: Path,
            *extra: str) -> subprocess.CompletedProcess[str]:
    """One entry point launched with --repo naming a path that is not a directory."""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(missing), *extra],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120,
    )


def _code_repo(tmp_path: Path, name: str) -> Path:
    """A committed git tree that holds source and no noni/: the pilot's mistake.

    The reproduction the ticket is written from. A repo built by _init_repo alone has
    no commit at all, and the writers' git probes answer differently there, so the
    README is committed first: this is the tree a caller points --repo at when they
    meant the state clone, and it is a valid git work tree, so decide's work-tree
    check admits it and only the state-root question refuses it.
    """
    repo = _init_repo(tmp_path / name)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_file(repo, "README.md", "# a code repository\n")
    _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
    return repo


def _launch_against(script: Path, repo: Path, cwd: Path,
                    *extra: str) -> subprocess.CompletedProcess[str]:
    """One entry point launched with --repo naming a committed tree holding no noni/."""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(repo), *extra],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120,
    )



def test_each_writer_refuses_a_repo_that_is_not_a_directory_with_its_own_code(tmp_path):
    """Every writer named in §7 answers with the code §7 gives it."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    for script, expected in STATE_ROOT_REFUSAL:
        missing = tmp_path / f"no-such-root-{script.stem}"
        proc = _launch(script, missing, cwd, *ARGV[script])
        assert proc.returncode == expected, (
            f"{script.name}: docs/PRODUCT.md §7 documents exit {expected} for a "
            f"--repo that is not a directory, got {proc.returncode}: {proc.stderr}"
        )
        assert "--repo" in proc.stderr.lower() or "is not a git work tree" in proc.stderr, (
            f"{script.name}: the refusal must name the argument it refused "
            f"(decide.py names the tree, the others the flag): {proc.stderr}"
        )
        assert ("is not a directory" in proc.stderr
                or "is not a git work tree" in proc.stderr), (
            f"{script.name}: the refusal must name the state it found: {proc.stderr}"
        )
        assert not missing.exists(), f"{script.name}: the refused run created {missing}"


def test_the_unified_census_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """The census answers the same state with its own usage code (2).

    Its wording differs ("repo path does not exist") because the census takes a
    directory to audit rather than writing into one, so this asserts the code and
    that the path is named, which is what makes the refusal actionable.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    missing = tmp_path / "no-such-root-census"
    proc = _launch(CENSUS, missing, cwd)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "no-such-root-census" in proc.stderr, proc.stderr


def test_the_readers_refuse_a_repo_that_holds_no_noni_directory(tmp_path):
    """A committed tree with no noni/ is refused by every verb that creates nothing.

    This is the state every other test missed: the path exists and is a git work
    tree, so the writers' existing ``is_dir`` and work-tree checks pass it, and
    before this refusal the run fell through to the reads and printed "no decision
    record ... is in the ledger" about a repository holding no ledger (the pilot's
    Route B report). The code is each tool's own wrong-path code from §7, unchanged.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    scripts = {"order": ORDER, "intent": INTENT}
    draft = tmp_path / "draft.md"
    draft.write_text(_INTENT_DRAFT, encoding="utf-8")
    for tool, argv, code in NO_NONI_REFUSAL:
        repo = _code_repo(tmp_path, f"noreader-{tool}-{argv[0]}")
        # A draft that exists: the run must be refused for its state root, not for a
        # missing --from file, which argparse answers first.
        proc = _launch_against(scripts[tool], repo, cwd,
                               *[str(draft) if a == "DRAFT" else a for a in argv])
        assert proc.returncode == code, (
            f"{tool} {argv[0]}: docs/PRODUCT.md §7 gives {code} for a wrong --repo, "
            f"got {proc.returncode}: {proc.stderr}"
        )
        assert str(repo) in proc.stderr, (
            f"{tool} {argv[0]}: the refusal must name the path it refused: "
            f"{proc.stderr}")
        for word in NOT_A_STATE_ROOT_WORDS:
            assert word in proc.stderr, (
                f"{tool} {argv[0]}: the refusal must say {word!r}: {proc.stderr}")
        assert "--repo" in proc.stderr, (
            f"{tool} {argv[0]}: the fix must name the flag the caller passed wrong: "
            f"{proc.stderr}")
        # The misleading answer this ticket exists to close, asserted absent: the
        # ledger sentence is true of a record and useless about a wrong --repo.
        assert "is in the ledger" not in proc.stderr, (
            f"{tool} {argv[0]}: reached the ledger reads instead of refusing the "
            f"state root: {proc.stderr}")
        assert not (repo / "noni").exists(), (
            f"{tool} {argv[0]}: a refused run created {repo / 'noni'}")


def test_the_sanctioned_creators_still_create_noni_on_a_tree_with_none(tmp_path):
    """The first-run exception holds for every verb §7 names as a creator.

    A refusal that refused these too would be the same bug with the opposite exit
    code: the first record, the first order entry, the first intent file and the
    first session all legitimately bring ``noni/`` into being, and QUICKSTART's own
    command blocks are first runs. Each run below is against a committed tree with
    no ``noni/`` at all, so the only thing that lets it through is the exception.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    draft = tmp_path / "intent-draft.md"
    draft.write_text(_INTENT_DRAFT, encoding="utf-8")

    cases = (
        (DECIDE, ("--slug", "first", "--scope", "first record", "--asked-by",
                  "dev", "--question", "q1=Ship?", "--option", "q1=yes",
                  "--option", "q1=no", "--answer", "q1=yes"), "noni/decisions"),
        (REGISTER, ("--identity", "developer", "--no-commit"), "noni/sessions"),
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
    ledger's own state tells them apart. The first sees no ``noni/decisions`` at all,
    is admitted on the creator exception, and exits 0 with the directory it made --
    which is how ``noni/`` ever comes to exist, and what QUICKSTART's command blocks
    do. The second finds that directory holding a committed record, so it is not a
    first run: it is naming a tree noni has written to, and the state-root refusal
    must not be the thing that stops it either way -- the run reaches its own answer
    (exit 4, the name is taken). Asserting both from one test is the point: a
    refusal that refused first runs, or an exception that let commits into a
    recordless tree through, fails one half.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    argv = ("--slug", "probe", "--scope", "state root", "--asked-by", "dev",
            "--question", "q1=Probe?", "--option", "q1=yes", "--option", "q1=no",
            "--answer", "q1=yes", "--date", "2026-10-01")
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
    not reach: the wrong ``--repo`` with a ``noni/`` in it -- another writer's session
    register, or a ledger an aborted run left a file in -- is a tree noni has been told
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
    for name, rel in (("sessions-tree", "noni/sessions/2026-10-01-aaaaaa.md"),
                      ("stray-ledger", "noni/decisions/left-behind.txt")):
        repo = _code_repo(tmp_path, name)
        held = repo / rel
        held.parent.mkdir(parents=True)
        held.write_text("state of somebody's\n", encoding="utf-8")
        proc = _launch_against(DECIDE, repo, cwd, *argv)
        assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, (
            f"{name}: a tree with a noni/ was refused as no state root: {proc.stderr}")


def test_decide_no_commit_is_admitted_on_a_tree_with_no_noni(tmp_path):
    """``--no-commit`` stays open where the tree itself holds no ``noni/``.

    The shim and the session writers drive ``decide --no-commit`` to mint a record
    without a commit of its own, so a state-root refusal that stopped it would stop
    those routes outright. The tree answers the question, not the flag: on a tree with
    no ``noni/`` the run is the first writer either way, and the file still lands
    uncommitted, which is what the caller then commits.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "no-commit")
    proc = _launch_against(DECIDE, repo, cwd,
                           "--slug", "probe", "--scope", "state root", "--asked-by",
                           "dev", "--question", "q1=Ship?", "--option", "q1=yes",
                           "--option", "q1=no", "--answer", "q1=yes",
                           "--date", "2026-10-01", "--no-commit")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert (repo / "noni" / "decisions" / "2026-10-01-probe.json").is_file(), proc.stdout
    assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, proc.stderr


def test_the_creator_rule_asks_the_tree_first_and_keeps_the_no_commit_route(tmp_path):
    """decide's creator rule: the tree refuses a wrong ``--repo``, the flag keeps its route.

    The rule is ``ledger_is_first(root) or no_commit`` and both halves are pinned. The
    tree half, which is what the ticket names: a committed code repository whose
    ``noni`` is a plain file is no tree this run brings into being, so the run is
    refused (exit 3, the path named, its fix line named) and nothing is written -- and
    the refusal is reached *before* the ledger allocation, so the ``noni`` leaf that
    would have been mkdir'd is still absent afterwards. The flag half: a run into a tree
    that holds no ``noni/`` at all is the sanctioned first record and stays open with or
    without ``--no-commit``, so the shim route that mints a record without committing it
    is not closed by the guard.

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

    for no_commit in (False, True):
        tag = "nc" if no_commit else "commit"
        repo = _code_repo(tmp_path, f"creator-file-{tag}")
        (repo / "noni").write_text("not a directory\n", encoding="utf-8")
        proc = _launch_against(DECIDE, repo, cwd, *argv,
                               *(() if not no_commit else ("--no-commit",)))
        assert proc.returncode == 3, (
            f"noni-as-a-file/{tag}: a tree whose noni is no directory is refused as a "
            f"wrong --repo: {proc.returncode}: {proc.stderr}")
        assert str(repo) in proc.stderr, proc.stderr
        assert "--repo" in proc.stderr or "fix:" in proc.stderr, proc.stderr
        assert not (repo / "noni" / "decisions").exists(), (
            f"noni-as-a-file/{tag}: the refused run allocated the ledger anyway")

    for no_commit in (False, True):
        tag = "nc" if no_commit else "commit"
        repo = _code_repo(tmp_path, f"first-record-{tag}")
        proc = _launch_against(DECIDE, repo, cwd, *argv,
                               *(() if not no_commit else ("--no-commit",)))
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


# A minimal intent draft for the creator case: `intent set` refuses a file that is not
# an intent artifact, so a first-run test that handed it prose would test the wrong
# refusal. The four sections are the shape intentschema validates.
_INTENT_DRAFT = """# Intent
Last-confirmed: 2026-10-01
## Purpose
Ship the release.
## Principles
Prefer the boring technology.
## Never
Never force push.
## Ask first
Anything that costs money.
"""
