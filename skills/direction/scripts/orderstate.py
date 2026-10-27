"""The state this writer reads before it plans a write: the artifact and the ledger.

Mechanics, not the writer's contract: how a path is classified, what the order
file at ``noni/direction/order.json`` holds, and what a decision record under
``noni/decisions/`` may be cited for. ``order.py`` owns the verbs, the exit
codes and the commit; this module owns the reads, so each file stays the size
one responsibility is worth and the two halves are loaded by path from the same
directory.

Nothing here prints, writes, or decides an exit code on its own: every answer
travels back to the writer as a value or as a refusal the caller turns into one
of the codes ``order.py`` names. The exit codes are received as parameters for
that reason — one table, one owner, no second copy here that could drift.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# A decision record id is what decide.py writes: <YYYY-MM-DD>-<slug> of
# lowercase letters, digits and dashes. The same shape both directions, so a
# name that could escape the ledger directory is refused before any path is
# built from it.
DECISION_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*")
DECISIONS_DIR = "noni/decisions"
STATUS_SUPERSEDED = "superseded"

# The three status words a decision record may hold. An id whose record carries
# any other word answers nothing about the chain, so it is refused like an
# unreadable record: a hand-edited status must not decide an ordering.
STATUSES = ("decided", "open", "superseded")


def load_sibling(script_dir: Path, name: str, file: str):
    """The module ``file`` beside ``script_dir``, loaded by path under ``name``.

    A sys.path entry would put a directory ahead of the standard library, where
    any module of the same name earlier on that path could be trusted as this
    writer's own; loading by path with a name of our own is what closes that.
    The module is registered under ``name`` before exec (the canonical importlib
    recipe), so a module body that imports itself finds its own entry.
    """
    spec = importlib.util.spec_from_file_location(
        name, Path(script_dir).resolve() / file)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load {file} beside order.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Resolved at import from this module's own directory, so the reader is always
# the schema file that sits beside the writer that loaded this one.
orderschema = load_sibling(Path(__file__).resolve().parent, "noni_orderschema",
                           "orderschema.py")


def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print a refusal as a headline plus a 'fix:' line naming what resolves it,
    and hand back the exit code. One shape for every refusal in this writer."""
    label = f"{Path(__file__).name}:"
    print(label, message, file=sys.stderr)
    if hint:
        print(label, "fix:", hint, file=sys.stderr)
    return code


def now_iso(value: str | None) -> tuple[str, str | None]:
    """(timestamp, problem): the run's clock, or the --now the caller fixed.

    Both are normalised to a UTC second-resolution stamp, so what lands in the
    file and what the census compares against have one shape. A malformed
    --now is a usage error: a run that silently used the clock instead would
    report a confirmed time it did not say it used.
    """
    if value is None:
        stamp = datetime.now(timezone.utc)
    else:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "", f"--now {value!r} is not a valid ISO-8601 timestamp"
        if stamp.tzinfo is None:
            return "", f"--now {value!r} carries no UTC offset (pass e.g. 2026-10-27T09:00:00Z)"
        stamp = stamp.astimezone(timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), None


def file_kind(path: Path) -> tuple[str, str | None]:
    """Classify a path for this writer: ("absent"|"regular"|"dir"|"refusal", why).

    Only a regular, non-symlinked file is readable. A link or any other
    non-regular entry is refused, never opened: reading through a link puts a
    file outside the tree into the writer's decisions, and writing onto one
    replaces somebody's link with an order file. A directory is reported as
    itself rather than as a generic refusal, because the two callers ask
    differently: for the ledger an empty directory is a readable answer ('no
    records'), for the artifact it is a fault.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return "absent", None
    if stat.S_ISLNK(mode):
        return "refusal", ("the path is a symlink; this writer does not read or "
                          "write through links")
    if stat.S_ISDIR(mode):
        return "dir", None
    if not stat.S_ISREG(mode):
        return "refusal", "the path is not a regular file"
    return "regular", None


class OrderOk(NamedTuple):
    # The order this writer may extend, plus the bytes on disk (None when the
    # path is absent, which is the state the first add writes into).
    entries: list
    before: bytes | None


class OrderRefused(NamedTuple):
    # Why this run may not write: a headline and the fix that resolves it.
    headline: str
    hint: str


class OrderFaulted(NamedTuple):
    # The artifact's path could not be read as a file at all (a symlink, a
    # directory, an unreadable regular file), or a git call hung: the
    # environment, not the order.
    headline: str
    hint: str


class RenderRefused(NamedTuple):
    # The plan could not be turned into the bytes this writer commits. Every
    # value in a plan is validated before it gets here, so this is the writer's
    # own bug rather than the operator's; the artifact is left exactly as it was
    # and nothing is claimed as committed.
    headline: str
    hint: str


def render(body: dict) -> bytes | RenderRefused:
    """The canonical bytes for ``body``, or the refusal naming why none exist."""
    try:
        return orderschema.order_bytes(body)
    except ValueError:
        return RenderRefused("the planned order cannot be written as JSON",
                             "re-run order.py; if it repeats, rebuild the order from "
                             "order.py add after removing the artifact")


def body_of(value: dict) -> dict:
    """The {schema, entries} mapping a parsed artifact holds, in canonical key order."""
    return {"schema": value["schema"], "entries": value["entries"]}


def read_order(path: Path) -> OrderOk | OrderRefused | OrderFaulted:
    """The order ``path`` holds, or the refusal naming why this run may not write.

    Absent is not a refusal: an empty order is what the first ``add`` extends.
    Anything else at the path that this writer would render differently is
    refused (exit 4) rather than overwritten, because destroying an order the
    operator committed is worse than refusing the run.
    """
    kind, why = file_kind(path)
    if kind == "absent":
        return OrderOk([], None)
    if kind == "dir":
        # A directory at the artifact path is not an empty order: nothing was
        # read, so this run may not write. The wording names the shape the
        # caller has to remove, which is not the fix for broken contents.
        return OrderFaulted(f"{orderschema.ORDER_REL} is not a regular file: a directory "
                            "sits at that path",
                            f"remove the directory at {orderschema.ORDER_REL}, then "
                            "re-run order.py")
    if kind == "refusal":
        # An environment fault, not a refusal of the order: nothing is wrong
        # with the ordering, this run cannot reach it. A caller who fixes the
        # path re-runs the same command; a caller who repairs the artifact's
        # contents does not, and the two are different work.
        return OrderFaulted(f"{orderschema.ORDER_REL} {why}",
                            "remove that path or point --repo at the tree that holds "
                            "the order, then re-run order.py")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return OrderFaulted(f"{orderschema.ORDER_REL} could not be read "
                            f"({exc.__class__.__name__}: {exc.strerror or exc})",
                            f"check that {orderschema.ORDER_REL} is readable, then "
                            "re-run order.py")
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        # The shared strict reader: the three literals no noni writer emits and
        # the depth bound, all of them ValueError. RecursionError is named because
        # it is no kind of ValueError: the bound answers for a document between it
        # and the interpreter's own ceiling, but past that ceiling the decoder
        # raises first (on 3.11 that ceiling sits just under the recursion limit,
        # about 990 levels at the default 1000), so the arm is reachable there and
        # a reader without it would die here instead of refusing the file. No text
        # from the file reaches the operator.
        return OrderRefused(f"{orderschema.ORDER_REL} is not valid JSON this writer can "
                            "extend",
                            f"repair the file (it must hold {orderschema.ORDER_SCHEMA}) "
                            f"or remove it and rebuild the order with order.py add")
    found = orderschema.problems(value)
    if found:
        return OrderRefused(f"{orderschema.ORDER_REL} is not an order this writer writes: "
                            + "; ".join(found),
                            f"repair the file to the documented shape "
                            f"({orderschema.ORDER_SCHEMA}) or remove it and rebuild the "
                            f"order with order.py add")
    # Render the parsed value and compare bytes: a file this writer did not
    # produce is refused rather than reformatted. A renderer that cannot render
    # its own validated output is the writer's own bug, not a property of the
    # file, so a broken renderer cannot make a canonical file look malformed:
    # the canonical comparison is skipped in that case and the plan's own
    # render step reports the fault.
    canonical = render(body_of(value))
    if not isinstance(canonical, RenderRefused) and canonical != raw:
        return OrderRefused(f"{orderschema.ORDER_REL} is not in the canonical form this "
                            "writer writes (its keys, their order or its indent)",
                            "have order.py write it, or repair and commit it in that "
                            "form, then re-run order.py")
    return OrderOk(value["entries"], raw)


def read_record(path: Path, exit_io: int, exit_refusal: int
                ) -> tuple[dict, None] | tuple[None, tuple[int, tuple[str, str]]]:
    """The decision record at ``path``, or the (code, (headline, hint)) refusal.

    The two codes travel with the refusal because the two ways a lookup fails
    are different kinds of failure: the record is not there (the caller's
    refusal code) and the record could not be read (the caller's I/O code). See
    :func:`decision_problems`.
    """
    rel = f"{DECISIONS_DIR}/{path.name}"
    kind, why = file_kind(path)
    if kind == "absent":
        return None, (exit_refusal,
                      (f"no decision record {rel} is in the ledger",
                       "name the record that set the position, or add it with the "
                       "steering-ledger writer first"))
    if kind != "regular":
        return None, (exit_io,
                      (f"the decision record {rel} is not readable: "
                       f"{why or 'not a regular file'}",
                       "repair or remove that path, or name a decision record that is "
                       "there"))
    try:
        raw = path.read_bytes()
    except OSError:
        # The name is the record's own path relative to the repo, so no
        # machine-local absolute path reaches the message.
        return None, (exit_io,
                      (f"the decision record {rel} could not be read",
                       "check that the ledger is readable, or name a different "
                       "--decision"))
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        # As for the artifact: one strict reader for both files this writer reads
        # but did not write, and the wording names no content from either.
        return None, (exit_io,
                      ("the decision record is not readable JSON",
                       "repair the record or name a different --decision"))
    if not isinstance(value, dict):
        return None, (exit_io,
                      ("the decision record is not a JSON object",
                       "name a record that holds a record, not a list or a bare value"))
    return value, None


def ledger_is_readable(repo: Path) -> bool:
    """Whether the ledger path is a directory the writer may look in.

    Path.is_dir follows a symlink and answers yes for a link to a directory,
    which is what this writer refuses elsewhere: reading through a link puts a
    tree outside the repo into the writer's decisions. lstat and S_ISDIR ask
    the question actually meant, is the ledger path itself a directory, and a
    link, a plain file or a device all answer no, so the run says it could not
    look rather than reporting an absence it did not observe.
    """
    try:
        return stat.S_ISDIR(os.lstat(repo / DECISIONS_DIR).st_mode)
    except OSError:
        # Absent is not a fault: an absent ledger answers 'that id is not here'.
        return True


def decision_problems(repo: Path, decision: str, exit_io: int, exit_refusal: int
                      ) -> tuple[int, str, str] | None:
    """The (code, headline, hint) refusal for a ``decision`` id this order may
    not cite, or None when the record it names is a record whose ordering stands.

    The code is part of the answer because a failed lookup is two different
    failures: the record is not there (the caller's refusal code, so the caller
    names another record) and the ledger could not be looked in (the caller's
    I/O code, so the caller fixes the tree). Collapsing them would make an
    unreadable ledger read as an ordering the operator should change.

    A decision record is identified by the filename stem of
    ``noni/decisions/<id>.json``, the path decide.py names its records by, so
    one file carrying the id is the whole answer.
    """
    path = repo / DECISIONS_DIR / f"{decision}.json"
    if not DECISION_ID_RE.fullmatch(decision):
        # A name the writer never produces cannot be a record, and building a
        # path from it is not worth the risk: same answer as no such file.
        return (exit_refusal,
                f"decision {decision!r} matches no record file under {DECISIONS_DIR}/",
                "name the record that set the position, in the form "
                "YYYY-MM-DD-<slug>; the census report lists the ledger's records")
    if not ledger_is_readable(repo):
        return (exit_io,
                f"the decision ledger {DECISIONS_DIR}/ could not be looked in: it is not "
                "a readable directory",
                "restore the ledger directory, then re-run order.py, or order without "
                "--decision if no record set this position")
    found = read_record(path, exit_io, exit_refusal)
    if found[0] is None:
        assert found[1] is not None
        code, (headline, hint) = found[1]
        return (code, headline, hint)
    record = found[0]
    status = record.get("status")
    if status not in STATUSES:
        return (exit_refusal,
                f"the decision record {decision} carries status {status!r}, not one of "
                + ", ".join(STATUSES),
                "the census is the arbiter of the ledger: repair the record's status, "
                "or name a different --decision")
    if status != STATUS_SUPERSEDED:
        return None
    successor = _successor(repo, decision, exit_io, exit_refusal)
    if successor is None:
        return (exit_refusal,
                f"decision {decision} is {STATUS_SUPERSEDED}, so its order no longer stands",
                "cite the record that replaced it; name it with the census report "
                "(census.py --only ledger-chain) or order it without --decision")
    return (exit_refusal,
            f"decision {decision} is {STATUS_SUPERSEDED} by {successor}",
            f"the record that superseded it is {successor}: pass --decision {successor}")


def _successor(repo: Path, decision: str, exit_io: int, exit_refusal: int) -> str | None:
    """The id of the live record that supersedes ``decision``, if the ledger holds one.

    Scans the ledger for the record whose ``supersedes`` names ``decision``.
    Only a record whose own status is not superseded answers: a chain that has
    moved on again is superseded by the newest of its links, and that is the id
    the hint should name. A ledger that cannot be listed answers nothing.
    """
    ledger = repo / DECISIONS_DIR
    try:
        names = sorted(ledger.glob("*.json"))
    except OSError:
        return None
    best: str | None = None
    for candidate in names:
        found = read_record(candidate, exit_io, exit_refusal)
        if found[0] is None:
            continue
        record = found[0]
        if record.get("supersedes") != decision or record.get("status") == STATUS_SUPERSEDED:
            continue
        rid = record.get("id")
        if isinstance(rid, str) and DECISION_ID_RE.fullmatch(rid):
            if best is None or rid > best:
                best = rid
    return best


def is_index_text(raw: str) -> bool:
    """Whether ``raw`` is text ``int`` can read as a plain decimal number.

    ``isdigit`` is True for a superscript or an Arabic-Indic digit and ``int``
    refuses both, so a gate that stops at ``isdigit`` lets a token through to an
    ``int`` call that raises: the writer dies with a traceback where it owes the
    operator a usage refusal. ASCII decimal digits are what a position and an
    issue number are spelled with, and this is the one rule both tokens obey.
    """
    return raw.isascii() and raw.isdecimal()
    return raw.isascii() and raw.isdecimal()


def parse_index(raw: str, flag: str, count: int) -> tuple[int, tuple[str, str] | None]:
    """The 1-based position ``raw`` names for a list of ``count`` entries.

    1-based because the order is printed and read 1-based, and a position is
    counted, not an offset. The range is the list this run produces, so the
    last position of an ``add`` is the new length and of a ``move`` the current
    one: an out-of-range index answers nothing about an order, so it is refused
    rather than clamped.
    """
    if not is_index_text(raw):
        return 0, (f"{flag} {raw!r} is not a position",
                   f"{flag} is a 1-based position in the order: pass {flag} 1 for the top")
    position = int(raw)
    if not 1 <= position <= count:
        return 0, (f"{flag} {position} is outside the order "
                   f"(1 to {count} position(s) here)",
                   f"pass a position between 1 and {count}, or drop {flag} to append at "
                   "the end")
    return position, None


def print_order(entries: list[dict], label: str) -> None:
    """The resulting order: one line per entry, position, issue, decision, confirmed.

    ``label`` is the writer's own filename, which the line opens: this module
    has no opinion on which command printed the order it just read.
    """
    print(f"{label}: {orderschema.ORDER_REL} ({len(entries)} entr"
          f"{'y' if len(entries) == 1 else 'ies'})")
    for index, entry in enumerate(entries, 1):
        print(f"{index:>{orderschema.POSITION_WIDTH}}. #{entry['issue']} "
              f"decision={entry['decision'] or '-'} confirmed={entry['confirmed']}")
