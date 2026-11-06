"""The git layer of ``intent.py``: what gets committed, and what a fault leaves behind.

The writer commits, so its failure modes are the interesting ones: a git that
fails, a git that hangs, a directory that will not hold a temp file. Each is
driven in-process, because the product's git calls are the only ones a spy can
see and a subprocess puts them behind a boundary the spy cannot cross -- the same
reason the ordering writer's git layer is tested this way.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
from pathlib import Path

from _harness import _git
from harness_git import _git_env_with_identity
from intent_fixtures import INTENT_REL, NOW, RECORD_ID, repo_with_record
from parent_link_fixtures import (
    assert_outside_untouched,
    plant_parent_link,
    write_outside_decoy,
)


def _intent_module() -> object:
    """The writer as a module, for the tests that drive its internals.

    The package module under its real name, so a seam a test puts on it is the
    seam the console route resolves too -- which is what makes the assertions
    below about the product rather than about a copy of it.
    """
    from noni import intent

    return intent


def _identity(monkeypatch) -> None:
    """The deterministic commit identity, in the environment of this process.

    The writers commit under the identity they are given and the suite clears
    ``GIT_AUTHOR_*``/``GIT_COMMITTER_*`` from the environment for every test, so an
    in-process run needs the pin the subprocess launchers apply -- otherwise git
    answers the commit with 'Author identity unknown', which is exit 3 for a
    reason no test here is asserting.
    """
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)


def _set(repo, *extra: str) -> tuple[int, str, str]:
    """One in-process run of the writer's ``main`` against ``repo``."""
    module = _intent_module()
    argv = ["--repo", str(repo), "set", "--from", str(_draft(repo)),
            "--decision", RECORD_ID, "--now", NOW, *extra]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


def _draft(repo: Path) -> Path:
    draft = repo.parent / "git-layer-draft.md"
    draft.write_text(
        "# Intent\nLast-confirmed: 2026-10-01\n## Purpose\nShip the beta.\n"
        "## Principles\nPrefer the boring technology.\n## Never\nNever force push.\n"
        "## Ask first\nAnything that costs money.\n", encoding="utf-8")
    return draft


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _subjects(repo: Path) -> list[str]:
    body = _git(repo, "show", f"HEAD:{INTENT_REL}").stdout
    return [line for line in body.splitlines() if line.startswith("## ")]


def test_a_failing_commit_leaves_the_file_written_and_names_the_path(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """Exit 3, the file named, never claimed as committed.

    The whole value of the exit-code contract is in this row: a caller has to be
    able to tell 'written and staged' from 'committed', because a run that lied
    would leave the census reporting an intent that history does not hold.
    """
    module = _intent_module()
    real = module.gitwrite.git
    calls: list[tuple[str, ...]] = []

    def failing(repo_arg, *args):
        calls.append(tuple(args))
        if args[0] == "commit":
            return subprocess.CompletedProcess(list(args), 128, "", "index.lock exists")
        return real(repo_arg, *args)

    monkeypatch.setattr(module.gitwrite, "git", failing)
    repo = repo_with_record(tmp_path)
    code, out, err = _set(repo)
    assert code == 3, err
    assert "commit failed" in err, err
    assert INTENT_REL in err, err
    assert (repo / INTENT_REL).is_file(), "the file is written even when git refused"


def test_a_failing_add_reports_unstaged_and_writes_no_commit(tmp_path, monkeypatch):
    _identity(monkeypatch)
    module = _intent_module()
    real = module.gitwrite.git

    def failing(repo_arg, *args):
        if args[0] == "add":
            return subprocess.CompletedProcess(list(args), 128, "", "")
        return real(repo_arg, *args)

    monkeypatch.setattr(module.gitwrite, "git", failing)
    repo = repo_with_record(tmp_path)
    before = _head(repo)
    code, out, err = _set(repo)
    assert code == 3, err
    assert "unstaged" in err, err
    assert _head(repo) == before, "a failed add must not commit anything"


def test_a_git_call_that_times_out_is_never_read_as_a_clean_answer(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """The timeout code is no answer: the run stops at exit 3 and says which call
    hung, rather than reporting a commit nobody saw land."""
    module = _intent_module()
    helper = module.gitwrite

    def hung(repo_arg, *args):
        return subprocess.CompletedProcess(list(args), helper.GIT_TIMEOUT_RC, "",
                                           "git timed out")

    monkeypatch.setattr(module.gitwrite, "git", hung)
    repo = repo_with_record(tmp_path)
    code, out, err = _set(repo)
    assert code == 3, code
    assert "timed out" in err, err
    assert str(helper.GIT_TIMEOUT) in err, err


def test_a_commit_that_times_out_says_staged_and_not_committed(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """The two timeout messages differ on purpose: the caller's repair for a hung
    add is 'stage it', and for a hung commit it is 'check whether it landed'."""
    module = _intent_module()
    helper = module.gitwrite
    real = helper.git

    def hung_after_add(repo_arg, *args):
        if args[0] == "commit":
            return subprocess.CompletedProcess(list(args), helper.GIT_TIMEOUT_RC, "", "")
        return real(repo_arg, *args)

    monkeypatch.setattr(module.gitwrite, "git", hung_after_add)
    repo = repo_with_record(tmp_path)
    code, out, err = _set(repo)
    assert code == 3, code
    assert "staged, not committed" in err, err


def test_the_commit_stages_only_the_intent_path(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """`git add -- <path>` and `git commit --only -- <path>`: a file somebody else
    had staged is neither committed nor unstaged."""
    module = _intent_module()
    seen: list[list[str]] = []
    real = module.gitwrite.git

    def spy(repo_arg, *args):
        seen.append(list(args))
        return real(repo_arg, *args)

    monkeypatch.setattr(module.gitwrite, "git", spy)
    repo = repo_with_record(tmp_path)
    (repo / "other.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(repo, "add", "other.md")
    code, out, err = _set(repo)
    assert code == 0, err
    adds = [call for call in seen if call[0] == "add"]
    commits = [call for call in seen if call[0] == "commit"]
    assert adds and all(adds_[0:1] == ["add"] and adds_[-2:] == ["--", INTENT_REL]
                        for adds_ in adds), adds
    assert commits and "--only" in commits[0], commits
    assert "other.md" in _git(repo, "status", "--porcelain").stdout, (
        "the run unstaged a file it did not write")


def test_a_directory_that_refuses_the_write_is_exit_3(tmp_path, monkeypatch):
    _identity(monkeypatch)
    module = _intent_module()

    def refuse(path, payload):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(module.gitwrite, "write_atomic", refuse)
    repo = repo_with_record(tmp_path)
    code, out, err = _set(repo)
    assert code == 3, code
    assert "could not be written" in err, err
    assert not (repo / INTENT_REL).exists()


def test_an_unreadable_installed_file_is_exit_3_not_a_refusal(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """'I could not read the file I was about to compare against' is an
    environment fault; 'it is not an intent file' is the draft's fault."""
    repo = repo_with_record(tmp_path)
    target = repo / INTENT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("anything\n", encoding="utf-8")
    target.chmod(0o000)
    try:
        code, out, err = _set(repo)
    finally:
        target.chmod(0o644)
    assert code == 3, err
    assert "could not be read" in err, err


def test_the_direction_directory_being_a_file_is_refused_on_the_wrong_path_code(tmp_path,
                                                                                monkeypatch):
    """Something that is not a directory where the intent file belongs (issue #104).

    The old route reached this shape with ``exists()``/``is_dir()`` and answered the
    environment-fault code 3; docs/PRODUCT.md 7 now gives every wrong path each
    writer's own code, so this row pins BOTH halves of the move: the code is the
    writer's 2, and the sentence still says "is not a directory" rather than
    inventing a link that is not there. The sibling tests in
    ``test_intent_writer_set.py`` are the linked-parent half, where the sentence
    says "is a symlink".
    """
    _identity(monkeypatch)
    repo = repo_with_record(tmp_path)
    (repo / "noni" / "direction").write_text("not a directory\n", encoding="utf-8")
    code, out, err = _set(repo)
    assert code == 2, err
    assert "is not a directory" in err, err
    assert "noni/direction" in err, err
    assert "symlink" not in err.lower(), err


def test_a_symlinked_parent_is_refused_before_the_writer_reaches_git(tmp_path, monkeypatch):
    """The guard runs ahead of every git call this layer owns (issue #104).

    Driven in-process, where the spy can see the commands: a linked parent used to
    reach ``git add`` and come back with "beyond a symbolic link" at exit 3, after
    the bytes had already been written outside the tree. Now the run returns the
    writer's wrong-path 2 with no git call of any kind, which is what "before its
    first read, probe or mkdir" has to mean for this writer.
    """
    _identity(monkeypatch)
    module = _intent_module()
    real = module.gitwrite.git
    seen: list[tuple[str, ...]] = []

    def spy(repo_arg, *args):
        seen.append(tuple(args))
        return real(repo_arg, *args)

    monkeypatch.setattr(module.gitwrite, "git", spy)
    repo = repo_with_record(tmp_path)
    outside = tmp_path / "outside"
    plant_parent_link(repo, outside, "noni/direction")
    write_outside_decoy(outside, "noni/direction", "intent.md")

    code, out, err = _set(repo)

    assert code == 2, err
    assert "symlink" in err.lower(), err
    assert "noni/direction" in err, err
    assert seen == [], f"a refused run still reached git: {seen}"
    assert (repo / "noni" / "direction").is_symlink(), "the run unmade the planted link"
    assert_outside_untouched(outside, "noni/direction", "intent.md")


def test_the_committed_subject_is_the_citation_the_census_reads(tmp_path, monkeypatch):
    _identity(monkeypatch)
    """The subject line is the artifact's citation: a writer that changed its own
    wording would make every committed intent read as uncited."""
    repo = repo_with_record(tmp_path)
    code, out, err = _set(repo)
    assert code == 0, err
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == f"intent: {RECORD_ID}"
    assert _subjects(repo) == ["## Purpose", "## Principles", "## Never", "## Ask first"]


def test_no_commit_leaves_the_file_and_says_which_it_is(tmp_path, monkeypatch):
    _identity(monkeypatch)
    repo = repo_with_record(tmp_path)
    before = _head(repo)
    code, out, err = _set(repo, "--no-commit")
    assert code == 0, err
    assert "uncommitted" in out, out
    assert _head(repo) == before
    assert (repo / INTENT_REL).is_file()
