"""The bytes one registration writes, and the two values it stamps them with.

``register.py`` owns the rules: which names it may write, whose file it may not
overwrite, when the working copy is marked. This module holds only the product of
those rules once the decision has been made -- the session file's own text, and the
two values that go into it: the session id this run allocated and the instant it
allocated it.

The id is minted ONCE per run and threaded through every use of it (the name written,
the pathspec, the marker's contents, the commit subject, the printed line), because two
mints would let the printed id and the committed id disagree. The shape is
``<UTC date>-<6 hex chars>``: 16^6 is roughly 16.7M slots per UTC day, which makes a
collision rare but not impossible, so ``register`` tests the name it mints against the
filesystem and mints again when it is taken, up to :data:`ALLOCATION_RETRIES` times
before it refuses. Ids are stable across pulls and clones once committed (see
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


# How many names the allocating route mints before it reports a taken name: the
# first allocation plus this many re-mints. A real 24-bit collision is rarer than one
# run in a hundred thousand, so the bound is there to end a pathological run (every
# name in the day's space held, or an allocator pinned to one id), not to be tuned;
# it lives beside the allocator so the retry and the mint are read together.
ALLOCATION_RETRIES = 3


def make_session_id() -> str:
    """The session id this run owns: a UTC date and six hex characters.

    The shape the census's ``SESSION_NAME_RE`` accepts, ``<YYYY-MM-DD>-<6 hex>``.
    Six hex characters are 16^6 slots per UTC day, which is roomy rather than
    collision-resistant: ids are compared, not trusted -- ``register`` checks the name
    this mints against the filesystem and mints again on the rare collision (see
    ``noni.register`` and ``references/register.md``).
    """
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
