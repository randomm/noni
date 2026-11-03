"""The bytes one registration writes, and the two values it stamps them with.

``register.py`` owns the rules: which names it may write, whose file it may not
overwrite, when the working copy is marked. This module holds only the product of
those rules once the decision has been made -- the session file's own text, and the
two values that go into it: the session id this run allocated and the instant it
allocated it.

The id is minted ONCE per run and threaded through every use of it (the name written,
the pathspec, the marker's contents, the commit subject, the printed line), because two
mints would let the printed id and the committed id disagree. The shape is
``<UTC date>-<6 hex chars>``: 16^6 is roughly 16.7M slots per day, so ids are
collision-free by construction and stable across pulls and clones once committed (see
``references/register.md``). The timestamp is the same UTC second, formatted the way
the sessions census reads it back.

The body's field lines are the grammar :mod:`noni._session_fields` reads; the writer
composes them and never parses them, so the two modules do not share code and cannot
drift into agreeing with each other by accident.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_utc() -> str:
    """The instant this run started, in the format the register file carries."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_session_id() -> str:
    """The session id this run owns: a UTC date and six hex characters."""
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}"


def session_body(session_id: str, identity: str, host: str, worktree: str,
                 started: str, status: str) -> str:
    """The full text of a register file for one new session.

    The field lines are written in the order the census and the writers' own readers
    expect; ``claims`` is left empty because a registration claims nothing -- that is
    ``claim.py``'s work, and it appends rather than rewriting this header.
    """
    return (f"# session {session_id}\n\n"
            f"- identity: {identity}\n"
            f"- host/worktree: {host} ({worktree})\n"
            f"- started: {started}\n"
            f"- status: {status}\n"
            f"- claims:\n")
