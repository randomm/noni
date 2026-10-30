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
    _mark_status,
    _no_committer_env,
    _refused_register,
    _register_refusing_commit,
    _sid_of_any,
)

from noni import _marker, register


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


def test_a_refused_commit_says_when_the_marker_could_not_be_restored(tmp_path,
                                                                     monkeypatch,
                                                                     capsys):
    """The one case AC1 does not fully cover has to be said out loud.

    When the restore itself cannot land, the tree can still be marked for a
    session git never received -- the state the restore exists to prevent -- and
    a message that only refused the commit would leave the operator believing the
    undo happened. The refusal stays the headline; one clause names the marker and
    the hint names what to do about it.

    The run that needs the clause is a re-registration, not a first one: the
    writer reads the marker's previous bytes *before* it writes its own, so the
    only run with bytes to put back is one whose working copy was already marked
    (a first registration's undo is the unlink, not a write). So this tree carries
    a committed, terminal session marked as its own -- a run is expected to
    allocate the next session and be refused for committing it.

    The restore is then made to fail at the one step of it that can: it writes its
    bytes through a temp file in the marker's own directory and one
    ``os.replace``, and that replace is refused here while the tree stays a tree
    an operator could be standing in. Nothing else about the run is faked, and --
    unlike a marker whose bytes are merely not UTF-8, which now restores
    byte-for-byte -- no codec is involved in the failure.
    """
    repo, first = _refused_register(tmp_path, "stuck-marker")
    assert first.returncode == 3, first.stderr
    marker = _marker.marker_path(repo)
    # The first run's refusal put its own marker back (absent), so mark this
    # working copy for a session of its own and end that session: the next run for
    # this working copy allocates afresh, writes the marker over the earlier one,
    # and has the earlier run's bytes to put back.
    committed = next((repo / "noni" / "sessions").glob("*.md"))
    earlier = committed.name.removesuffix(".md")
    _git_ok(repo, "add", "noni", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "commit the session file the refused run wrote")
    _mark_status(committed, "closed")
    _git_ok(repo, "add", "--", "noni/sessions")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "close the session")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(f"{earlier}\n".encode())

    def refusing_restore(marker_path, previous):
        """The undo refused at its one failable step: the byte replace.

        A restore that lands is not the state this clause reports, so the refusal
        is bound to the undo and to nothing else -- the session file's write, the
        marker write that follows it, and git's refusal all run as they do in a
        normal run. The marker still naming this run's session is what the clause
        then has to name.
        """
        assert previous is not None, \
            "this run read no previous marker bytes, so the tree is not the state " \
            "the clause is worded for and the refusal below would prove nothing"
        return False

    monkeypatch.setattr(_marker, "restore_marker", refusing_restore)

    # In-process, under the environment a refusing run is launched with (an empty
    # global gitconfig; the suite's autouse fixture has already cleared the
    # identity variables, and this tree's own config names no committer). In-process
    # is what lets the refusal land on the module ``register`` resolves
    # ``restore_marker`` off -- a child process imports its own copy of the module
    # and ignores the patch, which an earlier draft of this test mistook for the
    # product failing to report.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL",
                       _no_committer_env(tmp_path)["GIT_CONFIG_GLOBAL"])
    again = register.main(["--repo", str(repo), "--identity", "dev"])
    err = capsys.readouterr().err

    assert again == 3, f"{again}: {err}"
    assert "git could not commit" in err, err
    assert "could not be restored" in err, err
    assert str(marker) in err, err
    assert "Traceback" not in err, err
    # The restore did not land, which is the fact the message has to carry: the
    # marker still names the session this run allocated, and a message that let
    # the operator believe the undo happened is the failure this clause prevents.
    written = sorted(p.name.removesuffix(".md")
                     for p in (repo / "noni" / "sessions").glob("*.md"))
    assert earlier in written, written
    this_run = [sid for sid in written if sid != earlier]
    assert len(this_run) == 1, written
    assert marker.read_bytes() == f"{this_run[0]}\n".encode()


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
