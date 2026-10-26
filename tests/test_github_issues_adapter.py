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
from _harness import subprocess_env  # noqa: E402

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


# --- Label authorization ------------------------------------------------------

def test_label_applied_by_allowlisted_account_is_authorized():
    """A label present on the issue, applied by an allow-listed account, is
    authorized (it reads the account behind the label event)."""
    payload = _load_fixture("label-authorized.json")
    assert adapter.label_authorization(payload, "steer", ALLOWED) is True


def test_label_applied_by_stranger_is_unauthorized_even_if_present():
    """A label present on the issue but applied by a non-allow-listed
    account is unauthorized: the presence is not the evidence — the label
    event's actor is."""
    payload = _load_fixture("label-stranger.json")
    assert adapter.label_authorization(payload, "steer", ALLOWED) is False


def test_label_applied_by_allowlisted_then_removed_stays_authorized():
    """A label applied by an allow-listed account stays authorized if a
    stranger later removes it: the fixture is genuinely removed (the
    issue's labels list does not name it) and authorization is about who
    applied it, not who removed it (and not whether it is still present)."""
    payload = _load_fixture("label-authorized-then-removed.json")
    # The fixture is genuinely removed: the label is no longer on the issue.
    assert payload["issue"]["labels"] == []
    assert adapter.label_authorization(payload, "steer", ALLOWED) is True


def test_label_with_no_recorded_application_event_is_unauthorized():
    """A label with no recorded labeled event has no evidence of an
    allow-listed applier: unauthorized, even though the label is present
    on the issue (presence is not the evidence)."""
    payload = {
        "issue": {"labels": [{"name": "steer"}]},
        "events": [{"event": "opened", "actor": "agent-synthetic", "created_at": "2026-10-06T09:00:00Z"}],
    }
    assert adapter.label_authorization(payload, "steer", ALLOWED) is False


def test_label_present_with_no_events_is_unauthorized_in_every_allowlist_state():
    """A label present on the issue but whose timeline has no labeled
    event: False, and it stays False in every allow-list state (active,
    absent, refused, active-but-empty)."""
    payload = {"issue": {"labels": [{"name": "steer"}]}, "events": []}
    # active (the test's bare set)
    assert adapter.label_authorization(payload, "steer", ALLOWED) is False
    # absent
    assert adapter.label_authorization(payload, "steer", adapter_protocol.Allowlist(set(), "absent")) is False
    # refused
    assert (
        adapter.label_authorization(payload, "steer", adapter_protocol.Allowlist(set(), "refused", "symlink")) is False
    )
    # active but empty
    assert adapter.label_authorization(payload, "steer", set()) is False


def test_malformed_payload_non_dict_issue_is_unauthorized():
    """A non-dict issue is malformed: unauthorized, never a crash."""
    payload = {"issue": "not-a-dict", "events": [{"event": "labeled", "actor": "op-1", "label": "steer"}]}
    assert adapter.label_authorization(payload, "steer", ALLOWED) is False


def test_label_name_comparison_is_case_insensitive():
    """Label names compare case-insensitively on both sides: the requested
    label 'Steer' matches a 'steer' labeled event and vice versa."""
    payload = {
        "issue": {"labels": [{"name": "Steer"}]},
        "events": [{"event": "labeled", "actor": "op-1", "label": "steer", "created_at": "2026-10-01T10:00:00Z"}],
    }
    assert adapter.label_authorization(payload, "Steer", ALLOWED) is True
    inverted = {
        "issue": {"labels": [{"name": "steer"}]},
        "events": [{"event": "labeled", "actor": "op-1", "label": "Steer", "created_at": "2026-10-01T10:00:00Z"}],
    }
    assert adapter.label_authorization(inverted, "steer", ALLOWED) is True
    # Case-insensitivity does not reach across different labels.
    different = {
        "issue": {"labels": [{"name": "Steer"}]},
        "events": [{"event": "labeled", "actor": "op-1", "label": "other", "created_at": "2026-10-01T10:00:00Z"}],
    }
    assert adapter.label_authorization(different, "Steer", ALLOWED) is False


def test_label_on_issue_with_several_labels_is_decided_by_that_labels_events():
    """An issue with several labels: asking about the second one is decided
    by that label's own timeline events, not by the first label's. The
    first label's application is by a stranger, the second's by an
    allow-listed account (and vice versa), so the two answers differ."""
    payload = {
        "issue": {"labels": [{"name": "first"}, {"name": "second"}]},
        "events": [
            {"event": "opened", "actor": "agent-synthetic", "created_at": "2026-10-07T09:00:00Z"},
            {"event": "labeled", "actor": "stranger-1", "label": "first", "created_at": "2026-10-07T09:05:00Z"},
            {"event": "labeled", "actor": "op-1", "label": "second", "created_at": "2026-10-07T09:10:00Z"},
        ],
    }
    assert adapter.label_authorization(payload, "second", ALLOWED) is True
    assert adapter.label_authorization(payload, "first", ALLOWED) is False


def test_label_never_applied_is_unauthorized():
    """A label never applied (no labeled event for it, even though other
    labels were applied) is unauthorized: there is no evidence of an
    allow-listed applier for it."""
    payload = {
        "issue": {"labels": [{"name": "present"}]},
        "events": [
            {"event": "labeled", "actor": "op-1", "label": "other", "created_at": "2026-10-08T09:05:00Z"},
        ],
    }
    assert adapter.label_authorization(payload, "present", ALLOWED) is False


def test_empty_or_non_str_label_is_unauthorized():
    """An empty or non-str label argument names nothing to authorize:
    False even when the timeline has an allow-listed application of a
    label and the allow-list is active."""
    payload = {
        "issue": {"labels": [{"name": "steer"}]},
        "events": [{"event": "labeled", "actor": "op-1", "label": "steer", "created_at": "2026-10-01T10:00:00Z"}],
    }
    assert adapter.label_authorization(payload, "", ALLOWED) is False
    assert adapter.label_authorization(payload, None, ALLOWED) is False
    assert adapter.label_authorization(payload, 42, ALLOWED) is False


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
        [sys.executable, str(REPO / "skills" / "census" / "scripts" / "census.py"), "--repo", str(repo), "--now", "2026-10-02T12:00:00Z"],
        capture_output=True,
        text=True,
        timeout=60,
        env=subprocess_env(),
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


# --- Malformed payloads never crash and never authorize ---------------------


def test_malformed_question_payload_never_authorizes():
    """Non-dict payloads, non-dict comments/users, and missing/non-str
    actor or body fields all degrade to stranger (the last state carries a
    ticked option but an empty/foreign actor) rather than a crash or a
    false positive."""
    for name in ("not-a-dict.json", "comment-missing-actor.json", "comment-non-dict-user.json"):
        payload = _load_fixture(name)
        v = adapter.question_legitimacy(payload, ALLOWED)
        # A malformed state yields either none (no ticked option survives —
        # not-a-dict payload, non-dict user) or stranger (a ticked option
        # survives but the actor is missing/foreign); never a tick answer.
        assert v.verdict in ("stranger", "none"), f"{name}: {v.verdict!r} (malformed payload must not authorize)"
        assert v.answer is None


def test_malformed_non_dict_edit_yields_none():
    """A non-dict edit in the history is malformed: the adapter consults only
    the LAST edit in the timeline (a valid dict here), so the bare-string
    entry at the front is never read and never crashes the seam. The last
    state's body uses bare '  [x]' checkbox lines (no dash/bullet prefix),
    which the tick regex does not match, so zero options are ticked and the
    verdict is none (not stranger) with no answer — a malformed timeline
    entry never crashes and never authorizes."""
    payload = _load_fixture("comment-non-dict-edit.json")
    assert not isinstance(payload["edits"][0], dict)
    v = adapter.question_legitimacy(payload, ALLOWED)
    assert v.verdict == "none", f"{v.verdict!r} (malformed edit history yields none, not stranger)"
    assert v.answer is None


def test_malformed_label_payload_never_authorizes():
    """Malformed label payloads (non-dict events, non-str actor, non-dict
    label, non-str label name) are never authorized and never raise."""
    for name in ("label-non-dict-event.json", "label-non-str-actor.json", "label-non-dict-label.json"):
        payload = _load_fixture(name)
        assert adapter.label_authorization(payload, "steer", ALLOWED) is False, name
    # A non-dict payload is also never authorized.
    assert adapter.label_authorization("not-a-dict", "steer", ALLOWED) is False

