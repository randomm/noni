"""The GitHub-issues adapter's allow-list: sources, precedence, fail-closed loading.

The allow-list is never hard-coded: it loads from an untracked local config file
AND from an env var, and the file/env precedence mirrors the scrub's deny-list.

Loading is fail-closed. A default file that is a symlink, world-writable, or
undecodable is *refused* and the env-var candidate is not consulted as a
fallback; only an *absent* default lets the env var through. An active
allow-list whose lines are all malformed authorizes nothing but is not a
refusal. And a refusal is a no-candidate, not a refusal to load: an operator who
names a file still gets an active list.

Fixtures are synthetic-only and read offline (see gh_adapter_support).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gh_adapter_support import _INTEGRATIONS, REPO, _load_fixture, adapter, adapter_protocol

# --- Allow-list loading (never hard-coded) -----------------------------------

def test_allowlist_from_local_config_file(tmp_path, monkeypatch):
    """The allow-list loads from an untracked local config file (one account
    per line, comments and blanks ignored), through the adapter's seam.
    This is the canonical seam: load_allowlist(env_var, file) with the
    adapter's env var and the local config file."""
    config = tmp_path / "file-allowlist.txt"
    config.write_text("# local allow-list\nop-1\n\nother-operator\n", encoding="utf-8")
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, config)
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1", "other-operator"}


def test_allowlist_from_env_var(tmp_path, monkeypatch):
    """The allow-list loads from the file named by the env var (the
    NONI_ADAPTER_ALLOWLIST mirror of the scrub's NONI_SCRUB_DENYLIST)."""
    env_file = tmp_path / "env-allowlist.txt"
    env_file.write_text("op-1\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_file.as_posix())
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, tmp_path / "absent.txt")
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1"}


def test_allowlist_file_takes_precedence_over_env_var(tmp_path, monkeypatch):
    """The untracked local file takes precedence over the env-var-named file
    (mirrors the scrub's deny-list precedence)."""
    file_allowlist = tmp_path / "file-allowlist.txt"
    file_allowlist.write_text("op-1\n", encoding="utf-8")
    env_allowlist = tmp_path / "env-allowlist.txt"
    env_allowlist.write_text("other-operator\n", encoding="utf-8")

    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_allowlist.as_posix())
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, file_allowlist)
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1"}

    # Remove the file: the env-var-named file takes effect.
    file_allowlist.unlink()
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, file_allowlist)
    assert loaded.status == "active"
    assert loaded.accounts == {"other-operator"}


def test_allowlist_absent_yields_empty_set(tmp_path, monkeypatch):
    """With no local configuration the allow-list is empty: an adapter
    without a local allow-list authorizes nothing (it does not fall back to
    a hard-coded list)."""
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, tmp_path / "absent.txt")
    assert loaded.status == "absent"
    assert loaded.accounts == set()


def test_default_allowlist_file_is_gitignored():
    """The default allow-list file path is in .gitignore so it can never be
    committed (the same contract as the scrub's deny-list)."""
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".noni-adapter-allowlist" in gitignore
    result = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", ".noni-adapter-allowlist"],
        capture_output=True,
    )
    assert result.returncode == 0, ".noni-adapter-allowlist is not git-ignored"


def test_default_allowlist_file_resolves_to_the_attached_repo_root(tmp_path, monkeypatch):
    """The resolved default path is the ATTACHED repository's root, not the
    adapter's install directory (the bug that blocked adoption: the default
    used to be ``integrations/.noni-adapter-allowlist``).

    The value is asserted directly — a .gitignore substring check alone let the
    wrong path ship — and a file at that path is the one the loader loads."""
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)
    attached = tmp_path / "attached"
    attached.mkdir()

    resolved = adapter.default_allowlist_file(attached)

    assert resolved is not None
    assert Path(resolved) == attached / ".noni-adapter-allowlist"
    assert Path(resolved) != _INTEGRATIONS / ".noni-adapter-allowlist"
    assert not Path(resolved).is_relative_to(REPO / "integrations"), (
        f"the default must not live under noni's install directory: {resolved}"
    )

    (attached / ".noni-adapter-allowlist").write_text("op-1\n", encoding="utf-8")
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, resolved)
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1"}


def test_default_allowlist_file_accepts_a_string_root(tmp_path, monkeypatch):
    """A caller that holds the attached root as a ``str`` (a path read from
    config, say) gets the same answer as a ``Path``: the helper converts it
    rather than raising AttributeError on a string's missing ``is_dir``."""
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)
    attached = tmp_path / "attached-str"
    attached.mkdir()

    resolved = adapter.default_allowlist_file(str(attached))

    assert resolved is not None
    assert Path(resolved) == attached / ".noni-adapter-allowlist"
    (attached / ".noni-adapter-allowlist").write_text("op-1\n", encoding="utf-8")
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, resolved)
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1"}


def test_default_allowlist_file_is_none_without_a_repo_root(tmp_path, monkeypatch):
    """With no usable repository root the default is no candidate at all: the
    loader then consults only the env var, and with neither source the
    allow-list is ``absent`` (fail closed, never a wider default)."""
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)

    missing = tmp_path / "not-created-yet"
    for root in (None, missing):
        assert adapter.default_allowlist_file(root) is None, (
            f"an unavailable root ({root}) must yield no candidate file"
        )

    loaded = adapter_protocol.load_allowlist(
        adapter.ALLOWLIST_ENV_VAR, adapter.default_allowlist_file(None)
    )
    assert loaded.status == "absent"
    assert loaded.accounts == set()


def test_default_allowlist_file_is_none_for_an_unusable_root(tmp_path, monkeypatch):
    """The two negatives the guard adds: the empty string, and a value that is
    neither ``str`` nor ``Path``.

    ``Path("")`` is ``Path(".")`` — truthy, relative, and a directory in every
    shell — so without the guard an empty root would resolve to a candidate in
    whatever cwd the caller happened to run in: the wider default a fail-closed
    helper exists to refuse. The typed values raise ``TypeError`` inside
    ``Path``, which is a crash where the contract promises ``None``."""
    monkeypatch.delenv(adapter.ALLOWLIST_ENV_VAR, raising=False)

    unusable = ["", b"/tmp", 0, 7, [], {}, 1.5, True]
    for root in unusable:
        assert adapter.default_allowlist_file(root) is None, (
            f"an unusable root ({root!r}) must yield no candidate file, not a "
            f"cwd-relative path and not a TypeError"
        )

    # The refusal is a no-candidate, not a refusal to load: the env-var path is
    # untouched, so an operator who names a file still gets an active list.
    loaded = adapter_protocol.load_allowlist(
        adapter.ALLOWLIST_ENV_VAR, adapter.default_allowlist_file("")
    )
    assert loaded.status == "absent"
    assert loaded.accounts == set()


def test_default_allowlist_file_none_still_honours_the_env_var(tmp_path, monkeypatch):
    """A missing root is not a refusal: with no default candidate the env-var
    file still loads (the precedence rule lives in the loader, untouched)."""
    env_file = tmp_path / "ops-allowlist"
    env_file.write_text("op-9\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, str(env_file))

    loaded = adapter_protocol.load_allowlist(
        adapter.ALLOWLIST_ENV_VAR, adapter.default_allowlist_file(None)
    )
    assert loaded.status == "active"
    assert loaded.accounts == {"op-9"}


# --- Fail-closed allow-list loading ------------------------------------------


def _make_world_writable(path: Path) -> None:
    """Make ``path`` world-writable. On a filesystem without world-write
    support (e.g. some FAT mounts) the mode may not stick — in that case the
    test would need a different fixture, so we surface it as an error."""
    path.chmod(path.stat().st_mode | 0o002)
    assert path.stat().st_mode & 0o002, "could not make fixture world-writable"


def test_default_allowlist_symlink_refuses_no_fallback_to_env(tmp_path, monkeypatch, capsys):
    """A symlinked default allow-list file is refused (symlink), and the
    env-var candidate is NOT consulted as a fallback — the result is
    inactive/refused and nothing is authorized."""
    real = tmp_path / "real-allowlist.txt"
    real.write_text("op-1\n", encoding="utf-8")
    default = tmp_path / "default.txt"
    default.symlink_to(real)
    env_file = tmp_path / "env-allowlist.txt"
    env_file.write_text("op-1\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_file.as_posix())
    warnings: list[str] = []
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, default, warnings)
    assert loaded.status == "refused"
    assert loaded.accounts == set()
    assert not loaded.authorized
    assert loaded.reason and "symlink" in loaded.reason
    # The refusal is reported both on stderr and in warnings, naming the
    # file and the reason (distinct from "no allow-list configured": that
    # case emits no notices).
    err = capsys.readouterr().err
    assert "refused" in err and "symlink" in err and str(default) in err
    assert any("refused" in w and "symlink" in w for w in warnings)
    # Nothing is authorized: the adapter's seam sees the empty allow-list.
    payload = _load_fixture("comment-one.json")
    v = adapter.question_legitimacy(payload, set(loaded.accounts))
    assert v.verdict == "stranger" and v.answer is None


def test_default_allowlist_world_writable_refuses_no_fallback_to_env(tmp_path, monkeypatch, capsys):
    """A world-writable default allow-list file is refused, and the env-var
    candidate is NOT consulted — refused, nothing authorized."""
    default = tmp_path / "default.txt"
    default.write_text("op-1\n", encoding="utf-8")
    _make_world_writable(default)
    env_file = tmp_path / "env-allowlist.txt"
    env_file.write_text("op-1\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_file.as_posix())
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, default)
    assert loaded.status == "refused"
    assert loaded.accounts == set()
    assert not loaded.authorized
    assert loaded.reason and "world-writable" in loaded.reason
    err = capsys.readouterr().err
    assert "refused" in err and "world-writable" in err


def test_absent_default_with_valid_env_file_uses_env(tmp_path, monkeypatch):
    """When the default file is absent, the env-var-named file IS consulted
    (the fallback is reserved for the absent case) and is active."""
    env_file = tmp_path / "env-allowlist.txt"
    env_file.write_text("op-1\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_file.as_posix())
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, tmp_path / "absent-default.txt")
    assert loaded.status == "active"
    assert loaded.accounts == {"op-1"}
    assert "op-1" in loaded
    assert "op-1" in set(loaded.accounts)


def test_default_present_undecodable_refuses_no_fallback(tmp_path, monkeypatch):
    """A present-but-undecodable default file is refused, not fallen back.
    (Covers the undecodable branch of the fail-closed rule.)"""
    default = tmp_path / "default.txt"
    default.write_bytes(b"\xff\xfe\x00op-1\n")  # not valid UTF-8
    env_file = tmp_path / "env-allowlist.txt"
    env_file.write_text("op-1\n", encoding="utf-8")
    monkeypatch.setenv(adapter.ALLOWLIST_ENV_VAR, env_file.as_posix())
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, default)
    assert loaded.status == "refused"
    assert loaded.accounts == set()
    assert not loaded.authorized


def test_allowlist_with_only_malformed_lines_is_active_but_empty(tmp_path):
    """An active allow-list whose lines are all malformed is still active
    (it authorizes nothing — an empty active allow-list is not a refusal)."""
    bad = tmp_path / "default.txt"
    bad.write_text("op 1\nbad/line\nop\x001\n", encoding="utf-8")
    warnings: list[str] = []
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, bad, warnings)
    assert loaded.status == "active"
    assert loaded.accounts == set()
    # An active allow-list with no valid lines is still authorized (it
    # authorizes nothing — an empty active allow-list is not a refusal).
    assert loaded.authorized
    # All three lines are malformed (internal whitespace, path separator,
    # control character) — an active allow-list with no valid lines
    # authorizes nothing (an empty active allow-list is not a refusal).
    assert len(warnings) == 3


def test_malformed_allowlist_lines_with_control_chars_skipped(tmp_path, capsys):
    """Allow-list lines with control/non-printable characters or internal
    whitespace are skipped with a diagnostic (and do not authorize)."""
    f = tmp_path / "default.txt"
    f.write_text("op-1\nop 2\nop\x003\nop\n\t\n", encoding="utf-8")
    loaded = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, f)
    assert loaded.status == "active"
    # The two control-char/whitespace lines are skipped; op-1 and op are
    # valid tokens.
    assert loaded.accounts == {"op-1", "op"}
    err = capsys.readouterr().err
    assert "malformed line" in err


def test_case_insensitive_allowlist_match():
    """Tracker logins are case-insensitive on GitHub, so allow-list
    matching is case-insensitive (documented behavior), and the match is
    symmetric: the account name is casefolded at parse time and at
    lookup time, so a stored name matches a case-varied lookup and a
    case-varied stored name matches a plain lookup."""
    # Direction 1: plain stored, case-varied lookup.
    loaded = adapter_protocol.Allowlist({"op-1"}, "active")
    assert "OP-1" in loaded
    assert "Op-1" in loaded
    assert "op-1" in loaded
    assert "op-2" not in loaded
    # Direction 2: case-varied stored, plain lookup.
    loaded_case = adapter_protocol.Allowlist({"OP-1"}, "active")
    assert "op-1" in loaded_case
    assert "Op-1" in loaded_case
    assert "OP-1" in loaded_case
    assert "op-2" not in loaded_case
    # is_allowed matches case-insensitively for both Allowlist and bare-set
    # shapes, in both directions.
    assert adapter_protocol.is_allowed(loaded, "OP-1")
    assert adapter_protocol.is_allowed(loaded_case, "op-1")
    assert adapter_protocol.is_allowed({"op-1"}, "Op-1")
    assert adapter_protocol.is_allowed({"OP-1"}, "op-1")
    # load_allowlist casefolds at parse time: a file written in any case
    # matches any-case lookups.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "al.txt"
        f.write_text("OP-1\n", encoding="utf-8")
        parsed = adapter_protocol.load_allowlist(adapter.ALLOWLIST_ENV_VAR, f)
        assert parsed.status == "active"
        assert parsed.accounts == {"op-1"}
        assert "op-1" in parsed and "OP-1" in parsed


def test_refused_allowlist_never_authorizes():
    """A refused (or absent) Allowlist authorizes nothing, and an inactive
    allow-list stores no accounts at all — the seam-facing decision is
    always negative when not active, and len()/repr never suggest an
    account is live when the list as a whole is not."""
    refused = adapter_protocol.Allowlist({"op-1"}, "refused", "symlink")
    assert "op-1" not in refused
    assert not refused
    assert len(refused) == 0
    assert refused.accounts == set()
    assert "op-1" not in refused.accounts
    assert not adapter_protocol.is_allowed(refused, "op-1")
    absent = adapter_protocol.Allowlist(set(), "absent")
    assert "op-1" not in absent
    assert not adapter_protocol.is_allowed(absent, "op-1")


def test_bare_string_allowlist_never_authorizes():
    """A plain string is not an allow-list. A bare string is iterable over
    its characters, so an unguarded ``name in allowlist``-style check would
    let ``is_allowed("op-1", "o")`` authorize: is_allowed must refuse every
    non-set input (not just let it through), and __contains__ must be
    tolerant of non-str lookups (no AttributeError)."""
    # A bare string allow-list authorizes nothing, whatever the name.
    assert adapter_protocol.is_allowed("op-1", "o") is False
    assert adapter_protocol.is_allowed("op-1", "op-1") is False
    assert adapter_protocol.is_allowed(42, "op-1") is False
    assert adapter_protocol.is_allowed(["op-1"], "op-1") is False
    assert adapter_protocol.is_allowed(("op-1",), "op-1") is False
    assert adapter_protocol.is_allowed({"op-1": 1}, "op-1") is False
    # But a real set / frozenset still authorizes.
    assert adapter_protocol.is_allowed(frozenset({"op-1"}), "OP-1")


def test_allowlist_contains_is_tolerant_of_non_str_lookups():
    """Allowlist.__contains__ must not call .casefold() on a non-str lookup
    name (which would raise AttributeError) — it returns False instead."""
    active = adapter_protocol.Allowlist({"op-1"}, "active")
    for bad in (None, 42, ["op-1"], b"op-1", {"op-1"}):
        assert bad not in active, f"{bad!r} must not match (and must not raise)"
    # The str path is unchanged: a valid name still matches.
    assert "op-1" in active
