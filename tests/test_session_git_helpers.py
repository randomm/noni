"""``_session_git``'s hardened git call, atomic write, and the helper surface.

Four ``-c`` overrides, a timeout, and an environment the child is not handed the
host's git location in: each is invisible to a behavioural test on an ordinary
fixture repo (no hooks, no signing requirement, no fsmonitor helper to be bitten
by), so it is pinned where it is implemented. Same for ``atomic_write`` — a crash
mid-write must leave the previous bytes, never a truncated file — and for the
small helpers the writers compose: the terminal-status copy that must not drift
from the census's two copies, ``valid_token``, ``safe_text``.

The commit primitive's own path guard is here too, on the one shape its two
narrow questions cannot see: a link at ``noni``, above both the session file and
its directory.

The behavioural proof for the child environment lives in
``tests/test_writer_git_env.py``; this pins the same property one level down, so a
helper that dropped its ``env=`` fails here even before a writer is run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from _harness import _git_env_with_identity, _git_ok
from session_git_support import _repo

from noni import _session_git, census_sessions_checks, gitenv
from noni import census as census_mod


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Pin a git identity for this file's real commits.

    The suite's autouse conftest clears ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*``
    so a host identity cannot reach a test — which also means the in-process
    helper calls below would have git refuse every commit for want of one. The
    subprocess launchers pin their own (``run_claim``, ``run_close``,
    ``run_register``); these tests drive the helpers directly, so they pin it
    the same way from the same table, and block the host gitconfig the same way
    those launchers do.
    """
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)


# --- the hardened call -------------------------------------------------------


def test_the_git_helper_is_bounded_hardened_and_makes_no_signing_promise():
    """The four ``-c`` overrides and the timeout, tested where they live.

    A helper that silently dropped one would still pass every behavioural test,
    because an ordinary fixture repo has no hooks, no signing requirement and
    no fsmonitor helper to be bitten by."""
    seen: list[list[str]] = []
    bounds: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        bounds.append(dict(kwargs))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    proc = _session_git.git(Path("/nonexistent-repo"), "status", "--porcelain",
                            _run=spy)
    assert proc.returncode == 0
    assert len(seen) == 1, seen
    cmd = seen[0]
    assert cmd[:3] == ["git", "-C", "/nonexistent-repo"], cmd
    joined = " ".join(cmd)
    for hardening in ("-c commit.gpgsign=false", f"-c core.hooksPath={os.devnull}",
                      "-c protocol.ext.allow=never", "-c core.fsmonitor=false"):
        assert hardening in joined, f"{hardening} missing from {joined}"
    assert cmd[-2:] == ["status", "--porcelain"], cmd
    assert bounds[0].get("timeout") == _session_git.GIT_TIMEOUT, bounds[0]


def test_the_git_helper_hands_its_child_no_git_location_variables(monkeypatch):
    """The environment the helper passes, tested where the call is made.

    The behavioural proof is in ``tests/test_writer_git_env.py``; this pins the
    same property one level down, so a helper that dropped its ``env=`` fails
    here even before a writer is run. The location variables are the ones that
    relocate the child away from the ``-C`` path; the identity variables are not
    touched, because a commit made without them is a commit that fails.
    """
    seen: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    for name in gitenv.GIT_LOCATION_VARS:
        monkeypatch.setenv(name, "/hostile/" + name.lower())
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Replay")

    _session_git.git(Path("/nonexistent-repo"), "status", "--porcelain", _run=spy)

    assert len(seen) == 1, seen
    env = seen[0]
    for name in gitenv.GIT_LOCATION_VARS:
        assert name not in env, f"{name} reached the child: {env.get(name)!r}"
    assert env.get("GIT_AUTHOR_NAME") == "Replay", (
        "child_env removed a variable the commit needed: "
        "the identity must travel to the child"
    )


def test_a_hung_git_call_reports_the_timeout_code(tmp_path):
    """The helper converts its own timeout instead of raising, so every caller
    classifies a killed call the same way rather than ending in a traceback."""
    def hang(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 60))

    proc = _session_git.git(tmp_path, "push", "origin", "main", _run=hang)
    assert proc.returncode == _session_git.GIT_TIMEOUT_RC != 0
    assert "timed out" in proc.stderr
    assert "push" in proc.stderr, "the message names which git call hung"


# --- atomic_write ------------------------------------------------------------


def test_atomic_write_leaves_the_old_bytes_when_the_write_fails(tmp_path, monkeypatch):
    """A crash mid-write leaves the previous file, never a truncated one, and no
    temp file is left beside it. This is why the writers do not call open()."""
    target = tmp_path / "s.md"
    target.write_text("original\n", encoding="utf-8")
    real_replace = os.replace

    def exploding_replace(src, dst, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", exploding_replace)
    with pytest.raises(OSError):
        _session_git.atomic_write(target, "replacement\n")
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text(encoding="utf-8") == "original\n"
    # No temp file is left beside it. Scoped to the temp names the helper uses,
    # because the suite's own isolation home also lives in tmp_path.
    assert [p.name for p in tmp_path.iterdir()
            if p.name.startswith(".s.md")] == [], list(tmp_path.iterdir())


def test_atomic_write_gives_a_new_file_the_mode_the_umask_allows(tmp_path):
    """mkstemp's 0600 must not survive: a session file the census cannot read is
    a broken register. An existing file keeps its own mode."""
    target = tmp_path / "new.md"
    _session_git.atomic_write(target, "text\n")
    assert _session_git.file_mode(target) == os.stat(target).st_mode & 0o777
    assert oct(os.stat(target).st_mode & 0o777) == oct(_session_git.file_mode(target))

    target.chmod(0o600)
    _session_git.atomic_write(target, "text again\n")
    assert oct(os.stat(target).st_mode & 0o777) == "0o600"


# --- the commit primitive's path guard ---------------------------------------


def test_stage_and_commit_refuses_a_link_at_noni_above_the_session(tmp_path):
    """The one guard the primitive owns that a caller cannot skip, on the shape the
    two narrow questions cannot see.

    ``stage_and_commit`` lstat's the session file and its directory so a caller that
    ran no check of its own cannot drive a link through the primitive. Neither of
    those answers sees a link standing at ``noni``, the directory above both: a
    plain ``lstat`` resolves every intermediate component, so the sessions directory
    and the file under it still answer "directory" and "regular file". Without the
    walk up to the state root, git -- not noni -- would be what objected ("beyond a
    symbolic link", on a code no page documents) after the bytes had landed outside
    the clone.
    """
    repo = _repo(tmp_path)
    (repo / "noni" / "sessions").mkdir(parents=True)
    (repo / "noni" / "sessions" / "tracked.md").write_text("- status: active\n",
                                                            encoding="utf-8")
    target = tmp_path / "outside-tree"
    target.mkdir()
    os.replace(repo / "noni" / "sessions", target / "sessions")
    (repo / "noni").rmdir()
    (repo / "noni").symlink_to(target)
    head_before = _git_ok(repo, "rev-parse", "HEAD").stdout.strip()

    ok, why = _session_git.stage_and_commit(repo, "noni/sessions/tracked.md", "nope")

    assert ok is False, why
    assert "symlink" in why, why
    assert str(repo / "noni") in why, "the refusal names the linked directory"
    assert "fatal:" not in why.lower(), f"git's error, not noni's: {why}"
    assert (repo / "noni").is_symlink(), "the primitive replaced the tree link"
    assert (target / "sessions" / "tracked.md").read_text(
        encoding="utf-8") == "- status: active\n", "the primitive wrote through it"
    assert _git_ok(repo, "rev-parse", "HEAD").stdout.strip() == head_before


# --- terminal statuses: the copy that must not drift -------------------------


def test_terminal_statuses_equal_the_census_inactive_sets():
    """This module holds a copy of the set, not an import (it must not depend on
    the census, and the census must not depend on it). The census owns the same
    answer twice over, and all three must agree: a status added on one side
    without the others is this test's failure, and the bug it catches is a
    closed session still counted in the double-claim check."""
    assert _session_git.TERMINAL_STATUSES == frozenset(
        census_sessions_checks._constants().INACTIVE_STATUSES)
    assert _session_git.TERMINAL_STATUSES == frozenset(census_mod.INACTIVE_STATUSES)


def test_is_terminal_status_ignores_surrounding_space_and_case():
    """The field is read from a hand-editable file, so ' Closed ' and 'CLOSED'
    name the same ended session as 'closed'."""
    for spelling in ("closed", "  closed  ", "CLOSED", "Closed", "\tclosed\n"):
        assert _session_git.is_terminal_status(spelling), spelling
    for live in ("active", "", "   ", "open", "claimed"):
        assert not _session_git.is_terminal_status(live), live


# --- token validation --------------------------------------------------------


def test_valid_token_admits_one_clean_token_and_refuses_the_rest():
    """A token goes into a commit message and a file path, so whitespace and a
    separator are refused before either is reached. fullmatch, not match: a
    trailing newline must not sneak through ('$' matches before one)."""
    for good in ("developer", "reviewer", "#42", "2026-10-01-aaaaaa", "closed"):
        assert _session_git.valid_token(good), good
    for bad in ("", " ", "a b", "a/b", "a\\b", "a\n", "\nactive", "a b\n"):
        assert not _session_git.valid_token(bad), repr(bad)


# --- safe_text ---------------------------------------------------------------


def test_safe_text_strips_control_bytes_and_bounds_the_tail():
    """git's output can carry remote-side or credential-helper text, and an
    agent pipes it straight into tool output. Control bytes other than newline
    and space are dropped (no ANSI or OSC sequence reaches the terminal) and the
    tail past the limit is dropped with a marker."""
    noisy = "ok\x1b[2J\x07 done"
    cleaned = _session_git.safe_text(noisy)
    assert "\x1b" not in cleaned and "\x07" not in cleaned
    assert "ok" in cleaned and "done" in cleaned

    long = _session_git.safe_text("x" * (_session_git.GIT_OUTPUT_LIMIT + 50))
    assert long.endswith("... [truncated]")
    assert len(long) == _session_git.GIT_OUTPUT_LIMIT + len("... [truncated]")
