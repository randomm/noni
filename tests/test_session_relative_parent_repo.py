"""Every writer run from *inside* a nested directory with ``--repo ..`` (issue #66).

The other relative-repo suites name the state root as ``st`` from the project
directory: the ``--repo`` there is a downward step, and a derivation that read a
path against the process working directory could still land on the right file by
accident. This file turns the arrow around. The run is launched from
``<project>/deep`` and the state root is named as ``../st`` -- a ``--repo``
whose every component points up, the shape that breaks a cwd-reading derivation
rather than merely doubling it.

The property is one sentence and it is the state-root contract of
docs/PRODUCT.md 7: ``--repo`` names the target repository, whatever the cwd. Each
verb gets one test because each verb's own success path is what has to reach the
commit primitive (register writes a file it must first allocate; claim appends a
row; close moves the status line; release removes one), and each asserts the same
three things about the run:

* it exited 0 and the state clone holds the commit it made;
* ``git -C <state> diff --name-only HEAD~1 HEAD`` is *exactly* the one
  repo-relative path the writer owns, so a doubled pathspec (which would commit
  the decoy the fixture planted at ``st/noni/sessions/<sid>.md``) and a whole-tree
  commit both fail here;
* the nested directory the run started in is byte-for-byte what it was, so
  nothing was resolved against the cwd.

The cwd is itself a git repository holding one committed file. That is what makes
the third assertion bite: a writer that resolved its path against the cwd would
have found a real tree to write into and a real HEAD to move, so the assertions
read both trees rather than trusting the exit code of the one that was meant to
change.
"""

from __future__ import annotations

from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, _git_ok, _tree_bytes, run_from
from session_git_support import STATE_DIR, _nested_state

SID = "2026-10-01-cccccc"
# The state root as a run from ``<project>/deep`` names it. The launcher stands
# one directory inside the project and names the clone beside it as ``../st``, so
# every component of the ``--repo`` points up: the form a derivation that reads a
# path against the cwd cannot survive.
PARENT_REPO = f"../{STATE_DIR}"
DEEP = Path("deep")

# One entry per verb: the launcher's extra argv, the commit subject the writer
# owes, and a callable answering "did your change land in these committed bytes?"
# against the path the run owns. Each predicate is the verb's own contract rather
# than the exit code, because an exit 0 with the decoy in the commit is exactly
# the fault this file exists to catch.
VERBS = (
    (REGISTER, ("--identity", "developer"), "register:", "active"),
    (CLAIM, ("--session-id", SID, "--task", "#42"), "claim:", "claim: #42"),
    (CLOSE, ("--session-id", SID), "close:", "status: closed"),
    (RELEASE, ("--session-id", SID, "--task", "#1"), "release:", "no claim #1"),
)


def _lands(kind: str, committed: str) -> bool:
    """Whether the verb's own change is in the committed bytes of its own file."""
    if kind == "active":
        return "- identity: developer" in committed
    if kind == "claim: #42":
        return "- claim: #42" in committed
    if kind == "status: closed":
        return "- status: closed" in committed
    return "- claim: #1" not in committed and "- claim: #2" in committed


def _session_name_of(stdout: str, script: Path) -> tuple[str, str]:
    """``(the repo-relative session path, the subject of the commit owning it)``.

    claim, close and release take ``--session-id``, so their file is the one the
    fixture committed and the doubled spelling of it is the decoy commit. register
    allocates an id of its own, so its name is read out of its own line and the
    doubled spelling names a path the fixture never created -- which is its own
    witness that a pathspec carrying the ``--repo`` component was never staged.
    """
    if script is REGISTER:
        sid = stdout.strip().split("registered session ")[1].split(" ->")[0].strip()
        return f"noni/sessions/{sid}.md", "register:"
    return f"noni/sessions/{SID}.md", "decoy:"


# The files of the cwd tree a writer could have put there, and so the only ones
# the "left untouched" assertion measures. The launcher runs the child with
# COVERAGE_PROCESS_START set, so a coverage data file appears beside the cwd on
# every run and is not the product's doing; ``.git/`` is the fixture's own
# repository, whose HEAD the assertions below check directly.
_CWD_PLANTED = {"untouched.md": b"cwd file\n", ".gitignore": b"noni/\n.coverage*\n"}


def _cwd_snapshot(deep: Path) -> dict[str, bytes]:
    """The cwd tree restricted to what a noni writer could have written there."""
    return {name: data for name, data in _tree_bytes(deep).items()
            if name in _CWD_PLANTED or not name.startswith((".coverage", ".git/"))}


def _assert_nested_clone_untouched(project: Path) -> None:
    """The cwd the run started in holds exactly what the fixture put there."""
    assert _cwd_snapshot(project / DEEP) == _CWD_PLANTED, (
        "a run launched from a nested directory wrote beside its cwd"
    )


def test_each_writer_commits_the_named_repo_from_a_nested_directory(tmp_path):
    """AC1/AC7 with ``--repo ..``: one commit, one path, in the repo ``--repo`` named."""
    for index, (script, extra, subject, kind) in enumerate(VERBS):
        case = tmp_path / f"case-{index}"
        case.mkdir()
        project, state, _session = _nested_state(case, SID, name=f"project-{index}",
                                                 nested=True)
        deep = project / DEEP
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        # The cwd tree as git sees it too: HEAD, and the index and work-tree
        # state. The .gitignore the fixture committed hides the ``noni/`` a stray
        # write would create (and coverage's own data files), so porcelain alone
        # is not the witness -- HEAD is what a stray commit here would move.
        cwd_head_before = _git_ok(deep, "rev-parse", "HEAD").stdout.strip()
        cwd_porcelain_before = _git_ok(deep, "status", "--porcelain").stdout
        cwd_before = _cwd_snapshot(deep)

        proc = run_from(deep, script, "--repo", PARENT_REPO, *extra)

        assert proc.returncode == 0, f"{script.name}: {proc.returncode}: {proc.stderr}"
        rel, owner = _session_name_of(proc.stdout, script)
        # The commit landed in the repo --repo named, and it is exactly one path:
        # neither the decoy at the doubled path nor a whole-tree commit passes.
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() != head_before, (
            f"{script.name}: no commit reached the state root --repo named"
        )
        assert _git_ok(state, "diff", "--name-only", "HEAD~1", "HEAD").stdout.split() \
            == [rel], f"{script.name}: the commit is not exactly {rel}"
        # A completed run's index equals HEAD, so the staged set is empty: the
        # doubled name the fixture committed is what a doubled pathspec would have
        # left behind in it, and an absolute one -- which ``git add`` accepts from
        # outside the -C tree, exits 0 and stages nothing -- would have left the
        # run reporting a commit that carried nobody's file.
        assert _git_ok(state, "diff", "--cached", "--name-only").stdout.split() == [], (
            f"{script.name}: a completed run left a path staged")
        assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() \
            .startswith(subject), f"{script.name}: {proc.stdout}"
        committed = _git_ok(state, "show", f"HEAD:{rel}").stdout
        assert _lands(kind, committed), f"{script.name}: {committed}"
        # The doubled spelling of this run's path is the fixture's own decoy and
        # nothing this run did: the fixture committed it, so a run that handed git
        # the doubled string would have moved it or been refused. For register the
        # doubled spelling names no path at all, so a run that staged one would
        # have left it in the clone.
        doubled = f"{STATE_DIR}/{rel}"
        if owner == "decoy:":
            assert _git_ok(state, "log", "-1", "--format=%s", "--", doubled) \
                .stdout.strip().startswith("decoy"), f"{script.name}: the decoy moved"
            assert _git_ok(state, "show", f"HEAD:{doubled}").stdout == \
                "decoy at the doubled path\n", f"{script.name}: the decoy's bytes"
        else:
            assert _git_ok(state, "ls-files", doubled).stdout == "", (
                f"{script.name}: {doubled} was staged by a doubled pathspec")
        assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == [], (
            f"{script.name}: a completed run left the state clone dirty"
        )
        # And the directory the run stood in is the fixture's, byte for byte:
        # no file written beside it, no index entry, and no commit it made.
        assert _cwd_snapshot(deep) == cwd_before, f"{script.name}: the cwd tree changed"
        assert _git_ok(deep, "status", "--porcelain").stdout == cwd_porcelain_before, (
            f"{script.name}: the cwd tree carries a change this run made"
        )
        assert _git_ok(deep, "rev-parse", "HEAD").stdout.strip() == cwd_head_before, (
            f"{script.name}: the cwd repository took a commit this run made"
        )
        _assert_nested_clone_untouched(project)
