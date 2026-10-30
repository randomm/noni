"""The GitHub-issues adapter's question seam and its ledger record, on fixtures.

All fixtures under tests/fixtures/gh-adapter/ are synthetic-only (synthetic
users, synthetic repos) and are read offline: the adapter's two seams are
pure functions of (payload, allow-list), so no test touches the network.

Covered (per the ticket's test surface):
- single tick by an allow-listed last-editor  -> verdict "one"
- zero ticks                                  -> verdict "none"
- two+ ticks                                  -> verdict "many"
- tick by a non-allow-listed account          -> verdict "stranger"
- last-editor-wins: allow-listed first then stranger last -> "stranger";
  stranger first then allow-listed last -> "one"
- the ledger record the adapter's output becomes carries the new optional
  source field and passes the census.
"""

from __future__ import annotations

import json
import subprocess
import sys

from _harness import subprocess_env
from gh_adapter_support import ALLOWED, REPO, _load_fixture, adapter

# --- Interface conformance ----------------------------------------------------

def test_adapter_implements_the_interface():
    """The GitHub-issues adapter structurally satisfies the two-seam
    interface (check_interface finds no problems)."""
    from gh_adapter_support import adapter_protocol

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
