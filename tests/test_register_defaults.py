"""Register defaults must never publish machine-local values.

The register file is committed to a public repo (see the public-repo hygiene
rule in AGENTS.md), so a registration run without --worktree / --host must not
write an absolute path or the machine hostname into it. Explicit --worktree and
--host values are written as given.

The marker half of this file covers what a refusing commit does to the
working-copy marker: the tree is put back the way it was found, and when the
restore itself cannot land the operator is told rather than misled. The writer's
refusal, idempotency and field-parser paths are in ``test_register_refusals.py``.
"""

from __future__ import annotations

import socket

from _harness import _git_ok
from conftest import run_register
from register_refusal_fixtures import (
    _head,
    _hostworktree_value,
    _refused_register,
    _register_refusing_commit,
    _sid_of_any,
)

from noni import _marker


def test_a_refused_commit_leaves_no_marker_for_a_session_that_never_landed(tmp_path):
    """AC1 for register: a run whose commit git refused leaves the tree exactly as
    it found it, marker included.

    The marker is the evidence a later run reads to find this working copy's
    session, so a marker naming a file git never received would make the next
    register continue (or refuse to overwrite) a session that exists only as an
    uncommitted file -- the half-applied state this issue is about, one step
    further along. Three promises, asserted: the run says so with a cause in
    noni's words and a hint that names the path to commit by hand (and no raw
    ``git status --porcelain`` dump), HEAD did not move, and the marker this run
    created is gone.
    """
    repo, proc = _refused_register(tmp_path, "fresh")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    assert "git could not commit" in proc.stderr, proc.stderr
    assert "by hand" in proc.stderr and "register.py" in proc.stderr, proc.stderr
    assert "git status --porcelain" not in proc.stderr, proc.stderr
    assert " M noni/" not in proc.stderr and "A  noni/" not in proc.stderr, proc.stderr
    assert _head(repo) == _git_ok(repo, "rev-parse", "HEAD").stdout.strip()
    assert not _marker.marker_path(repo).exists(), \
        "a failed first registration left a marker behind"
    # The file itself is still written (the message says so), and it is still the
    # only change this run made to the tree: no sibling touched, and nothing else
    # staged for a later 'git add -A' to sweep in by accident. The staged entry
    # for this one path is the primitive's own (reset, add, then the commit git
    # refused), and the message's whole claim is that the change is written and
    # uncommitted -- HEAD above proves the uncommitted half. The coverage hook's
    # data file appears beside it under the suite and is not this writer's doing,
    # so the assertion names the path it cares about.
    rows = [row for row in _git_ok(repo, "status", "--porcelain").stdout.splitlines()
            if "noni/" in row]
    assert rows == [f"A  noni/sessions/{_sid_of_any(repo)}"], rows


def test_a_refused_commit_restores_a_marker_an_earlier_run_left(tmp_path):
    """The same refusal against a tree that already carried a marker: the earlier
    run's bytes come back verbatim, trailing newline included.

    A restore that rewrote the marker through the writer's own formatter would be
    a second change this run made and did not commit, and the id it names would
    still be this run's rather than the session the marker was written for.
    """
    repo, _first = _refused_register(tmp_path, "marked")
    marker = _marker.marker_path(repo)
    previous = "2026-10-01-keepme\n"
    marker.write_text(previous, encoding="utf-8")

    again = _register_refusing_commit(repo, tmp_path)

    assert again.returncode == 3, f"{again.returncode}: {again.stderr}"
    assert "git could not commit" in again.stderr, again.stderr
    assert "could not be restored" not in again.stderr, again.stderr
    assert marker.read_text(encoding="utf-8") == previous


def test_a_refused_commit_says_when_the_marker_could_not_be_restored(tmp_path):
    """The one case AC1 does not fully cover has to be said out loud.

    When the restore itself cannot land, the tree can still be marked for a
    session git never received -- the state the restore exists to prevent -- and
    a message that only refused the commit would leave the operator believing the
    undo happened. The refusal stays the headline; one clause names the marker and
    the hint names what to do about it.
    """
    repo, _first = _refused_register(tmp_path, "stuck-marker")
    marker = _marker.marker_path(repo)
    # A marker holding bytes that are not UTF-8: read_marker reads it back as
    # nothing (so this run allocates afresh and marks the tree through it), while
    # read_marker_raw keeps the lone surrogates -- and the restore's UTF-8 write
    # cannot encode them. The real state where a restore cannot land, reached
    # without patching anything.
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"2026-10-01-keepme\n\xff\xfe\n")

    again = _register_refusing_commit(repo, tmp_path)

    assert again.returncode == 3, f"{again.returncode}: {again.stderr}"
    assert "git could not commit" in again.stderr, again.stderr
    assert "could not be restored" in again.stderr, again.stderr
    assert str(marker) in again.stderr, again.stderr
    assert "Traceback" not in again.stderr, again.stderr
    # The restore did not land, which is the fact the message has to carry. What
    # is left in the marker is the empty write the restore managed before the
    # surrogates (a restore cannot be half-applied and still be trusted), which is
    # precisely why the operator is told to remove it rather than left to assume
    # the earlier bytes came back.
    assert not marker.read_bytes().startswith(b"2026-10-01-keepme")


def test_register_defaults_publish_no_local_paths_or_hostname(tmp_path):
    """A default registration contains no absolute path and no hostname."""
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = run_register(repo, "synthetic-identity")
    assert proc.returncode == 0, proc.stderr

    sessions_dir = repo / "noni" / "sessions"
    files = list(sessions_dir.glob("*.md"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    value = _hostworktree_value(body)

    # No absolute path anywhere in the file, and none in the field value.
    assert "/" not in value, f"absolute path leaked into host/worktree: {value}"
    assert str(tmp_path) not in body, "tmp repo path leaked into the session file"
    # The machine hostname must not be recorded either.
    assert socket.gethostname() not in body, "machine hostname leaked into the session file"
    assert socket.gethostname() not in value


def test_register_explicit_values_written_as_given(tmp_path):
    """Explicit --worktree and --host are written verbatim."""
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = run_register(
        repo,
        "synthetic-identity",
        worktree="some/other/dir",
        host="chosen-host",
    )
    assert proc.returncode == 0, proc.stderr

    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    value = _hostworktree_value(body)
    assert value == "chosen-host (some/other/dir)"
