"""The GitHub-issues adapter: both adapter interface seams, fixture-driven.

Implements the two-seam interface documented in ``integrations/README.md``
and ``integrations/adapter_protocol.py`` for GitHub issues:

- **Question legitimacy.** A steering question is an **issue comment with
  checkbox options**. The payload is the comment together with its edit
  history (the timeline), because the legitimacy rule is about *who made the
  comment's last edit*, not who is allowed to read the comment.
  The verdict is ``one`` / ``none`` / ``many`` / ``stranger``:

    * ``one``      exactly one option ticked in the comment's last state, and
                   the comment's last edit was made by an allow-listed
                   account;
    * ``none``     no option ticked;
    * ``many``     more than one option ticked (ambiguous — not an answer);
    * ``stranger`` the comment's last edit was made by an account not on
                   the allow-list (a foreign edit voids the reply — the
                   last editor wins, not the first).

  A ticked comment edited later by anyone is re-evaluated on that edit: the
  "comment's last edit" is the latest timeline event that changed the
  comment, and it is that event's account that must be allow-listed.

- **Label authorization.** The payload is the issue (with its labels) plus
  the issue's timeline events. The check reads **the account behind the label
  event, not the label's presence**: for each label present on the issue it
  finds the latest label event, and the label is authorized only when that
  event's actor is on the allow-list. A label applied by a stranger is
  unauthorized even though it is present on the issue; a label applied by an
  allow-listed account stays authorized if a stranger later removes it (the
  removal is a different event; authorization is about who applied it).

The allow-list comes from local configuration only (an untracked file or an
env var, via ``adapter_protocol.load_allowlist``) — never hard-coded.

Payload shapes (the GitHub REST API's JSON, recorded offline as fixtures —
see ``tests/fixtures/gh-adapter/``):

  question payload (a comment with its edit timeline)::

    {
      "comment": {
        "id": 47,
        "body": "q1: ...\n  [x] yes\n  [ ] no",
        "user": {"login": "op-1"}
      },
      "edits": [                       # timeline events, oldest first
        {"actor": "op-1", "edited_at": "2026-10-01T10:00:00Z",
         "new_body": "q1: ...\n  [ ] yes\n  [ ] no"},
        {"actor": "op-1", "edited_at": "2026-10-01T10:05:00Z",
         "new_body": "q1: ...\n  [x] yes\n  [ ] no"}
      ]
    }

  label payload (an issue with its labels and timeline)::

    {
      "issue": {"labels": [{"name": "steer"}]},
      "events": [
        {"event": "labeled", "actor": "op-1", "label": "steer",
         "created_at": "2026-10-01T10:00:00Z"}
      ]
    }

Both seams are pure functions of (payload, allow-list): the adapter does
no I/O itself, so every test runs offline against recorded JSON fixtures.
"""

from __future__ import annotations

import re

# Import the shared contract and the allow-list loader from the sibling
# integrations module (no package; tests insert integrations/ on sys.path —
# the same pattern every noni script uses).
from adapter_protocol import (  # noqa: E402
    VERDICT_MANY,
    VERDICT_NONE,
    VERDICT_ONE,
    VERDICT_STRANGER,
    QuestionVerdict,
)

#: The env var naming an alternative allow-list file (mirrors the scrub's
#: NONI_SCRUB_DENYLIST pattern). The untracked file at the repo root takes
#: precedence when it exists; the env-var-named file is the fallback.
ALLOWLIST_ENV_VAR = "NONI_ADAPTER_ALLOWLIST"

_TICKED_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(.+)$", re.MULTILINE)


def default_allowlist_file() -> str:
    """Path of the default (untracked) allow-list file: the repo root's
    ``.noni-adapter-allowlist``. The path is in .gitignore, so the file can
    never be committed — the same pattern as the scrub's deny-list.
    """
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / ".noni-adapter-allowlist")


def _ticked_options(body: str) -> list[str]:
    """The option labels ticked in a checkbox-comment body.

    A ticked option is a line ``- [x] label`` (or ``* [x]``, case-insensitive
    ``x``). Unticked options (``[ ]``) are not counted. Duplicate ticks of
    the same label are collapsed (the same option cannot be ticked twice).
    """
    seen: list[str] = []
    for match in _TICKED_RE.finditer(body):
        label = match.group(1).strip()
        if label and label not in seen:
            seen.append(label)
    return seen


def _last_state(payload: dict) -> tuple[str, str]:
    """The (body, actor) of the comment's last state.

    If the payload carries an edit history, the last edit's ``new_body`` and
    actor define the current state (the comment's own body is the same
    content; the history is what carries *who* set it last). Without a
    history the comment's own body and user are the last state (no edits
    means the author wrote it once).
    """
    comment = payload.get("comment", {})
    edits = payload.get("edits", [])
    if edits:
        last = edits[-1]
        return last.get("new_body", ""), last.get("actor", "")
    return comment.get("body", ""), comment.get("user", {}).get("login", "")


def question_legitimacy(payload: dict, allowlist: set[str]) -> QuestionVerdict:
    """Question-legitimacy seam.

    Returns the operator's answer (when the steer is legitimate) and the
    verdict. A steer is legitimate (``one``) iff exactly one option is
    ticked in the comment's last state and the comment's last edit was made
    by an allow-listed account.
    """
    body, actor = _last_state(payload)
    options = _ticked_options(body)

    if len(options) == 0:
        return QuestionVerdict(VERDICT_NONE, None)
    if len(options) > 1:
        return QuestionVerdict(VERDICT_MANY, None)

    answer = options[0]
    if actor in allowlist:
        return QuestionVerdict(VERDICT_ONE, answer)
    return QuestionVerdict(VERDICT_STRANGER, None)


def label_authorization(payload: dict, allowlist: set[str]) -> bool:
    """Label-authorization seam.

    Returns True iff every label present on the issue was *applied* by an
    allow-listed account. The check reads the account behind the label
    event (the latest ``labeled`` event for that label in the timeline), not
    the label's presence: a present label whose application actor is not
    allow-listed is unauthorized, and a label applied by an allow-listed
    account stays authorized if someone later removes it (removals are
    ``unlabeled`` events and do not re-attribute the application).
    """
    labels = {label.get("name") for label in payload.get("issue", {}).get("labels", []) if label.get("name")}
    if not labels:
        # No labels present: nothing to authorize, and nothing unauthorized.
        return True

    events = payload.get("events", [])
    for label in sorted(labels):
        applied_by: list[str] = []
        for event in events:
            if event.get("event") == "labeled" and event.get("label") == label:
                applied_by.append(event.get("actor", ""))
        # No recorded application event for a present label: cannot verify the
        # actor, so it is not authorized (the read is about the event, not the
        # presence — no event means no evidence of an allow-listed applier).
        if not applied_by:
            return False
        if applied_by[-1] not in allowlist:
            return False
    return True
