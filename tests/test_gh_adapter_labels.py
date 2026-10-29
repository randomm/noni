"""The GitHub-issues adapter's label seam: who applied the label, not that it is there.

Label authorization reads the account behind the label event, not the label's
presence: a stranger-applied label present on the issue is unauthorized, and an
allow-listed-applied label a stranger later removed stays authorized (and is
genuinely removed in that fixture). A label with no recorded labeled event has
no evidence of an allow-listed applier, so it is unauthorized in every
allow-list state. Malformed payloads degrade to False rather than raising.

Fixtures are synthetic-only and read offline (see gh_adapter_support).
"""

from __future__ import annotations

from gh_adapter_support import ALLOWED, _load_fixture, adapter, adapter_protocol


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


def test_malformed_label_payload_never_authorizes():
    """Malformed label payloads (non-dict events, non-str actor, non-dict
    label, non-str label name) are never authorized and never raise."""
    for name in ("label-non-dict-event.json", "label-non-str-actor.json", "label-non-dict-label.json"):
        payload = _load_fixture(name)
        assert adapter.label_authorization(payload, "steer", ALLOWED) is False, name
    # A non-dict payload is also never authorized.
    assert adapter.label_authorization("not-a-dict", "steer", ALLOWED) is False
