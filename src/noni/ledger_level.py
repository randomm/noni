"""The ledger schema's level, and the declaration an attached project commits.

The symptom this module exists for: a writer newer than the census its project's
CI pins emits a field the pinned census does not declare, and the record reads
back at exit 10 hours later, in a red run, with nothing said at write time. The
level below is the writer's own answer to "which closed key set do I write"; a
project states the level its census runs in the file named here, and a run whose
writer is ahead of that number says so before it writes.

ONE integer, and bumping it is part of the change that changes the closed set in
``ledger_schema``: a field added to ``OPTIONAL_LEDGER_FIELDS`` without a bump here
is a record a pinned census refuses with nothing said at the writer, which is the
bug this constant was introduced to close. 1 is the level of today's set (the
required eight plus the four optional names).

"Newer" means exactly one comparison and no other: this writer's
:data:`LEDGER_SCHEMA_LEVEL` is greater than the declared integer. No string
version, no release tag, nothing fetched. A project with no declaration file
behaves exactly as it did before this module existed -- absence is the ordinary
answer, not a finding.

Nothing here prints or exits: :func:`read_schema_level` answers a level, nothing,
or :class:`DeclarationError`, and the two wording helpers hand back text for the
writer and the census to print in their own voice with their own codes.
"""

from __future__ import annotations

from pathlib import Path

from .census_json import load_json_strict

# The writer's own ledger schema level. See the module docstring for what bumping
# it means and when.
LEDGER_SCHEMA_LEVEL = 1

# The declaration's key, and the only value it may hold: an integer at or above
# the first level, never a bool (Python calls ``True`` an ``int``, and json's
# ``true`` declares no level). The comparison every caller makes is the plain
# integer one: this writer's ``LEDGER_SCHEMA_LEVEL`` against the declared N.
SCHEMA_LEVEL_KEY = "schema_level"

# The number a declaration may go down to. 0 is a real answer and not a malformed
# one: it is a census pinned before the level existed, or one whose maintainer says
# plainly "my census is older than the first declared set". Refusing it would turn
# the exact project this check exists for into a usage error, so the floor of the
# range is 0 and the comparison a writer makes stays the plain integer one.
SCHEMA_LEVEL_FLOOR = 0

# The declaration's path under the state root: a sibling of ``decisions/``, never
# inside it, so the ledger probe's ``*.json`` listing never counts it as a record.
# The file is committed by whoever pins the census, and a writer never creates it.
# A ``--ledger`` override moves the ledger and not this file: the declaration
# belongs to the state root, which is the tree whose census is being pinned.
SCHEMA_LEVEL_DIR = "noni/direction"
SCHEMA_LEVEL_FILE = "census-level.json"
SCHEMA_LEVEL_REL = f"{SCHEMA_LEVEL_DIR}/{SCHEMA_LEVEL_FILE}"


class DeclarationError(Exception):
    """A declaration file that answers nothing, and why it could not.

    Raised by :func:`read_schema_level` for every shape that is not "no
    declaration": bytes that are not readable JSON, a document that is not an
    object, a missing or non-integer ``schema_level``, a path that is a link or a
    directory or a position the filesystem declined to describe, and a read that
    faulted. ``why`` is the reason in plain words and quotes no content from the
    file, so a caller may print it. Absence is not this -- absence is ``None``.
    """

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def read_schema_level(root: Path) -> int | None:
    """The census level ``root`` declares, or None when it declares none.

    One file, one key, read strictly: :func:`noni.census_json.load_json_strict` is
    the reader every other noni JSON document goes through, so a declaration
    holding a literal no writer emits is refused rather than believed, and
    :class:`DeclarationError` is raised for everything that is not "no file". A
    caller that must not write on an answer it could not get fails closed on that
    exception; a caller that only reports treats it as "nothing declared" and says
    nothing.

    The file is a sibling of ``decisions/``, so it is read by path and never
    through the ledger probe's listing, and it is never followed through a link:
    the ``lstat`` question is :func:`noni._path_kind.inspected_file_kind`, the same
    one every other guard in the family asks, so a link, a directory or a device
    standing at the path is a refusal and not an absence.
    """
    from . import _path_kind

    path = root / SCHEMA_LEVEL_REL
    refused = _path_kind.inspected_file_kind(path)
    if refused is not None:
        raise DeclarationError(f"{SCHEMA_LEVEL_REL} {refused}")
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DeclarationError(
            f"{SCHEMA_LEVEL_REL} could not be read "
            f"({exc.__class__.__name__}: {exc.strerror or exc})") from exc
    try:
        value = load_json_strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise DeclarationError(
            f"{SCHEMA_LEVEL_REL} is not readable JSON "
            f"({exc.__class__.__name__})") from exc
    if not isinstance(value, dict):
        raise DeclarationError(f"{SCHEMA_LEVEL_REL} is not a JSON object")
    level = value.get(SCHEMA_LEVEL_KEY)
    if not isinstance(level, int) or isinstance(level, bool) or level < SCHEMA_LEVEL_FLOOR:
        raise DeclarationError(
            f'{SCHEMA_LEVEL_REL} must hold "{SCHEMA_LEVEL_KEY}" as an integer of '
            f"{SCHEMA_LEVEL_FLOOR} or more")
    return level


def schema_level_skew(writer_level: int, declared: int) -> tuple[str, str]:
    """The (headline, hint) pair a writer prints when it is newer than the census.

    Both numbers are in the headline and the fix names both directions of the
    repair, because either half of the pair may be the one that is out of date:
    the project can upgrade its census to this noni, or the writer can go back to
    the commit that census was pinned at. Nothing is quoted from the declaration
    file beyond the integer it declares.
    """
    return (f"this writer is at ledger schema level {writer_level}, ahead of the "
            f"level {declared} that {SCHEMA_LEVEL_REL} declares: a record this run "
            "writes could carry a field the census at that level reports as an "
            "unknown field",
            f"upgrade the census pin to this noni (level {writer_level}), or run "
            f"the writer at the commit the census at level {declared} is pinned at")


def declaration_refusal(why: str) -> tuple[str, str]:
    """The (headline, hint) pair for a declaration that answered nothing.

    The writer's fail-closed answer: a file it cannot read says nothing about the
    census it was meant to describe, so the run refuses rather than writing on the
    uncertainty. ``why`` is :attr:`DeclarationError.why` -- this module's own
    words about the file's path and its shape, never its content -- and the hint
    states the one shape that is read.
    """
    return (why, f'repair or remove {SCHEMA_LEVEL_REL}, or write it as '
            f'{{"{SCHEMA_LEVEL_KEY}": N}} with N an integer of '
            f'{SCHEMA_LEVEL_FLOOR} or more')


def unknown_field_cause(level: int) -> str:
    """The clause a census row appends when it refuses a field it does not declare.

    An unknown field is what a record from a newer writer looks like to an older
    census, and that is the fact the row used to leave out. The clause names the
    level this census runs at and the one act that clears it, so the reader is not
    left to arrive at the cause from scratch. The row's own "unknown field(s)"
    sentence is untouched, so a caller that matched the fault keeps matching it.
    """
    return (f"a record from a newer noni than this census "
            f"({SCHEMA_LEVEL_KEY} {level}) shows as an unknown field: upgrade the "
            "census pin to the writer's noni")
