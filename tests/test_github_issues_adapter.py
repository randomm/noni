"""The GitHub-issues adapter against recorded JSON fixtures.

All fixtures under tests/fixtures/gh-adapter/ are synthetic-only (synthetic
users, synthetic repos) and are read offline: the adapter's two seams are
pure functions of (payload, allow-list), so no test touches the network.

Covered (per the ticket's test surface):
- single tick by an allow-listed last-editor  -> verdict "one"
- zero ticks                                  -> verdict "none"
- two+ ticks                                  -> verdict "many"
- tick by a non-allow-listed account          -> verdict "stranger"
- allow-list loaded from a local config file AND from an env var (never
  hard-coded; the file/env precedence mirrors the scrub's deny-list)
- last-editor-wins: allow-listed first then stranger last -> "stranger";
  stranger first then allow-listed last -> "one"
- label authorization reads the account behind the label event, not the
  label's presence (stranger-applied label present -> unauthorized;
  allow-listed-applied label later removed -> still authorized)
- the ledger record the adapter's output becomes carries the new optional
  source field and passes the census.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GH_FIXTURES = REPO / "tests" / "fixtures" / "gh-adapter"

# Make integrations/ and integrations/github-issues/ importable (no package;
# sys.path insertion is the established pattern for repo-local modules).
_INTEGRATIONS = REPO / "integrations"
_GH_ADAPTER = _INTEGRATIONS / "github-issues"
for _p in (str(_INTEGRATIONS), str(_GH_ADAPTER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adapter_protocol  # noqa: E402
import github_issues_adapter as adapter  # noqa: E402

#: The synthetic allow-list every test in this module uses. Real operator
#: names live only in the untracked local allow-list file; the test uses
#: synthetic account names.
ALLOWED = {"op-1"}
NOT_ALLOWED = {"stranger-1"}


def _load_fixture(name: str) -> dict:
    return json.loads((GH_FIXTURES / name).read_text(encoding="utf-8"))


# --- Interface conformance ----------------------------------------------------

def test_adapter_implements_the_interface():
    """The GitHub-issues adapter structurally satisfies the two-seam
    interface (check_interface finds no problems)."""
    assert adapter_protocol.check_interface(adapter) == []


# --- Question legitimacy ------------------------------------------------------

def test_single_tick_by_allowlisted_last_editor_is_one():
    """Exactly one tick, last edited by an allow-listed account: verdict one,
    answer is the ticked option."""
    payload = _load_fixture("comment-one.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "one"
    assert v.answer == "next train"


def test_zero_ticks_is_none():
    """No option ticked: verdict none, no answer."""
    payload = _load_fixture("comment-none.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "none"
    assert v.answer is None


def test_two_ticks_is_many():
    """Two options ticked: verdict many (ambiguous), no answer."""
    payload = _load_fixture("comment-many.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "many"
    assert v.answer is None


def test_tick_by_non_allowlisted_account_is_stranger():
    """A single tick, but the last editor is not on the allow-list:
    verdict stranger, no answer."""
    payload = _load_fixture("comment-stranger.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "stranger"
    assert v.answer is None


def test_allowlisted_first_stranger_last_is_stranger():
    """Last-editor-wins: an allow-listed account ticks first, a stranger
    later re-ticks a different option. The last edit that ticked the comment
    was by the stranger -> stranger (the earlier allow-listed tick does not
    count)."""
    payload = _load_fixture("comment-allowlisted-first-stranger-last.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "stranger"
    assert v.answer is None


def test_stranger_first_allowlisted_last_is_one():
    """Last-editor-wins (the converse): a stranger ticks first, an
    allow-listed account later re-ticks the same option. The last edit that
    ticked the comment was by the allow-listed account -> one."""
    payload = _load_fixture("comment-stranger-first-allowlisted-last.json")
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "one"
    assert v.answer == "next train"


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


# --- Label authorization ------------------------------------------------------

def test_label_applied_by_allowlisted_account_is_authorized():
    """A label present on the issue, applied by an allow-listed account, is
    authorized (it reads the account behind the label event)."""
    payload = _load_fixture("label-authorized.json")
    assert adapter.label_authorization(payload, ALLOWED) is True


def test_label_applied_by_stranger_is_unauthorized_even_if_present():
    """A label present on the issue but applied by a non-allow-listed
    account is unauthorized: the presence is not the evidence — the label
    event's actor is."""
    payload = _load_fixture("label-stranger.json")
    assert adapter.label_authorization(payload, ALLOWED) is False


def test_label_applied_by_allowlisted_then_removed_stays_authorized():
    """A label applied by an allow-listed account stays authorized if a
    stranger later removes it: authorization is about who applied it, not
    who removed it (and not whether it is still present)."""
    payload = _load_fixture("label-authorized-then-removed.json")
    assert adapter.label_authorization(payload, ALLOWED) is True


def test_label_with_no_recorded_application_event_is_unauthorized():
    """A label present on the issue with no recorded labeled event has no
    evidence of an allow-listed applier: unauthorized."""
    payload = {
        "issue": {"labels": [{"name": "steer"}]},
        "events": [{"event": "opened", "actor": "agent-synthetic", "created_at": "2026-10-06T09:00:00Z"}],
    }
    assert adapter.label_authorization(payload, ALLOWED) is False


# --- The ledger record the adapter's output becomes ---------------------------

def test_adapter_record_with_source_passes_census(git_repo):
    """A ledger record produced from a GitHub answer (the fixture's record)
    carries the new optional source field referencing the issue number and
    comment id, and the census accepts it (exit 0)."""
    repo, commit = git_repo
    fixture = _load_fixture("record-with-source.json")
    record = fixture["record"]

    # The source field references the tracker issue and comment.
    assert record["source"] == {"issue_number": 42, "comment_id": 9102}

    # The record's verdict/answer match the fixture's expected values.
    assert record["status"] == "decided"
    assert record["questions"][0]["answer"] == fixture["expected_answer"]

    # Commit the record to the fixture repo so the git-backed census checks
    # (edited, deleted, chain) run for real rather than skipping.
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / f"{record['id']}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    commit({f"noni/decisions/{record['id']}.json": (ledger / f"{record['id']}.json").read_text()}, "record")

    import subprocess

    proc = subprocess.run(
        ["python3", str(REPO / "skills" / "census" / "scripts" / "census.py"), "--repo", str(repo), "--now", "2026-10-02T12:00:00Z"],
        capture_output=True,
        text=True,
        timeout=60,
        env=dict(os.environ),
    )
    # Exit 0: the record is schema-valid (the source field is admitted) and
    # the full census — schema, edited, deleted and chain checks — passes on
    # a real git repo (one root, one live record, nothing edited or deleted
    # post-commit).
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"


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
    matching is case-insensitive (documented behavior)."""
    loaded = adapter_protocol.Allowlist({"op-1"}, "active")
    assert "OP-1" in loaded
    assert "Op-1" in loaded
    assert "op-1" in loaded
    assert "op-2" not in loaded
    # is_allowed matches case-insensitively for both Allowlist and bare-set
    # shapes.
    assert adapter_protocol.is_allowed(loaded, "OP-1")
    assert adapter_protocol.is_allowed({"op-1"}, "Op-1")


def test_refused_allowlist_never_authorizes():
    """A refused (or absent) Allowlist authorizes nothing, even if an
    account string is present in its accounts attribute — the seam-facing
    decision is always negative when not active."""
    refused = adapter_protocol.Allowlist({"op-1"}, "refused", "symlink")
    assert "op-1" not in refused
    assert not refused
    assert not adapter_protocol.is_allowed(refused, "op-1")
    absent = adapter_protocol.Allowlist(set(), "absent")
    assert "op-1" not in absent
    assert not adapter_protocol.is_allowed(absent, "op-1")


# --- Malformed payloads never crash and never authorize ---------------------


def test_malformed_question_payload_never_authorizes():
    """Non-dict payloads, non-dict comments/edits, and missing/non-str
    actor or body fields all degrade to stranger / not-authorized rather
    than a crash or a false positive."""
    fixtures = [
        "not-a-dict.json",
        "comment-missing-actor.json",
        "comment-non-dict-edit.json",
        "comment-non-dict-user.json",
    ]
    for name in fixtures:
        payload = _load_fixture(name)
        v = adapter.question_legitimacy(payload, ALLOWED)
        assert v.verdict in ("stranger", "none"), f"{name}: {v.verdict!r} (malformed payload must not authorize)"
        assert v.answer is None


def test_malformed_label_payload_never_authorizes():
    """Malformed label payloads (non-dict events, non-str actor, non-dict
    label, non-str label name) are never authorized and never raise."""
    for name in ("label-non-dict-event.json", "label-non-str-actor.json", "label-non-dict-label.json"):
        payload = _load_fixture(name)
        assert adapter.label_authorization(payload, ALLOWED) is False, name
    # A non-dict payload is also never authorized.
    assert adapter.label_authorization("not-a-dict", ALLOWED) is False

