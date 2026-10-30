"""Register's refusal, idempotency and field-parser paths, driven through the CLI.

register.py's contract is that a writer only ever touches a file it allocated in
this run, and never another session's file. Three paths carry that contract and
each exits with a distinct code; they are driven here through the real CLI
(subprocess), with the id allocator patched so a run can be aimed at a path that
already exists.

The allocator is patched in a tiny driver script rather than in-process:
register.py must stay byte-identical, and monkeypatching its clock or id function
in the pytest process would not reach the launched interpreter.

The shapes ``_parse_fields`` tolerates are covered here too: they are the
exit-code contract of the writer, and they are what the coverage gate otherwise
never executes. The marker half of register's behaviour is in
``test_register_defaults.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import SRC, subprocess_env
from conftest import run_register
from register_refusal_fixtures import (
    _fields,
    _git_repo,
    _head,
    _mark_status,
    _sid_of,
)


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
