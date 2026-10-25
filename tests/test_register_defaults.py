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

from _harness import REGISTER as REGISTER_SCRIPT
from _harness import subprocess_env
from conftest import run_register

# register.py is a script, not a package (packages = [] in pyproject.toml), so
# reaching its helpers is the repo's established sys.path insertion, done here
# because pytest's rootdir handling does not put a skill scripts/ dir on the
# path. The subprocess driver below does its own insertion instead of relying
# on this one: it lives in tmp_path, not next to register.py.
if str(REGISTER_SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(REGISTER_SCRIPT.parent))


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
        f"sys.path.insert(0, {str(REGISTER_SCRIPT.parent)!r})\n"
        "import register\n"
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


def test_re_registering_the_allocated_file_and_identity_is_a_noop(tmp_path):
    """The idempotency branch: re-registering the file this run allocated,
    under the identity it already carries, exits 0, prints the no-op line and
    leaves the bytes alone."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "2026-01-01-aaaaaa.md"
    original = "# session 2026-01-01-aaaaaa\n\n- identity: synth\n- status: active\n"
    target.write_text(original, encoding="utf-8")

    proc = _run_patched_allocation(tmp_path, repo, "synth", "2026-01-01-aaaaaa")
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}\n{proc.stderr}"
    assert "already registered" in proc.stdout, proc.stdout
    assert "identity=synth" in proc.stdout, proc.stdout
    assert target.read_text(encoding="utf-8") == original


def test_existing_allocated_file_with_another_identity_is_refused(tmp_path):
    """The allocated path already held by a different identity exits 1, names
    both identities, and leaves the other session's bytes alone."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "2026-01-01-bbbbbb.md"
    original = "- identity: other-person\n- status: active\n"
    target.write_text(original, encoding="utf-8")

    proc = _run_patched_allocation(tmp_path, repo, "synth", "2026-01-01-bbbbbb")
    assert proc.returncode == 1, f"expected exit 1, got {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "other-person" in proc.stderr and "synth" in proc.stderr, proc.stderr
    assert target.read_text(encoding="utf-8") == original


def test_allocated_file_without_an_identity_field_is_not_overwritten(tmp_path):
    """A pre-existing file that carries no identity is treated as someone
    else's (an empty identity differs from the requested one): exit 1, never a
    write. This is the fail-closed side of the idempotency check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "2026-01-01-cccccc.md"
    target.write_text("- status: active\n", encoding="utf-8")

    proc = _run_patched_allocation(tmp_path, repo, "synth", "2026-01-01-cccccc")
    assert proc.returncode == 1, f"a file with no identity must not be overwritten, got {proc.returncode}"
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
