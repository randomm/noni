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

- **Label authorization.** The payload is the issue plus the issue's
  timeline events, and the label itself is an explicit argument:
  ``label_authorization(payload, label, allowlist)``. The seam returns
  True iff an *authorized application* of that label is on record: the
  allow-list is active, and the latest ``labeled`` timeline event whose
  label name matches ``label`` (casefolded) names an allow-listed actor.
  It reads the account behind the label event, not the label's presence:
  a label currently absent from the issue still counts if it was applied
  by an allow-listed account (and later removed by anyone — the removal
  is a different event, not a new application), and a label present on
  the issue with no recorded ``labeled`` event — or one applied by a
  stranger — is not authorized. The label's current presence on the
  issue is irrelevant in every direction. The allow-list itself must be
  active: an absent or refused allow-list authorizes nothing. An
  empty or non-str ``label`` argument is never authorized.

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

  label payload (an issue with its timeline; the label asked about is
  passed as the seam's explicit argument)::

    {
      "issue": {"labels": [{"name": "steer"}]},
      "events": [
        {"event": "labeled", "actor": "op-1", "label": "steer",
         "created_at": "2026-10-01T10:00:00Z"}
      ]
    }

The question seam is a pure function of (payload, allow-list) and the
label seam of (payload, label, allow-list); the adapter does no I/O
itself, so every test runs offline against recorded JSON fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path

# Import the shared contract and the allow-list loader from the sibling
# integrations module (no package; tests insert integrations/ on sys.path —
# the same pattern every noni script uses).
import adapter_protocol
from adapter_protocol import (
    VERDICT_MANY,
    VERDICT_NONE,
    VERDICT_ONE,
    VERDICT_STRANGER,
    Allowlist,
    QuestionVerdict,
    is_allowed,
)

#: The env var naming an alternative allow-list file (mirrors the scrub's
#: NONI_SCRUB_DENYLIST pattern). The untracked file at the attached repository's
#: root takes precedence when it exists; the env-var-named file is the fallback.
ALLOWLIST_ENV_VAR = "NONI_ADAPTER_ALLOWLIST"

#: The untracked allow-list file's name, relative to the attached repository's
#: root. The adapter is a pure function of (payload, allow-list) and never
#: resolves a working directory itself, so the caller supplies that root.
ALLOWLIST_FILENAME = ".noni-adapter-allowlist"

_TICKED_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]\s*(.+)$", re.MULTILINE)


def default_allowlist_file(repo_root: str | Path | None) -> str | None:
    """Path of the default (untracked) allow-list file: ``repo_root``'s
    ``.noni-adapter-allowlist``.

    ``repo_root`` is the root of the repository noni is *attached to* — the one
    whose ``noni/`` state and tracker issues the adapter is reading — not this
    adapter's install directory. The caller resolves it; the adapter never
    guesses a working directory. It is accepted as a ``str`` or a ``Path``, so
    a caller that holds the root as a string (a path read from config, say) is
    not required to wrap it first. ``.gitignore`` names the file, so it can
    never be committed — the same pattern as the scrub's deny-list.

    Returns ``None`` when no usable root is given (``None``, an empty string,
    or a value that is neither ``str`` nor ``Path``): with no candidate file
    the loader consults only ``ALLOWLIST_ENV_VAR`` and otherwise reports the
    allow-list as ``absent``, so an unusable root fails closed rather than
    authorising from a wider default. ``None``, the empty string and any value
    that is neither ``str`` nor ``Path`` are all refused before ``Path`` sees
    them: ``Path("")`` is ``Path(".")``, a truthy relative path that would
    otherwise hand back a candidate resolved against whatever directory the
    caller happened to run in, and ``Path`` raises ``TypeError`` on a
    ``bytes``/``int``/``list`` — a helper whose contract is "no candidate" must
    return it, not crash.
    """
    if repo_root is None:
        return None
    if not isinstance(repo_root, (str, Path)):
        return None
    if not str(repo_root):
        # Path("") is Path("."): a truthy, relative, existing directory, which
        # is_dir() would wave through. Refuse it as what it is — no root.
        return None
    root = Path(repo_root)
    if not root.is_dir():
        return None
    return str(root / ALLOWLIST_FILENAME)


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


def _last_state(payload: object) -> tuple[str, str]:
    """The (body, actor) of the comment's last state.

    If the payload carries an edit history, the last edit's ``new_body`` and
    actor define the current state (the comment's own body is the same
    content; the history is what carries *who* set it last). Without a
    history (or a malformed history) the comment's own body and user are
    the last state (no edits means the author wrote it once).

    A malformed payload never crashes and never authorizes: a non-dict
    payload, a non-dict comment, a non-dict edit, or a missing/non-str
    actor or body yields an empty ("", "") — the empty actor is never on
    any allow-list, so the seam returns ``stranger``/not authorized rather
    than a crash or a false positive.
    """
    if not isinstance(payload, dict):
        return "", ""
    comment = payload.get("comment")
    comment = comment if isinstance(comment, dict) else {}
    edits = payload.get("edits")
    if isinstance(edits, list) and edits:
        last = edits[-1]
        if isinstance(last, dict):
            body = last.get("new_body")
            actor = last.get("actor")
            return (body if isinstance(body, str) else "", actor if isinstance(actor, str) else "")
    body = comment.get("body")
    body = body if isinstance(body, str) else ""
    user = comment.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    return body, (login if isinstance(login, str) else "")


def question_legitimacy(payload: dict, allowlist: set[str] | Allowlist) -> QuestionVerdict:
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
    if is_allowed(allowlist, actor):
        return QuestionVerdict(VERDICT_ONE, answer)
    return QuestionVerdict(VERDICT_STRANGER, None)


def label_authorization(payload: dict, label: str, allowlist: set[str] | Allowlist) -> bool:
    """Label-authorization seam.

    Given a label on an issue (the label is an explicit argument — it is
    never inferred from the issue's current label set), returns True iff
    the allow-list is **active** and the latest ``labeled`` timeline
    event whose label name casefold-equals ``label`` names an allow-listed
    actor — and False in every other state, in any allow-list state.

    The label's current presence on the issue is irrelevant: a label
    applied by an allow-listed account stays authorized if someone later
    removes it (the removal is a different event and does not re-attribute
    the application), and a label applied by a stranger is unauthorized
    whether or not it is still present.

    Fails closed in every state: an absent or refused allow-list
    authorizes nothing (there is no active allow-list to authorize the
    application), a label with no recorded ``labeled`` event has no
    evidence of an allow-listed applier, and an empty or non-str
    ``label`` argument names no label to authorize. Label names compare
    case-insensitively on both sides (tracker label names are
    case-insensitive in practice; the event and the requested label must
    name the same label).

    A malformed payload never crashes and never authorizes: a non-dict
    payload/event, a non-str label name or actor, or a missing
    label/event yields ``False`` — no evidence of an allow-listed
    applier means unauthorized, never an exception.
    """
    # An empty or non-str label argument names nothing to authorize.
    if not isinstance(label, str) or not label:
        return False

    # The allow-list must be active (an Allowlist carries its own status;
    # a bare set is active iff non-empty). An inactive allow-list
    # authorizes nothing, in any label state.
    if isinstance(allowlist, adapter_protocol.Allowlist):
        if not allowlist.authorized:
            return False
    else:
        if not allowlist:
            return False

    if not isinstance(payload, dict):
        return False

    # A non-dict issue is a malformed payload: unauthorized, never a crash.
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return False

    events = payload.get("events")
    events = events if isinstance(events, list) else []

    requested = label.casefold()

    # The latest ``labeled`` event for the requested label (label names
    # compare case-insensitively). The timeline is oldest-first, so the
    # last matching event is the latest application; an application with
    # a missing/non-str actor is recorded as "" so it can never match.
    latest_actor: str | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("event") != "labeled":
            continue
        event_label = event.get("label")
        if not isinstance(event_label, str) or not event_label:
            continue
        if event_label.casefold() != requested:
            continue
        actor = event.get("actor")
        latest_actor = actor if isinstance(actor, str) else ""

    if latest_actor is None:
        return False
    return is_allowed(allowlist, latest_actor)
