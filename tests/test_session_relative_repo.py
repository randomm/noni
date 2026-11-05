"""The private-state route as a reader names it: a relative ``--repo`` (issue #66,
and the printed path token of issue #77 AC2).

docs/PRODUCT.md 7 sells a second state root -- a separate repository carrying the
same ``noni/`` layout, selected by passing its path as ``--repo``. The shape a
reader copies is a clone *nested inside* the project and git-ignored by it, named
on the command line by name alone: ``--repo .noni-state``, launched from the
project directory.

Every launcher the four writer suites had built its ``--repo`` from an absolute
``tmp_path``, so no test ever sent the relative form and the bug was invisible:
the old derivation joined the caller-relative ``--repo`` to the state path and
left the ``--repo`` component in the answer, so ``git -C <state> add --
st/noni/sessions/x.md`` named a path the state clone does not hold. Each of the
four writers exited 3 with its file written and uncommitted. No such helper
exists any more -- the writers build the name once with
:func:`noni._session_git.writer_name` -- which is why these tests hold: they pin
the fault the removed helper used to produce.

Issue #77 found the same blind spot in the *printed* path. A ``--no-commit`` run
named the file by its state-root-relative path while the committed run named it
by the path from the caller's cwd, so on Route B the uncommitted line read as a
stray ``noni/`` having appeared beside the project. The last tests here run each
session writer twice with one relative ``--repo`` -- once committed, once with
``--no-commit`` -- and require both lines to carry the same path token. The
direction writers (order, intent, decide) have no session file to build, so
``tests/test_writer_path_form.py`` covers them.

One module holds all four verbs rather than one test in each suite, because the
property is the shared primitive's and every launcher in it is the same
``run_from(cwd, script, ...)``. The per-verb assertions differ only in what the
writer prints, which is the point of AC6: a fix that corrected the pathspec but
not the message (register derives its message path separately from the path it
stages) fails here and passes an exit-code-only test.

Each run plants a committed decoy at the doubled path, so admitting that path
into the commit is a name-set failure rather than a silent success.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, _git_ok, run_from
from session_git_support import (
    _PATH,
    STATE_DIR,
    _committed_names,
    _nested_state,
    _strip_identity,
)

# One session id per verb's fixture; no writer in this file reuses another's tree.
SID = "2026-10-01-cccccc"

# The single path every commit in here must consist of, and the doubled spelling
# that must never appear in it or in any message.
REL = f"noni/sessions/{SID}.md"
DOUBLED = f"{STATE_DIR}/noni/sessions/{SID}.md"

# The token a Route B caller must be handed on both routes: the session file as
# reached from the project directory, ``--repo`` component included (issue #77).
# Only writers addressed by an id carry it -- close, release and claim name the
# one session this file's fixture commits; register mints a fresh id per run and
# its own pair is checked for the same *form* instead.
TOKEN = DOUBLED


def _refused_run(cwd: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer from ``cwd`` with no committer identity, so git refuses the commit.

    The refusal the writer suites already use: it leaves the run's own path
    handling as the only variable being measured, and it is the honest state (a
    state repository prepared on a machine that never configured a committer).
    """
    return run_from(cwd, script, *args, identity=False,
                    env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})


def _assert_names_the_repo_relative_path(err: str) -> None:
    """The wording half of AC2/AC6: ``noni/sessions/<sid>.md`` and nothing else.

    ``DOUBLED`` is the string a path built by joining the caller-cwd-relative
    ``--repo`` to the state path produces, so its absence is what distinguishes a
    corrected derivation from a corrected pathspec with the message left behind.
    """
    assert DOUBLED not in err, (
        f"a path built by joining the relative --repo to the state path reached "
        f"the wording: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a path whose commit was refused was classified as a missing upstream: {err}"
    )


def _assert_clone_clean(state: Path) -> None:
    """AC4: a writer that finished left no dirty or staged path behind."""
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == [], (
        "a completed run left the state clone dirty"
    )


def _one_line(stdout: str, label: str) -> str:
    """The single output line carrying ``label``, or the failure that says so.

    Exactly one match is a precondition of every path comparison below: two lines
    would make it ambiguous which one agreed, and none would make the assertion
    vacuous.
    """
    matching = [row for row in stdout.splitlines() if label in row]
    assert len(matching) == 1, f"expected one {label!r} line, got {matching}"
    return matching[0]


def _run_ok(cwd: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer launched from ``cwd``, whose exit code has to be 0.

    ``--repo`` is handed over exactly as a Route B reader types it -- a bare
    directory name -- so the pair of runs one test builds differ by the
    ``--no-commit`` flag and nothing else.
    """
    proc = run_from(cwd, script, *args)
    assert proc.returncode == 0, (f"{script.name} {args}: {proc.returncode}"
                                  f"\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    return proc


def _assert_named_on_both_routes(label: str, committed: str, uncommitted: str,
                                 same_file: bool = True) -> None:
    """Both lines name the path as spelled from the caller's cwd.

    The token is ``--repo`` joined to the path under the state root, which is the
    string that actually locates the file in the directory the command ran in. It
    is compared exactly rather than by substring: the bare state-root-relative
    spelling that one route used to print satisfies a ``in`` test for nothing, and
    a line that printed the absolute machine path (the other form this bug took)
    fails it too, because the token would carry the tmp_path prefix.

    ``same_file`` says whether the two runs addressed one path. Three writers are
    addressed by an id, so both runs name the caller's own session and the two
    tokens must be equal; register mints a fresh id per run, and its pair is
    compared for the same *form* under the directory rather than the same name.
    """
    committed_token = _path_token(committed)
    uncommitted_token = _path_token(uncommitted)
    prefix = f"{STATE_DIR}/noni/sessions/"
    assert committed_token.startswith(prefix), (
        f"the committed {label} line names {committed_token!r}, not a path under "
        f"the --repo the caller typed: {committed}")
    assert uncommitted_token.startswith(prefix), (
        f"the --no-commit {label} line names {uncommitted_token!r}, which a Route "
        f"B reader reads as a noni/ beside the project: {uncommitted}")
    if not same_file:
        # Same directory, same depth, one file name inside it: what may not vary
        # between the two lines is the shape of the answer, only the id.
        assert "/" not in uncommitted_token[len(prefix):], uncommitted_token
        assert committed_token.count("/") == uncommitted_token.count("/") == 3, (
            committed_token, uncommitted_token)
        return
    assert committed_token == uncommitted_token, (
        f"the two {label} lines name the same file differently: "
        f"{committed_token!r} vs {uncommitted_token!r}")


def _path_token(line: str) -> str:
    """The whitespace-delimited path inside one printed line.

    Exactly one token of a line may look like a path under the state root; a line
    carrying none (or a second one) says the writer's wording changed, and the
    comparison would have been made against the wrong word.
    """
    candidates = [word.rstrip(".;,") for word in line.split() if "/" in word]
    named = [word for word in candidates if word.endswith(".md")]
    assert len(named) == 1, f"expected one path in {line!r}, found {named}"
    return named[0]


# --- register ---------------------------------------------------------------


def test_register_commits_the_session_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the register lands
    in the clone, and the commit is exactly the one repo-relative path."""
    project, state, _session = _nested_state(tmp_path, SID, name="register-relative")

    proc = run_from(project, REGISTER, "--repo", STATE_DIR, "--identity", "developer")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    sid = proc.stdout.split("registered session ")[1].split(" ->")[0].strip()
    committed = _git_ok(state, "show", f"HEAD:noni/sessions/{sid}.md").stdout
    assert "- identity: developer" in committed, committed
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"register: {sid}"
    # Exactly one path, and it carries no --repo component: the decoy the fixture
    # committed at the doubled path stayed out of this commit.
    assert _committed_names(state) == [f"noni/sessions/{sid}.md"], (
        "the commit moved paths other than the one register file"
    )
    _assert_clone_clean(state)
    # The marker belongs to the state clone, not to the cwd the run started in.
    assert (state / ".git" / "noni-session").is_file()


def test_register_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo register names ``noni/sessions/<sid>.md``
    in its headline *and* its hint, never the doubled path.

    register.py is the verb that computed its message path separately from the
    path it staged, so this is the case an exit-code-only test cannot see.
    """
    project, state, _session = _nested_state(tmp_path, SID, name="register-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, REGISTER, "--repo", STATE_DIR, "--identity", "developer")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    # The id this run allocated, read out of the wording so the assertion cannot
    # drift from the run that produced it.
    sid = err.split("git could not commit noni/sessions/")[1].split(".md")[0]
    assert f"git could not commit noni/sessions/{sid}.md (the file is written)" in err, err
    assert f"commit noni/sessions/{sid}.md by hand" in err, err
    assert DOUBLED not in err, err
    assert "no upstream configured" not in err, err
    # AC4: the file is on disk, and the clone holds no commit this run made.
    assert (state / "noni" / "sessions" / f"{sid}.md").is_file()
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


# --- claim ------------------------------------------------------------------


def test_claim_commits_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the row lands in
    the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="claim-relative")

    proc = run_from(project, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                    "--task", "#42")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #42" in session.read_text(encoding="utf-8"), "the row is not on disk"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- claim: #42" in committed, "the row is not in the commit"
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "claim: #42"
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    _assert_clone_clean(state)


def test_claim_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo claim names ``noni/sessions/<sid>.md``
    in the wording it owes, ``( <rel>, which this run staged)``, never the doubled
    path, and does not call a refused commit a missing upstream."""
    project, state, session = _nested_state(tmp_path, SID, name="claim-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#42")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"(noni/sessions/{SID}.md, which this run staged)" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4: the row is on disk, and the clone holds no commit this run made.
    assert "- claim: #42" in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


# --- close ------------------------------------------------------------------


def test_close_commits_the_session_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the status line
    moves in the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="close-relative")

    proc = run_from(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"close: {SID}"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- status: closed" in committed, committed
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    # The decoy at the doubled path is still the fixture's own commit, unmoved.
    assert _git_ok(state, "show", f"HEAD:{DOUBLED}").stdout == \
        "decoy at the doubled path\n"
    _assert_clone_clean(state)


def test_close_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo close names ``noni/sessions/<sid>.md``
    in both its headline and its hint, never the doubled path, and the cause is
    not an unrelated upstream clause."""
    project, state, session = _nested_state(tmp_path, SID, name="close-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit noni/sessions/{SID}.md" in err, err
    assert f"commit noni/sessions/{SID}.md by hand" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4 (the #57 writer-honesty contract): the file is written and exactly one
    # path is staged, so a later `git add -A` cannot sweep anything else in.
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
    assert [row for row in _git_ok(state, "status", "--porcelain").stdout.splitlines()
            if "noni/" in row] == [f"M  {REL}"]


# --- release ----------------------------------------------------------------


def test_release_removes_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the row is gone in
    the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="release-relative")

    proc = run_from(project, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                    "--task", "#1")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #1" not in session.read_text(encoding="utf-8"), "row still on disk"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- claim: #1" not in committed, "the row is still in the commit"
    assert "- claim: #2" in committed, "the writer released a row nobody named"
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "release: #1"
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    _assert_clone_clean(state)


def test_release_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo release names ``noni/sessions/<sid>.md``
    in its headline and its hint, never the doubled path, and does not blame a
    missing upstream for a commit git refused."""
    project, state, session = _nested_state(tmp_path, SID, name="release-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#1")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit noni/sessions/{SID}.md" in err, err
    assert f"commit noni/sessions/{SID}.md by hand" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4: the row is removed on disk, and nothing landed in the clone.
    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


# --- the printed path token, committed and uncommitted (issue #77, AC2) ------
#
# One relative --repo, one writer, two runs: the flag flipped is the only
# difference, so the two lines the writer prints are the pair the pilot read as
# two different files. Each pair runs in its own fixture tree, because these
# writers are not idempotent across the pair: a close that landed leaves nothing
# for the second close to name, and release removes the row it would ask for.


def test_register_prints_the_same_path_token_committed_and_uncommitted(tmp_path):
    """``registered session <id> -> <path>`` and ``<path> left uncommitted`` agree.

    register mints a fresh id per run, so the two runs name two files; what has
    to agree is the form, and that neither line ever drops the ``--repo``
    component the bug dropped on one of the two routes.
    """
    project, _state, _session = _nested_state(tmp_path, SID, name="token-register")
    committed = _run_ok(project, REGISTER, "--repo", STATE_DIR, "--identity",
                        "developer")
    uncommitted = _run_ok(project, REGISTER, "--repo", STATE_DIR, "--identity",
                          "reviewer", "--no-commit")

    committed_line = _one_line(committed.stdout, "->")
    uncommitted_line = _one_line(uncommitted.stdout, "left uncommitted")
    _assert_named_on_both_routes("register", committed_line, uncommitted_line,
                                 same_file=False)


def test_close_prints_the_same_path_token_committed_and_uncommitted(tmp_path):
    """``closed session <id> in <path>`` and ``<path> left uncommitted`` agree."""
    project_a, _state_a, _a = _nested_state(tmp_path, SID, name="token-close-committed")
    project_b, _state_b, _b = _nested_state(tmp_path, SID, name="token-close-uncommitted")

    committed = _run_ok(project_a, CLOSE, "--repo", STATE_DIR, "--session-id", SID)
    uncommitted = _run_ok(project_b, CLOSE, "--repo", STATE_DIR, "--session-id", SID,
                          "--no-commit")
    _assert_named_on_both_routes(
        "close",
        _one_line(committed.stdout, "closed session"),
        _one_line(uncommitted.stdout, "left uncommitted"))


def test_release_prints_the_same_path_token_committed_and_uncommitted(tmp_path):
    """``released <task> from <path>`` and ``<path> left uncommitted`` agree."""
    project_a, _state_a, _a = _nested_state(tmp_path, SID, name="token-rel-committed")
    project_b, _state_b, _b = _nested_state(tmp_path, SID, name="token-rel-uncommitted")

    committed = _run_ok(project_a, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#1")
    uncommitted = _run_ok(project_b, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                          "--task", "#1", "--no-commit")
    _assert_named_on_both_routes(
        "release",
        _one_line(committed.stdout, "released"),
        _one_line(uncommitted.stdout, "left uncommitted"))


def test_claim_prints_the_same_path_token_committed_and_uncommitted(tmp_path):
    """``committed claim <task> in <path>`` and ``appended ... to <path>`` agree.

    The shape that differed between the two lines (a bare id on one, a path on
    the other) is exactly what AC2 forbids, and what the pilot read as a second
    ``noni/`` tree beside the project.
    """
    project_a, _state_a, _a = _nested_state(tmp_path, SID, name="token-claim-committed")
    project_b, _state_b, _b = _nested_state(tmp_path, SID, name="token-claim-uncommitted")

    committed = _run_ok(project_a, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#42")
    uncommitted = _run_ok(project_b, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                          "--task", "#7", "--no-commit")
    _assert_named_on_both_routes(
        "claim",
        _one_line(committed.stdout, "committed claim"),
        _one_line(uncommitted.stdout, "left uncommitted"))
