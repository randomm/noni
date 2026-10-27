"""Order the work the operator wants next: write noni/direction/order.json and commit it.

The order is one committed, ordered list of open issues: position in the list IS
the order, an issue appears at most once, and every entry carries the time the
operator last confirmed it. This writer is the only writer of that file and it
never contacts a tracker: an issue number is checked only to be a positive
integer, so the core stays viable with no adapter installed.

The file holds two fields:

  schema   -- "noni.order/1", the artifact's version marker
  entries  -- [{issue, decision, confirmed}] in the order the operator wants

``decision`` is the id of the decision record that set the entry's position, or
null; a run that supplies one is refused (exit 4) when no file under
noni/decisions/ carries that id, or when the record it finds is already
superseded, and the hint names the record that superseded it. ``confirmed`` is
stamped by the writer (add and confirm stamp it with this run's UTC time, or
with --now when given); a run never leaves it empty. A correction of the order
is another run of this command, so the file keeps one owner.

Usage:
    order.py --repo REPO add ISSUE [--at N] [--decision ID] [--now ISO-8601] [--no-commit]
    order.py --repo REPO move ISSUE --to N [--now ISO-8601] [--no-commit]
    order.py --repo REPO remove ISSUE [--now ISO-8601] [--no-commit]
    order.py --repo REPO confirm [ISSUE] [--now ISO-8601] [--no-commit]

Exit codes:
    0  the order was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, a subcommand outside add/move/remove/confirm,
       an issue that is not a positive integer, a missing --decision on add, an --at or
       --to that is not a 1-based position of the resulting list, a flag passed to the
       verb that does not own it, or --now that is not a valid ISO-8601 timestamp
    3  a path this writer needs could not be read or written, or a git call failed or
       timed out: the order file is not a regular file at its path (a symlink, a
       directory, an unreadable file), the decision ledger could not be looked in, a
       decision record it must read is unreadable, the artifact could not be written, or
       the commit step failed (the file is left written and named, never claimed as
       committed)
    4  what the order itself refuses: the issue is already listed (add), absent from the
       order (move, remove, confirm), no file under noni/decisions/ carries the given
       --decision id, the record it finds is superseded (the hint names its successor),
       or the existing order file is not the artifact this writer writes (unparseable,
       wrong schema, or malformed entries) so overwriting it would destroy an order

Every refusal (2, 3 or 4) leaves the artifact untouched: reads and checks
happen before any write, the write goes to a temp file in its own directory and
moves into place with os.replace, and the commit stages only the path this
command wrote (git add -- <path> then git commit --only -- <path>), so a file
somebody else had staged is neither committed nor unstaged. --no-commit writes
through the same chain, leaves the file uncommitted and prints one line saying
so. Every run prints the resulting order, one line per entry: the 1-based
position, the issue, and the decision (or -) and confirmed timestamp it carries.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# The artifact's shape and the git / atomic-write mechanics live beside this
# file and are loaded by path, the way the steering-ledger writer loads its own
# helpers: a sys.path entry would put a directory ahead of the standard library,
# where any module of the same name earlier on that path could be trusted as
# this writer's schema. The names are ours.
_HELPERS = {"noni_orderschema": "orderschema.py", "noni_order_gitwrite": "gitwrite.py"}
for _name, _file in _HELPERS.items():
    _spec = importlib.util.spec_from_file_location(
        _name, Path(__file__).resolve().parent / _file)
    if _spec is None or _spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load {_file} beside order.py")
    sys.modules[_name] = _loaded = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loaded)
del _spec, _name, _file, _HELPERS, _loaded

orderschema = sys.modules["noni_orderschema"]
gitwrite = sys.modules["noni_order_gitwrite"]

# Every return path names one of these, and the 'Exit codes:' block above
# carries exactly this set (tests/test_order_writer.py pins the two together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_IO: int = 3
EXIT_REFUSAL: int = 4

# A decision record id is what decide.py writes: <YYYY-MM-DD>-<slug> of
# lowercase letters, digits and dashes. The same shape both directions, so a
# name that could escape the ledger directory is refused before any path is
# built from it.
DECISION_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*")
DECISIONS_DIR = "noni/decisions"
STATUS_SUPERSEDED = "superseded"

# The three status words a decision record may hold. An id whose record carries
# any other word answers nothing about the chain, so it is refused like an
# unreadable record (exit 3): a hand-edited status must not decide an ordering.
STATUSES = ("decided", "open", "superseded")


def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print a refusal as a headline plus a 'fix:' line naming what resolves it,
    and hand back the exit code. One shape for every refusal in this writer."""
    label = f"{Path(__file__).name}:"
    print(label, message, file=sys.stderr)
    if hint:
        print(label, "fix:", hint, file=sys.stderr)
    return code


def _now_iso(value: str | None) -> tuple[str, str | None]:
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


def _file_kind(path: Path) -> tuple[str, str | None]:
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


class _OrderOk(NamedTuple):
    # The order this writer may extend, plus the bytes on disk (None when the
    # path is absent, which is the state the first add writes into).
    entries: list
    before: bytes | None


class _OrderRefused(NamedTuple):
    # Why this run may not write: a headline and the fix that resolves it.
    headline: str
    hint: str


class _OrderFaulted(NamedTuple):
    # The artifact's path could not be read as a file at all (a symlink, a
    # directory, an unreadable regular file), or a git call hung: the
    # environment, not the order.
    headline: str
    hint: str


def _read_order(path: Path) -> _OrderOk | _OrderRefused | _OrderFaulted:
    """The order ``path`` holds, or the refusal naming why this run may not write.

    Absent is not a refusal: an empty order is what the first ``add`` extends.
    Anything else at the path that this writer would render differently is
    refused (exit 4) rather than overwritten, because destroying an order the
    operator committed is worse than refusing the run.
    """
    kind, why = _file_kind(path)
    if kind == "absent":
        return _OrderOk([], None)
    if kind == "dir":
        # A directory at the artifact path is not an empty order: nothing was
        # read, so this run may not write. The wording names the shape the
        # caller has to remove, which is not the fix for broken contents.
        return _OrderFaulted(f"{orderschema.ORDER_REL} is not a regular file: a directory "
                             "sits at that path",
                             f"remove the directory at {orderschema.ORDER_REL}, then "
                             "re-run order.py")
    if kind == "refusal":
        # An environment fault, not a refusal of the order: nothing is wrong
        # with the ordering, this run cannot reach it. A caller who fixes the
        # path re-runs the same command; a caller who repairs the artifact's
        # contents does not, and the two are different work.
        return _OrderFaulted(f"{orderschema.ORDER_REL} {why}",
                             "remove that path or point --repo at the tree that holds "
                             "the order, then re-run order.py")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _OrderFaulted(f"{orderschema.ORDER_REL} could not be read "
                             f"({exc.__class__.__name__}: {exc.strerror or exc})",
                             f"check that {orderschema.ORDER_REL} is readable, then "
                             "re-run order.py")
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=orderschema.refuse_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _OrderRefused(f"{orderschema.ORDER_REL} is not valid JSON this writer can "
                             "extend",
                             f"repair the file (it must hold {orderschema.ORDER_SCHEMA}) "
                             f"or remove it and rebuild the order with order.py add")
    found = orderschema.problems(value)
    if found:
        return _OrderRefused(f"{orderschema.ORDER_REL} is not an order this writer writes: "
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
    canonical = _render(body_of(value))
    if not isinstance(canonical, _RenderRefused) and canonical != raw:
        return _OrderRefused(f"{orderschema.ORDER_REL} is not in the canonical form this "
                             "writer writes (its keys, their order or its indent)",
                             "have order.py write it, or repair and commit it in that "
                             "form, then re-run order.py")
    return _OrderOk(value["entries"], raw)


def _read_record(path: Path) -> tuple[dict, None] | tuple[None, tuple[int, tuple[str, str]]]:
    """The decision record at ``path``, or the (code, (headline, hint)) refusal.

    The code travels with the refusal because the two ways a lookup fails are
    different kinds of failure: see :func:`_decision_problems`.
    """
    rel = f"{DECISIONS_DIR}/{path.name}"
    kind, why = _file_kind(path)
    if kind == "absent":
        return None, (EXIT_REFUSAL,
                      (f"no decision record {rel} is in the ledger",
                       "name the record that set the position, or add it with the "
                       "steering-ledger writer first"))
    if kind != "regular":
        return None, (EXIT_IO,
                      (f"the decision record {rel} is not readable: "
                       f"{why or 'not a regular file'}",
                       "repair or remove that path, or name a decision record that is "
                       "there"))
    try:
        raw = path.read_bytes()
    except OSError:
        # The name is the record's own path relative to the repo, so no
        # machine-local absolute path reaches the message.
        return None, (EXIT_IO,
                      (f"the decision record {rel} could not be read",
                       "check that the ledger is readable, or name a different "
                       "--decision"))
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=orderschema.refuse_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, (EXIT_IO,
                      ("the decision record is not readable JSON",
                       "repair the record or name a different --decision"))
    if not isinstance(value, dict):
        return None, (EXIT_IO,
                      ("the decision record is not a JSON object",
                       "name a record that holds a record, not a list or a bare value"))
    return value, None


def _ledger_is_readable(repo: Path) -> bool:
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


def _decision_problems(repo: Path, decision: str) -> tuple[int, str, str] | None:
    """The (code, headline, hint) refusal for a ``decision`` id this order may
    not cite, or None when the record it names is a record whose ordering stands.

    The code is part of the answer because a failed lookup is two different
    failures: the record is not there (exit 4, the caller names another record)
    and the ledger could not be looked in (exit 3, the caller fixes the tree).
    Collapsing them would make an unreadable ledger read as an ordering the
    operator should change.

    A decision record is identified by the filename stem of
    ``noni/decisions/<id>.json``, the path decide.py names its records by, so
    one file carrying the id is the whole answer.
    """
    path = repo / DECISIONS_DIR / f"{decision}.json"
    if not DECISION_ID_RE.fullmatch(decision):
        # A name the writer never produces cannot be a record, and building a
        # path from it is not worth the risk: same answer as no such file.
        return (EXIT_REFUSAL,
                f"decision {decision!r} matches no record file under {DECISIONS_DIR}/",
                "name the record that set the position, in the form "
                "YYYY-MM-DD-<slug>; the census report lists the ledger's records")
    if not _ledger_is_readable(repo):
        return (EXIT_IO,
                f"the decision ledger {DECISIONS_DIR}/ could not be looked in: it is not "
                "a readable directory",
                "restore the ledger directory, then re-run order.py, or order without "
                "--decision if no record set this position")
    found = _read_record(path)
    if found[0] is None:
        assert found[1] is not None
        code, (headline, hint) = found[1]
        return (code, headline, hint)
    record = found[0]
    status = record.get("status")
    if status not in STATUSES:
        return (EXIT_REFUSAL,
                f"the decision record {decision} carries status {status!r}, not one of "
                + ", ".join(STATUSES),
                "the census is the arbiter of the ledger: repair the record's status, "
                "or name a different --decision")
    if status != STATUS_SUPERSEDED:
        return None
    successor = _successor(repo, decision)
    if successor is None:
        return (EXIT_REFUSAL,
                f"decision {decision} is {STATUS_SUPERSEDED}, so its order no longer stands",
                "cite the record that replaced it; name it with the census report "
                "(census.py --only ledger-chain) or order it without --decision")
    return (EXIT_REFUSAL,
            f"decision {decision} is {STATUS_SUPERSEDED} by {successor}",
            f"the record that superseded it is {successor}: pass --decision {successor}")


def _successor(repo: Path, decision: str) -> str | None:
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
        found = _read_record(candidate)
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


def _parse_index(raw: str, flag: str, count: int) -> tuple[int, tuple[str, str] | None]:
    """The 1-based position ``raw`` names for a list of ``count`` entries.

    1-based because the order is printed and read 1-based, and a position is
    counted, not an offset. The range is the list this run produces, so the
    last position of an ``add`` is the new length and of a ``move`` the current
    one: an out-of-range index answers nothing about an order, so it is refused
    rather than clamped.
    """
    try:
        position = int(raw)
    except ValueError:
        return 0, (f"{flag} {raw!r} is not a position",
                   f"{flag} is a 1-based position in the order: pass {flag} 1 for the top")
    if not 1 <= position <= count:
        return 0, (f"{flag} {position} is outside the order "
                   f"(1 to {count} position(s) here)",
                   f"pass a position between 1 and {count}, or drop {flag} to append at "
                   "the end")
    return position, None


class _RenderRefused(NamedTuple):
    # The plan could not be turned into the bytes this writer commits. Every
    # value in a plan is validated before it gets here, so this is the writer's
    # own bug rather than the operator's; the artifact is left exactly as it was
    # and nothing is claimed as committed.
    headline: str
    hint: str


def _render(body: dict) -> bytes | _RenderRefused:
    """The canonical bytes for ``body``, or the refusal naming why none exist."""
    try:
        return orderschema.order_bytes(body)
    except ValueError:
        return _RenderRefused("the planned order cannot be written as JSON",
                              "re-run order.py; if it repeats, rebuild the order from "
                              "order.py add after removing the artifact")


def body_of(value: dict) -> dict:
    """The {schema, entries} mapping a parsed artifact holds, in canonical key order."""
    return {"schema": value["schema"], "entries": value["entries"]}


def _print_order(entries: list[dict]) -> None:
    """The resulting order: one line per entry, position, issue, decision, confirmed."""
    print(f"{Path(__file__).name}: {orderschema.ORDER_REL} ({len(entries)} entr"
          f"{'y' if len(entries) == 1 else 'ies'})")
    for index, entry in enumerate(entries, 1):
        print(f"{index:>{orderschema.POSITION_WIDTH}}. #{entry['issue']} "
              f"decision={entry['decision'] or '-'} confirmed={entry['confirmed']}")


def _digests(data: bytes) -> str:
    """A short stable digest for a run message; never a path, never file bytes."""
    return hashlib.sha1(data).hexdigest()[:7]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="order.py",
        description="Write the ordered list of issues the operator wants worked next "
                    "(noni/direction/order.json) and commit it.",
    )
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("subcommand", help="add, move, remove or confirm")
    parser.add_argument("issue", nargs="?", default=None,
                        help="the issue number (required for add, move and remove; "
                             "optional for confirm)")
    parser.add_argument("--at", default=None, metavar="N",
                        help="position (1-based) to place the added issue")
    parser.add_argument("--to", default=None, metavar="N",
                        help="position (1-based) to move the issue to")
    parser.add_argument("--decision", default=None, metavar="ID",
                        help="decision record id that set this entry's position "
                             "(required for add)")
    parser.add_argument("--now", default=None, metavar="ISO-8601",
                        help="fixed UTC timestamp for the confirmed stamp "
                             "(default: the current UTC time)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file and leave it uncommitted for the caller")
    args = parser.parse_args(argv)

    subcommand = args.subcommand
    if subcommand not in ("add", "move", "remove", "confirm"):
        return _fail(EXIT_USAGE, f"subcommand {subcommand!r} is not one of "
                     "add, move, remove or confirm",
                     "order.py --repo REPO add ISSUE --decision ID | move ISSUE --to N | "
                     "remove ISSUE | confirm [ISSUE]")

    # --at belongs to add and --to to move and nothing else: a flag that means
    # nothing for the verb it was passed with is a usage error, not a hint the
    # run quietly ignores.
    if subcommand != "add" and args.at is not None:
        return _fail(EXIT_USAGE, f"--at belongs to add, not {subcommand}",
                     f"to place an entry with {subcommand} pass --to N")
    if subcommand != "move" and args.to is not None:
        return _fail(EXIT_USAGE, f"--to belongs to move, not {subcommand}",
                     "--to is only how move names a position")
    if args.decision is not None and subcommand != "add":
        return _fail(EXIT_USAGE, f"--decision belongs to add, not {subcommand}",
                     "only add takes a position's decision; confirm restamps what is there")

    # The issue token: a positive integer, checked before the file is opened,
    # so a typo cannot decide which entry of a real order gets touched. confirm
    # is the one verb that may omit it, which means every entry at once.
    issue: int | None = None
    if subcommand == "confirm" and args.issue is None:
        pass
    else:
        token = args.issue
        if token is None:
            return _fail(EXIT_USAGE, f"{subcommand} needs an issue number",
                         f"order.py --repo REPO {subcommand} 42")
        if not token.isdigit() or int(token) < 1:
            return _fail(EXIT_USAGE, f"issue {token!r} is not a positive integer",
                         "name the issue by its number, e.g. 42")
        issue = int(token)

    if subcommand == "add" and args.decision is None:
        return _fail(EXIT_USAGE, "add needs --decision ID: an added position is a decision",
                     "name the decision record that put this issue there, or order it "
                     "with order.py confirm if it is already listed")

    stamp, err = _now_iso(args.now)
    if err:
        return _fail(EXIT_USAGE, err, "pass --now as e.g. 2026-10-27T09:00:00Z, or drop it "
                                      "to stamp this run's time")

    repo = Path(args.repo)
    order_path = repo / orderschema.ORDER_REL

    # --- reads: the artifact, then the decision it must cite -----------------
    # Read once, before anything is written: a --no-commit run leaves its own
    # bytes in the working tree for the next run to read, and a plan built from
    # entries this run has already restamped would not be a plan at all.
    read = _read_order(order_path)
    if isinstance(read, _OrderFaulted):
        return _fail(EXIT_IO, read.headline, read.hint)
    if isinstance(read, _OrderRefused):
        return _fail(EXIT_REFUSAL, read.headline, read.hint)
    entries = [dict(entry) for entry in read.entries]
    before_entries = [dict(entry) for entry in read.entries]
    before = read.before
    listed = {entry["issue"] for entry in entries}

    # --- the plan: what the entries become, decided before any write ---------
    verb: str
    if subcommand == "add":
        assert issue is not None
        assert args.decision is not None
        if issue in listed:
            position = next(i for i, e in enumerate(entries, 1) if e["issue"] == issue)
            return _fail(EXIT_REFUSAL, f"issue {issue} is already in the order at position "
                         f"{position}", f"move it with 'order.py move {issue} --to N', or "
                         "restamp it with 'order.py confirm'")
        refusal = _decision_problems(repo, args.decision)
        if refusal is not None:
            return _fail(*refusal)
        count = len(entries) + 1
        if args.at is None:
            position = count
        else:
            position, problem = _parse_index(args.at, "--at", count)
            if problem is not None:
                return _fail(EXIT_USAGE, *problem)
        entries.insert(position - 1, orderschema.entry(issue, args.decision, stamp))
        verb = f"add {issue}"
    elif subcommand == "move":
        assert issue is not None
        if issue not in listed:
            return _fail(EXIT_REFUSAL, f"issue {issue} is not in the order",
                         "list it first with 'order.py add ISSUE --decision ID'")
        if args.to is None:
            return _fail(EXIT_USAGE, "move needs --to N: a move to no position is not a move",
                         f"pass the 1-based position to move {issue} to, e.g. --to 1")
        position, problem = _parse_index(args.to, "--to", len(entries))
        if problem is not None:
            return _fail(EXIT_USAGE, *problem)
        moved = next(e for e in before_entries if e["issue"] == issue)
        entries = [e for e in entries if e["issue"] != issue]
        entries.insert(position - 1, orderschema.entry(issue, moved["decision"], stamp))
        verb = f"move {issue} to {position}"
    elif subcommand == "remove":
        assert issue is not None
        if issue not in listed:
            return _fail(EXIT_REFUSAL, f"issue {issue} is not in the order",
                         "there is nothing to remove; the order is left as it is")
        entries = [e for e in entries if e["issue"] != issue]
        verb = f"remove {issue}"
    else:
        if issue is not None and issue not in listed:
            return _fail(EXIT_REFUSAL, f"issue {issue} is not in the order",
                         "add it first with 'order.py add ISSUE --decision ID'")
        targets = entries if issue is None else [e for e in entries if e["issue"] == issue]
        for entry in targets:
            entry["confirmed"] = stamp
        verb = f"confirm {issue if issue is not None else 'all'}"

    # --- the write: every check above has passed -----------------------------
    body = {"schema": orderschema.ORDER_SCHEMA, "entries": entries}
    rendered = _render(body)
    if isinstance(rendered, _RenderRefused):
        # Not bytes this writer can produce. The plan is built from validated
        # values, so the file keeps the bytes it had and nothing is claimed.
        return _fail(EXIT_REFUSAL, rendered.headline, rendered.hint)
    if before is not None and rendered == before:
        # A run that changes no byte (confirming an entry already stamped at the
        # time it was given) has nothing to commit: it prints the order it read
        # and says the file is unchanged, rather than committing a --allow-empty
        # commit no one asked for.
        _print_order(entries)
        print(f"{Path(__file__).name}: {orderschema.ORDER_REL} is unchanged; nothing to "
              "commit")
        return EXIT_OK
    if order_path.parent.exists() and not order_path.parent.is_dir():
        # The parent path is part of the artifact's identity: a file where the
        # direction directory belongs is an environment fault, and mkdir would
        # have failed here anyway with a worse message.
        return _fail(EXIT_IO, f"{orderschema.ORDER_DIR} is not a directory",
                     f"remove {orderschema.ORDER_DIR} or move it aside, then re-run "
                     "order.py")
    try:
        order_path.parent.mkdir(parents=True, exist_ok=True)
        gitwrite.write_atomic(order_path, rendered)
    except OSError as exc:
        return _fail(EXIT_IO, gitwrite.written(exc, f"{orderschema.ORDER_REL} could not be "
                                               "written"),
                     f"check that {orderschema.ORDER_DIR} is writable, then re-run order.py")

    _print_order(entries)
    digest = _digests(rendered)
    if args.no_commit:
        # The census reads the working tree, so this file reads as uncommitted;
        # the one line says so and names the path, and committing it is the
        # caller's job.
        print(f"{Path(__file__).name}: wrote {orderschema.ORDER_REL}; left uncommitted: "
              "commit this path before running the census")
        return EXIT_OK

    rel = orderschema.ORDER_REL
    # --only with the explicit path: the commit carries exactly what this run
    # wrote, never a file somebody else had staged.
    added = gitwrite.git(repo, "add", "--", rel)
    if added.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git add timed out for {rel} after {gitwrite.GIT_TIMEOUT}s "
                     f"(the file is written, its staged state unknown)",
                     "check 'git status --porcelain' once git answers, then stage and "
                     "commit the path by hand or re-run order.py")
    if added.returncode != 0:
        detail = added.stderr.strip() or added.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git add failed for {rel} (the file is written, "
                     f"unstaged): {detail}",
                     f"run 'git status --porcelain -- {rel}' and stage the path by "
                     "hand, or re-run order.py")
    committed = gitwrite.git(repo, "commit", "-q", "-m", f"direction: {verb} [{digest}]",
                             "--only", "--", rel)
    if committed.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git commit timed out for {rel} after {gitwrite.GIT_TIMEOUT}s "
                     f"(the file is written and staged, not committed)",
                     "check 'git log -1 --oneline' once git answers, then commit the path "
                     "by hand or re-run order.py")
    if committed.returncode != 0:
        detail = committed.stderr.strip() or committed.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git commit failed for {rel} (the file is written and "
                     f"staged, not committed): {detail}",
                     f"commit {rel} by hand, or re-run order.py once git answers")
    print(f"{Path(__file__).name}: committed {rel} ({verb})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
