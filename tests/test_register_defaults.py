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

import socket
import subprocess
import sys
from pathlib import Path

from _harness import REGISTER, SRC, _git_ok, run_from, subprocess_env
from conftest import run_register


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


# --- State root: --repo names it, the cwd does not ----------------------------
#
# register.py is the writer that creates noni/sessions/ in the first place, so a
# run that resolved the sessions directory from its cwd would seed a project
# nobody pointed it at. Three trees: the state repository (a git repo holding no
# noni/ yet), a decoy register beside the cwd, and an empty cwd a stray write
# would show up in.

REGISTER_STATE_DIR = "register-state-root"
REGISTER_CWD_DIR = "register-cwd"
REGISTER_DECOY_DIR = "register-decoy"
REGISTER_DECOY_SID = "2026-10-01-dddddd"


def _register_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one register state-root run: (root, decoy, cwd)."""
    root = _git_repo(tmp_path)
    root = root.rename(tmp_path / REGISTER_STATE_DIR)
    decoy = tmp_path / REGISTER_DECOY_DIR
    sessions = decoy / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{REGISTER_DECOY_SID}.md").write_text(
        "# session decoy\n\n- identity: decoy\n- host/worktree: decoy (decoy)\n"
        "- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n"
        "  - claim: #999\n",
        encoding="utf-8",
    )
    cwd = tmp_path / REGISTER_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _register_from(cwd: Path, repo: Path, identity: str = "developer"
                   ) -> subprocess.CompletedProcess[str]:
    """register.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, REGISTER, "--repo", str(repo), "--identity", identity)


def test_register_creates_the_register_only_under_the_state_root(tmp_path):
    """A first registration creates ``noni/sessions/`` in the state repository
    and leaves the decoy and the cwd exactly as they were."""
    root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()
    assert not (root / "noni").exists(), "the state root must start with no noni/"

    proc = _register_from(cwd, root)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    files = list((root / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1, f"one register file is one registration: {files}"
    body = files[0].read_text(encoding="utf-8")
    assert _fields(body)["identity"] == "developer"
    # The commit landed in the state repository, not wherever the run happened
    # to be launched from: HEAD's only path is the new register file.
    subject = _git_ok(root, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("register:"), subject
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes, (
        "the run touched the decoy register beside its cwd, so the sessions "
        "directory resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_register_reuses_the_state_roots_marker_not_the_cwds(tmp_path):
    """The working-copy marker is read from ``--repo`` too: a second run in the
    same state root continues the session instead of minting a new one, even
    though both runs launch from an unrelated directory."""
    root, _decoy, cwd = _register_case(tmp_path)
    first = _register_from(cwd, root)
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)

    second = _register_from(cwd, root)
    assert second.returncode == 0, second.stderr
    assert f"{sid}.md already registered" in second.stdout, second.stdout
    assert len(list((root / "noni" / "sessions").glob("*.md"))) == 1, (
        "a second run allocated a second session, so the marker was not the "
        "state root's"
    )


def test_register_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is a usage error (exit 2) naming the
    argument, and it creates nothing beside the cwd."""
    _root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()

    proc = _register_from(cwd, tmp_path / "no-such-state-root")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "--repo" in proc.stderr.lower(), proc.stderr
    assert "directory" in proc.stderr.lower(), proc.stderr
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes
    assert not (cwd / "noni").exists()
