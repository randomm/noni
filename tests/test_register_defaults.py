"""Register defaults must never publish machine-local values.

The register file is committed to a public repo (see the public-repo hygiene
rule in AGENTS.md), so a registration run without --worktree / --host must not
write an absolute path or the machine hostname into it. Explicit --worktree
and --host values are written as given.

The second half of this file covers register.py's refusal and idempotency
paths (the --file mismatch, the same-identity no-op, the other-identity
refusal) and the shapes _parse_fields tolerates: they are the exit-code
contract of the writer, and they are what the coverage gate otherwise never
executes.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

from _harness import REGISTER, SRC, _git_ok, run_from, subprocess_env
from conftest import run_register

from noni import _marker


def _git_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one commit, in tmp_path.

    The marker lives under the tree's own ``.git``, and the committing path
    needs a branch to commit on, so the idempotency tests need a real repo and
    not a bare directory.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    return repo


def _head(repo: Path) -> str:
    """The commit HEAD names, for the assertion that a reuse adds none."""
    return _git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def _sid_of(stdout: str) -> str:
    """The session id from register.py's committing success line."""
    return stdout.strip().split("registered session ")[1].split(" ->")[0].strip()


def _mark_status(path: Path, status: str) -> None:
    """Rewrite a session file's own ``- status:`` field to ``status``.

    The fixture reaches a terminal state without close.py, so the marker test
    exercises register's reading of the field and nothing else.
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("- status:"):
            lines.append(f"- status: {status}")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

# The product is the noni package; _harness puts src/ on sys.path, so the
# register helpers are reachable here as `from noni import register`. No skill
# scripts/ dir goes on the path: the wrapper there is a shim, and a lookalike
# earlier on sys.path must not be trusted as the writer's own code.


def _fields(body: str) -> dict:
    """The '- key: value' fields of a register file, as a dict."""
    fields = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- "):
            key, sep, value = line[2:].partition(":")
            if sep:
                fields[key.strip()] = value.strip()
    return fields


def _hostworktree_value(body: str) -> str:
    """Return the value part of the '- host/worktree:' field line."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- host/worktree:"):
            return line[len("- host/worktree:"):].strip()
    raise AssertionError(f"no host/worktree field in session file:\n{body}")


def _no_committer_env(tmp_path: Path) -> dict[str, str]:
    """The environment a commit refusal needs: a gitconfig that names no committer.

    An empty file, not ``/dev/null``, because the writer's git helper keeps
    ``GIT_CONFIG_GLOBAL`` in its environment (a caller's identity is meant to
    survive the filter), and a device reads as no config file at all -- which
    would let the *host's* config decide the committer and make the commit
    succeed. An empty regular file says 'this machine configured nothing', which
    is the state these tests want: the operator who runs a writer on a box where
    no committer was ever set. ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` stay
    unset (the suite's autouse fixture clears them and the launcher is asked not
    to add them), so git has no committer from either source.
    """
    empty = tmp_path / "_empty_gitconfig"
    empty.write_text("", encoding="utf-8")
    return {"GIT_CONFIG_GLOBAL": str(empty),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
# The environment a commit refusal needs: no global config for git to read a
# committer from, and no GIT_AUTHOR_* / GIT_COMMITTER_* (the launcher is asked
# not to add them, and the suite's autouse fixture already cleared them). That
# is also how an operator reaches the state -- a state repository prepared on a
# machine that never configured a committer.


def _refused_register(tmp_path, name, identity="dev"):
    """A committing register run whose git commit is refused; the tree is returned.

    ``_git_repo`` builds ``<dir>/repo``, so the tree comes back from it rather
    than being assumed to be ``tmp_path / name``.
    """
    parent = tmp_path / name
    parent.mkdir(parents=True, exist_ok=True)
    repo = _git_repo(parent)
    return repo, _register_refusing_commit(repo, tmp_path, identity)


def _register_refusing_commit(repo: Path, scratch: Path, identity: str = "dev"
                              ) -> subprocess.CompletedProcess[str]:
    """One registering run in ``repo`` whose commit git will not take.

    ``scratch`` is where that run's empty gitconfig lives; the run is otherwise
    an ordinary one, so the only difference an operator can see is the refusal.
    """
    return run_from(repo, REGISTER, "--repo", str(repo), "--identity", identity,
                    identity=False, env=_no_committer_env(scratch))


def _sid_of_any(repo: Path) -> str:
    """The session id of the one register file this run left in ``repo``.

    The id is minted from the clock, so a test that needs to name the path reads
    it back from the tree rather than guessing at the date.
    """
    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1, files
    return files[0].name


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
    assert marker.read_text(encoding="utf-8") == previous


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


# --- Refusal and idempotency paths -------------------------------------------
#
# register.py's contract is that a writer only ever touches a file it
# allocated in this run, and never another session's file. Three paths carry
# that contract and each exits with a distinct code; they are driven here
# through the real CLI (subprocess), with the id allocator patched so a run
# can be aimed at a path that already exists.
#
# The allocator is patched in a tiny driver script rather than in-process:
# register.py must stay byte-identical, and monkeypatching its clock or id
# function in the pytest process would not reach the launched interpreter.


def _run_patched_allocation(tmp_path: Path, repo: Path, identity: str, session_id: str) -> subprocess.CompletedProcess:
    """Run register.py's main() with _make_session_id pinned to session_id.

    Pinning the allocation is what makes the idempotency branches reachable
    from the outside: the --file guard compares against a freshly minted id on
    every run, so the only way to name the allocated path is to fix what the
    allocation produces. The driver is written under the test's tmp_path and
    puts register.py's own directory on sys.path itself, so nothing is ever
    created inside the shipped skills/ tree; register.py is never modified.
    The child runs under sys.executable with the harness env, which is what
    keeps it inside the coverage measurement.
    """
    driver_dir = tmp_path / "_register_test_driver"
    driver_dir.mkdir(exist_ok=True)
    driver = driver_dir / "drive_register.py"
    driver.write_text(
        "import os\n"
        "import sys\n"
        f"sys.path.insert(0, {str(SRC)!r})\n"
        "from noni import register\n"
        "register._make_session_id = lambda: os.environ['NONI_TEST_SESSION_ID']\n"
        "raise SystemExit(register.main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    env = subprocess_env()
    env["NONI_TEST_SESSION_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(driver), "--repo", str(repo), "--identity", identity],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_file_that_was_not_allocated_is_refused(tmp_path):
    """A --file the run did not allocate is refused with exit 2, and nothing
    is written: the writer writes only a path it allocated."""
    repo = tmp_path / "repo"
    repo.mkdir()
    other = repo / "noni" / "sessions" / "2026-01-01-dead07.md"
    other.parent.mkdir(parents=True)
    other.write_text("- identity: someone-else\n", encoding="utf-8")

    proc = run_register(repo, "synthetic-identity", file=str(other))
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "refusing to write" in proc.stderr, proc.stderr
    # The pre-existing file is untouched and no second file appeared.
    assert other.read_text(encoding="utf-8") == "- identity: someone-else\n"
    assert [p.name for p in other.parent.glob("*.md")] == ["2026-01-01-dead07.md"]


def test_relative_file_path_is_resolved_against_the_repo(tmp_path):
    """A relative --file resolves against --repo before the allocation check,
    so it is still refused as un-allocated rather than silently written to the
    current directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = run_register(repo, "synthetic-identity", file="noni/sessions/not-mine.md")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}\n{proc.stderr}"
    assert not (repo / "noni" / "sessions" / "not-mine.md").exists()


def test_re_registering_the_marked_active_session_is_a_noop(tmp_path):
    """The idempotency branch: a second register in a working copy marked for
    an active session exits 0, prints the no-op line, and leaves the bytes and
    HEAD alone — no second file, no second commit.

    The marker, not ``--file``, is what makes this reachable from the CLI as
    shipped: the allocator mints a fresh id every run, so the only way a run
    names a file it did not allocate is the marker an earlier run left.
    """
    repo = _git_repo(tmp_path)
    first = run_register(repo, "synth")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    target = repo / "noni" / "sessions" / f"{sid}.md"
    original = target.read_text(encoding="utf-8")
    head_before = _head(repo)

    second = run_register(repo, "synth")
    assert second.returncode == 0, f"expected exit 0, got {second.returncode}\n{second.stdout}\n{second.stderr}"
    assert "already registered" in second.stdout, second.stdout
    assert "identity=synth" in second.stdout, second.stdout
    assert target.read_text(encoding="utf-8") == original
    assert _head(repo) == head_before, "a reuse must not add a commit"
    assert [p.name for p in target.parent.glob("*.md")] == [f"{sid}.md"]


def test_second_register_after_a_terminal_status_allocates_a_new_session(tmp_path):
    """The other side of the marker: a marked session that has ended is no
    session to continue, so the next register allocates a new file and re-marks
    the working copy for it."""
    repo = _git_repo(tmp_path)
    first = run_register(repo, "synth")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    _mark_status(repo / "noni" / "sessions" / f"{sid}.md", "closed")

    second = run_register(repo, "synth")
    assert second.returncode == 0, second.stderr
    new_sid = _sid_of(second.stdout)
    assert new_sid != sid
    assert "allocating a new session" in second.stdout or "allocating a new session" in second.stderr
    assert (repo / "noni" / "sessions" / f"{new_sid}.md").is_file()


def test_marked_session_with_another_identity_is_refused(tmp_path):
    """The working copy is marked for an active session carrying a different
    identity: exit 1, both identities named, and the other session's bytes left
    alone — this is the only path on which a run can name a file it did not
    allocate, and it is refused."""
    repo = _git_repo(tmp_path)
    first = run_register(repo, "other-person")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    target = repo / "noni" / "sessions" / f"{sid}.md"
    original = target.read_text(encoding="utf-8")

    second = run_register(repo, "synth")
    assert second.returncode == 1, f"expected exit 1, got {second.returncode}\n{second.stdout}\n{second.stderr}"
    assert "other-person" in second.stderr and "synth" in second.stderr, second.stderr
    assert target.read_text(encoding="utf-8") == original


def test_unreadable_marked_file_is_refused_not_overwritten(tmp_path):
    """A marked file that cannot be read is a refusal (exit 2), never a fresh
    write over bytes this run could not read: fail closed."""
    repo = _git_repo(tmp_path)
    first = run_register(repo, "synth")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    target = repo / "noni" / "sessions" / f"{sid}.md"
    # Bytes no field parser can read, and no valid text at all.
    target.write_bytes(b"\xff\xfe\x00\x01 not text")

    second = run_register(repo, "synth")
    assert second.returncode == 2, f"expected exit 2, got {second.returncode}\n{second.stdout}\n{second.stderr}"
    assert "refusing to overwrite" in second.stderr, second.stderr
    assert target.read_bytes() == b"\xff\xfe\x00\x01 not text"


def test_a_session_with_no_identity_field_is_not_overwritten(tmp_path):
    """A pre-existing file that carries no identity is treated as someone
    else's (an empty identity differs from the requested one): exit 1, never a
    write. This is the fail-closed side of the idempotency check."""
    repo = _git_repo(tmp_path)
    first = run_register(repo, "synth")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    target = repo / "noni" / "sessions" / f"{sid}.md"
    target.write_text("- status: active\n", encoding="utf-8")

    second = run_register(repo, "synth")
    assert second.returncode == 1, f"a file with no identity must not be overwritten, got {second.returncode}"
    assert target.read_text(encoding="utf-8") == "- status: active\n"


def test_registration_creates_the_sessions_dir_when_absent(tmp_path):
    """A fresh repo has no noni/ state: registration creates the sessions dir
    and writes exactly the allocated file (the first-writer path)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = run_register(repo, "synthetic-identity")
    assert proc.returncode == 0, proc.stderr
    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1
    fields = _fields(files[0].read_text(encoding="utf-8"))
    assert fields["identity"] == "synthetic-identity"
    assert fields["status"] == "active"


# --- _parse_fields shapes ----------------------------------------------------
#
# The register-file field grammar is one line per field, '- key: value',
# parsed by stripping the line first. These assert the shapes the parser must
# tolerate without crashing or inventing a field, including the indented claim
# row that the census — not the parser — classifies.


def test_parse_fields_reads_dash_prefixed_key_value_lines():
    """Fields are read after stripping, so the indented claim row parses as a
    'claim' key: register.py uses only identity, and the census is what
    separates claim rows from fields (census-sessions.py)."""
    from register import _parse_fields

    fields = _parse_fields(
        "# session x\n"
        "\n"
        "- identity: synth\n"
        "- host/worktree: host-a (work-a)\n"
        "- claims:\n"
        "  - claim: #42\n"
    )
    assert fields["identity"] == "synth"
    assert fields["host/worktree"] == "host-a (work-a)"
    assert fields["claims"] == ""
    assert fields["claim"] == "#42"


def test_parse_fields_ignores_malformed_lines():
    """A line without a colon, a non-field line and an empty body are all
    tolerated: no crash, and nothing invented."""
    from register import _parse_fields

    assert _parse_fields("") == {}
    assert _parse_fields("just prose\n- no colon here\n- identity: ok") == {"identity": "ok"}
    # Surrounding whitespace is stripped from both key and value.
    assert _parse_fields("   -   identity   :    synth   ") == {"identity": "synth"}


def test_parse_fields_keeps_the_last_write_for_a_repeated_key():
    """A duplicated field is last-wins: the census, not the parser, decides
    whether a repeated key is a defect."""
    from register import _parse_fields

    assert _parse_fields("- status: active\n- status: idle") == {"status": "idle"}


def test_parse_fields_splits_on_the_first_colon_only():
    """A value containing colons (a timestamp) survives intact."""
    from register import _parse_fields

    assert _parse_fields("- started: 2026-10-01T10:00:00Z") == {
        "started": "2026-10-01T10:00:00Z"
    }


