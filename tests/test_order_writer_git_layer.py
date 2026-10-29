"""The git layer of order.py: what gets committed, and with what identity.

Extracted from the order writer suite: the commit's single path, the pinned
author and date, and the refusals that keep history linear."""

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path

from _harness import (
    _git_e2,
    _order_module,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    _entry,
    _git_verb,
    _gitwrite_module,
    _issues,
    _order,
    _repo,
    _seed,
    _spied_git,
    _writer_git_call,
)


def test_a_failing_commit_is_exit_three_and_leaves_the_file_written(tmp_path):
    """The file is written and named, never claimed as committed: the caller
    fixes git and re-runs, and the message says which of the two steps failed."""
    repo = _repo(tmp_path)
    _git_e2(repo, "config", "--unset", "user.name")
    _git_e2(repo, "config", "--unset", "user.email")
    env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": str(tmp_path / "no-home"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW, env=env)
    assert proc.returncode == 3, proc.stderr
    assert "commit failed" in proc.stderr, proc.stderr
    assert _issues(repo) == [7], "the artifact is written even when git refused"


def test_a_git_call_that_times_out_is_never_read_as_a_clean_answer(tmp_path, monkeypatch):
    """A git call that hangs reports the timeout code, which is no answer: the
    run stops at exit 3 and says which call hung, rather than committing an
    order whose commit nobody saw land."""
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"))

    helper = _gitwrite_module()

    def hung(repo_arg, *args, **kwargs):
        # What the writer's own helper hands back for a call that cannot
        # finish: a return code no caller may read as a clean answer.
        return subprocess.CompletedProcess(["git", *args], helper.GIT_TIMEOUT_RC,
                                           "", "git timed out")

    monkeypatch.setattr(module.gitwrite, "git", hung)
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "confirm", "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "timed out" in err.getvalue(), err.getvalue()
    assert str(_gitwrite_module().GIT_TIMEOUT) in err.getvalue(), err.getvalue()


def test_every_git_call_disables_hooks_signing_and_external_transports(tmp_path, monkeypatch):
    """No hook, no signing, no external transport, and no hang: the writer must
    not be able to wedge itself or run the tree's own scripts on the operator's
    behalf. Global config is NOT neutralised: the commit is made under the
    tree's configured identity, like every other noni writer.

    The writer is driven in-process for this one: the product's git calls are
    the only ones the spy can see, and a subprocess run would put them behind a
    process boundary the spy cannot cross.
    """
    seen: list[list[str]] = []
    module = _order_module()
    real_run = subprocess.run

    repo = _repo(tmp_path)
    # The spy lives on the helper's own module object, which is the shared
    # package module the writer resolves through, so the product's git calls are
    # the ones this spy sees. monkeypatch restores the helper's own call after.
    monkeypatch.setattr(module.gitwrite, "git", _spied_git(real_run, seen))
    with contextlib.redirect_stdout(io.StringIO()):
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == 0, code
    own = [c for c in seen if _writer_git_call(c, repo)]
    assert own, f"the writer made no git call of its own: {seen}"
    for cmd in own:
        joined = " ".join(cmd)
        assert "-c commit.gpgsign=false" in joined, joined
        assert f"-c core.hooksPath={os.devnull}" in joined, joined
        assert "-c protocol.ext.allow=never" in joined, joined
        assert "-c core.fsmonitor=false" in joined, joined
        assert cmd[2] == str(repo)


def test_a_run_that_renders_nothing_writable_fails_as_io(tmp_path, monkeypatch):
    """The atomic write itself is an environment fault, not a refusal of the
    order: when the directory cannot hold a temp file the run says the file
    could not be written (exit 3) and leaves the artifact it read alone."""
    module = _order_module()

    def refuse(path, payload):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(module.gitwrite, "write_atomic", refuse)
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = (repo / ORDER_REL).read_bytes()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "could not be written" in err.getvalue(), err.getvalue()
    raw = (repo / ORDER_REL).read_bytes()
    assert raw == before, "a failed write must leave the artifact as it was"


def test_a_file_where_the_direction_directory_belongs_is_a_fault(tmp_path):
    """The parent path is part of the artifact's identity: a plain file sitting
    at noni/direction is an environment fault (exit 3), not a refusal of the
    order and not something the writer works around by replacing it."""
    module = _order_module()
    repo = _repo(tmp_path)
    (repo / "noni" / "direction").write_text("not a directory\n", encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "is not a directory" in err.getvalue(), err.getvalue()
    assert (repo / "noni" / "direction").read_text(encoding="utf-8") == "not a directory\n"


def test_a_planned_order_that_cannot_be_rendered_is_refused(tmp_path, monkeypatch):
    """The writer renders its own plan, and a plan it cannot render is a refusal
    that leaves the artifact alone: the path is unreachable in normal operation
    (every value is validated first), so it is exercised by making the renderer
    lie, and the contract under test is that no half-written order is committed."""
    module = _order_module()

    def lie(body):
        raise ValueError("cannot render")

    # The seam is the state module's renderer, because that is the one call
    # order.py's _render now makes: patching the schema's order_bytes on the
    # writer's own handle would miss it (orderstate holds its own), and a lying
    # renderer must be caught wherever the writer reaches it.
    monkeypatch.setattr(module.orderstate.orderschema, "order_bytes", lie)
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = (repo / ORDER_REL).read_bytes()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_REFUSAL, code
    assert "cannot be written as JSON" in err.getvalue(), err.getvalue()
    assert (repo / ORDER_REL).read_bytes() == before


def test_the_commit_names_only_the_written_path(tmp_path, monkeypatch):
    """The staged-set rule is in the command line itself: add and commit both
    carry `-- <path>`, and the commit carries --only."""
    seen: list[list[str]] = []
    module = _order_module()
    real_run = subprocess.run

    # Driven in-process through the writer's own git helper, so the calls the
    # spy sees are the writer's: the subprocess run would put them behind a
    # process boundary the spy cannot cross.
    repo = _repo(tmp_path)
    # The spy lives on the helper's own module object, which is the shared
    # package module the writer resolves through, so the product's git calls are
    # the ones this spy sees. monkeypatch restores the helper's own call after.
    monkeypatch.setattr(module.gitwrite, "git", _spied_git(real_run, seen))
    with contextlib.redirect_stdout(io.StringIO()):
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == 0, code
    own = [c for c in seen if _writer_git_call(c, repo)]
    assert own, f"the writer made no git call of its own: {seen}"
    adds = [c for c in own if _git_verb(c) == "add"]
    commits = [c for c in own if _git_verb(c) == "commit"]
    assert adds and commits, seen
    assert adds[0][-2:] == ["--", ORDER_REL], adds[0]
    assert "--only" in commits[0], commits[0]
    assert commits[0][-2:] == ["--", ORDER_REL], commits[0]
    # The subject the writer actually built is visible in the history: a
    # compound change stays one change, identifiable by its verb.
    subject = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert subject.startswith("direction: add 7 [") and subject.endswith("]"), subject
