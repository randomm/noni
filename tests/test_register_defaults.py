"""Register defaults must never publish machine-local values.

The register file is committed to a public repo (see the public-repo hygiene
rule in AGENTS.md), so a registration run without --worktree / --host must not
write an absolute path or the machine hostname into it. Explicit --worktree
and --host values are written as given.
"""

from __future__ import annotations

import socket

from conftest import run_register


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
