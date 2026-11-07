"""File one idea as its own committed record: write noni/items/<id>.json and commit it.

An item is one idea, held as one committed file, so "we thought about that" survives
the session that thought of it. This writer is the only writer of those files and it
never contacts a tracker: an issue number is checked only to be a positive integer,
so the core stays viable with no adapter installed.

The file holds eight fields:

  schema    -- "noni.item/1", the artifact's version marker
  id        -- the item's name, restated inside its own file
  title     -- one line: the idea as its author phrased it
  status    -- "candidate", "promoted" or "dropped"
  created   -- the UTC stamp this writer gave the item
  issue     -- the issue the item became, or null
  decision  -- the decision record that moved it, or null
  why       -- the reason it was dropped, or null

``why`` is the reason a dropped item was dropped and it is never empty: the report
that asked for the store asked for "the reason, the kill list and the link to a
decision", so a dropped item carries all three and one that cites nothing or explains
nothing is refused (exit 4). ``decision`` is the id of a record under
``noni/decisions/`` whose status is not ``superseded``. ``created`` is stamped by the
writer (with this run's UTC time, or with ``--now`` when given) and no verb restamps
it: the age of an idea is the age of the idea.

Usage:
    item.py --repo REPO add ID --title TITLE [--now ISO-8601] [--no-commit]
    item.py --repo REPO list [--no-commit]
    item.py --repo REPO drop ID --decision ID --why REASON [--now ISO-8601] [--no-commit]
    item.py --repo REPO promote ID [--issue N] [--now ISO-8601] [--no-commit]

Exit codes:
    0  the item was written (and committed unless --no-commit), or listed
    2  invalid input: an argparse failure, a subcommand outside add/list/drop/promote,
       a missing --title on add, --decision or --why passed to a verb that does not
       own them, an id that is not lowercase letters, digits and dashes (or ends in
       .json), a --title or --why that is blank or more than one line or past its
       length limit, an --issue that is not a positive integer, a --now that is not a
       valid UTC ISO-8601 timestamp, a --repo that is not a directory, or a noni/ or
       noni/items directory -- every one from the state root down to the item file --
       that is not a plain path this writer may read or write through (a symlink, a
       plain file, a socket or a device, each asked of lstat before any read, write or
       mkdir, and an absent one admitted because the first add creates it)
    3  a path this writer needs could not be read or written, or a git call failed or
       timed out: the item file is not a regular file at its path (a symlink, a
       directory, a device, an unreadable file), the decision ledger could not be
       looked in, a decision record it must read is unreadable, the items directory
       could not be listed for the duplicate-title scan, the order file could not be
       read so the promote refusal could not be answered, the artifact could not be
       written, or the commit step failed (the file is left written and named, never
       claimed as committed)
    4  what the item itself refuses: the id is already filed (add), the title is
       already carried by a dropped item (add, which is the record of an idea already
       killed), the item is absent (drop, promote), the item is already terminal
       (drop or promote of a promoted or dropped item), no file under
       noni/decisions/ carries the given --decision id or the record it finds is
       superseded (the hint names its successor), an order entry cites the item so
       promoting it alone would leave the order out of step (the refusal names the
       order path and says the order is what has to change), or the existing item file
       is not the artifact this writer writes (unparseable, wrong schema, an id that
       is not the file's own name, or bytes this writer would render differently) so
       overwriting it would destroy a record

Every refusal (2, 3 or 4) leaves the tracked files byte-identical: reads and checks
happen before any write -- the artifact is read once, the store listed once and the
order read once, all before a byte is staged -- the write goes to a temp file in its
own directory and moves into place with os.replace, and the commit stages only the
path this command wrote (git add -- <path> then git commit --only -- <path>), so a
file somebody else had staged is neither committed nor unstaged. --no-commit writes
through the same chain, leaves the file uncommitted and prints one line saying so.

Every run that writes prints one line naming the item and its status. ``list`` prints
one line per item, newest first: the id, the status, the title, and the issue,
decision or reason each item carries, so the kill list and the link the report asked
for are on the screen without a second command. Every free text of that listing goes
through the package's one text renderer, because a title is text somebody typed and a
terminal is not somewhere a control character gets to mean something. The path the
success line names (wrote, committed, or left uncommitted) is the artifact's real
location as seen from the caller's working directory: ``--repo`` followed by
noni/items/<id>.json, spelled the same with and without --no-commit.

The artifact's shape lives in itemschema.py in the package, the read of the order it
must not contradict in item_reads.py, and the reads of the ledger it cites are reused
from orderstate.py; the git and atomic-write mechanics are reused from
order_gitwrite.py. All are package imports: inside an installed wheel there is no
sibling file to load by path, and no directory of the package ever goes on
``sys.path``, so no caller can put a lookalike ahead of them. This file owns the
verbs, the exit codes, the plan and the commit.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import (
    _path_kind,
    item_reads,
    itemschema,
    labels,
    ledger_schema,
    orderschema,
    orderstate,
)
from . import order_gitwrite as gitwrite
from ._safe_text import safe_text


# The state reader reports a refusal as a (headline, hint) pair and leaves the code
# to the writer, so the one table of codes stays here and the reader's answers arrive
# pre-coded at the call sites below. The label is the running program's own name from
# ``noni.labels``, which is what lets a refusal reached through the borrowed reader
# read as coming from ``item.py``, the program that ran, and not from the order writer
# those mechanics came from.
def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print one refusal in the writer's voice and hand back its code.

    The label is this program's own name from ``noni.labels`` rather than this file's:
    a refusal printed by a borrowed reader must still read as coming from
    ``item.py``, whichever route reached it.
    """
    return orderstate._fail(code, message, hint, label=f"{labels.ITEM}:")


# Every return path names one of these, and the 'Exit codes:' block above carries
# exactly this set (tests/test_item_writer_docs.py pins the two together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_IO: int = 3
EXIT_REFUSAL: int = 4


# The verbs the writer owns, in the order every document lists them. One tuple so the
# unknown-verb refusal, the missing-verb hint and the usage line cannot name three
# different sets.
VERBS: tuple[str, ...] = ("add", "list", "drop", "promote")

# The directories this run reads or writes, in the order the guard walks them:
# ``noni`` itself first (a link there hides every path beneath it from ``lstat``),
# then the store this writer owns, then the ledger a dropped item cites. The wording,
# the walk and the declined-``lstat`` rule all live in the guard; see
# :func:`_refuse_linked_state`.
_GUARDED_DIRS: tuple[str, ...] = ("noni", itemschema.ITEM_DIR,
                                  orderstate.DECISIONS_DIR)

# The flags each verb owns, spelled once so the refusal that names the verb a flag
# belongs to and the parser's own declaration cannot drift apart.
_FLAG_OWNER = {"--title": "add", "--decision": "drop", "--why": "drop",
               "--issue": "promote"}

# The verb list the missing-subcommand hint prints, spelled once from ``VERBS``.
_VERBS_JOINED = ", ".join(VERBS)

# The usage line, spelled once and handed to argparse as ``usage=``.
#
# argparse composes a usage line as ``optionals + positionals``, unconditionally, so
# with ``--repo`` required and the flags declared before the verbs, ``item.py --help``
# would render ``... [--no-commit] subcommand [id]`` and bury the one word the caller
# has to choose. ``order.py`` and ``intent.py`` carry the same decision, the reasoning
# and the Python 3.14 history behind it: a literal is the only public way to put the
# verb first, and a formatter subclass that called argparse's private formatters died
# on 3.14 (issue #98). The flag block is the parser's own declaration, in declaration
# order, with the metavar argparse prints for each, and the flag-set parity of
# ``tests/test_item_writer_docs.py`` compares the two: a flag added to the parser
# belongs here too.
_USAGE = (f"{labels.ITEM} --repo REPO subcommand [id]"
          " [--title TITLE] [--decision ID] [--why REASON] [--issue N]"
          " [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional, and the
# line argparse prints above it. argparse turns this refusal into usage-plus-error
# itself, so the verbs are added to *that* pair rather than to the message text.
_MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class _VerbedParser(argparse.ArgumentParser):
    """The parser of a one-verb writer, naming the verbs when the verb is missing.

    ``item.py --repo R`` with no verb got argparse's own refusal, which names the slot
    (``subcommand``) and not the four words that fill it: only an *invalid* verb
    reached the fix line that named them, so the commonest mistake printed the least
    useful answer (issue #98, the same refusal ``order.py`` and ``intent.py`` close).
    This parser keeps argparse's own refusal and adds the verbs to it, so the usage
    line, the wording and the exit code are unchanged and one more line names the
    accepted verbs. The parser shape is deliberately untouched: ``add_subparsers`` or
    ``choices=`` would move the verb out of the usage line and take the refusal off
    the path the pinned wording stands for.
    """

    def error(self, message: str):
        if _MISSING_SUBCOMMAND in message:
            self.print_usage(sys.stderr)
            print(f"{self.prog}: {message}", file=sys.stderr)
            print(f"{self.prog}: fix: choose from: {_missing_verb_hint()}",
                  file=sys.stderr)
            raise SystemExit(EXIT_USAGE)
        super().error(message)


def _missing_verb_hint() -> str:
    """The verb list the missing-subcommand hint prints.

    Joined with the same "or" the unknown-verb refusal above uses -- one sentence for
    one set, so the two refusals of the same mistake cannot answer it twice.
    """
    *first, last = VERBS
    if len(first) == 1:
        return f"{first[0]} or {last}"
    return f"{', '.join(first)} or {last}"


def _digests(data: bytes) -> str:
    """A short stable digest for a commit subject; never a path, never file bytes."""
    return hashlib.sha1(data).hexdigest()[:7]


def _refuse_linked_state(repo: Path, verb: str) -> int | None:
    """The exit-2 refusal for a ``--repo`` this writer may not read or write, or None.

    One seam for both ``noni/`` questions of :data:`_GUARDED_DIRS`, in the order and
    with the wording :func:`noni._path_kind.refuse_state_root` owns. Only ``add`` is
    admitted to the state-root question: it is this writer's one sanctioned creator,
    while ``list``, ``drop`` and ``promote`` create nothing legitimate and are refused
    ahead of the reads that would otherwise answer "no such item". ``EXIT_USAGE`` is
    the code docs/PRODUCT.md 7 gives ``item`` for a wrong path; the guard runs before
    the artifact read, the ledger lookup and every mkdir.
    """
    refused = _path_kind.refuse_state_root(repo, verb == "add", _GUARDED_DIRS)
    return None if refused is None else _fail(EXIT_USAGE, *refused)


def _refuse_text(flag: str, value: str, limit: int, what: str) -> int | None:
    """The exit-2 refusal for a flag whose value is not one bounded line, or None.

    Blank, multi-line and over-long are the three ways a free-text flag stops being
    the one line it names, and all three are refused at the flag rather than at the
    file: a value carrying a newline into the artifact would put a second line into a
    listing, and one past the bound would put an unbounded row into the census. The
    predicate is the ledger's, so one rule holds a decision record's name field and
    an item's title.
    """
    if not ledger_schema.is_single_line(value):
        return _fail(EXIT_USAGE, f"{flag} {value!r} is not a non-blank single line",
                     f"{what} is one line of text: pass it without a newline and "
                     "with something in it")
    if len(value) > limit:
        return _fail(EXIT_USAGE, f"{flag} is {len(value)} characters, past the "
                     f"{limit} limit", f"shorten {flag} to at most {limit} characters")
    return None


def _read_item(path: Path, item_id: str) -> tuple[dict | None, int | None]:
    """The item at ``path``, or the refusal code with its line already printed.

    ``(None, None)`` is absence, which the caller decides the meaning of: an absent
    item is the "no such item" refusal of drop and promote, and the empty store a
    first ``add`` extends. A file that is there and is not the artifact is refused
    rather than overwritten, because destroying a record the operator committed is
    worse than refusing the run.
    """
    rel = itemschema.item_rel(item_id)
    kind, why = orderstate.file_kind(path)
    if kind == "absent":
        return None, None
    if kind != "regular":
        return _fail(EXIT_IO, f"{rel} is not a readable regular file: "
                   f"{why or 'not a regular file'}",
                     "remove that path or point --repo at the tree that holds the "
                     "item, then re-run item.py"), None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _fail(EXIT_IO, f"{rel} could not be read "
                   f"({exc.__class__.__name__}: {exc.strerror or exc})",
                     f"check that {rel} is readable, then re-run item.py"), None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # The package's one strict reader, so the writer and the census answer one
        # document alike. The wording is fixed and names none of the bytes: they are
        # content this writer did not write, and a refusal that quotes them prints
        # them. RecursionError is no kind of ValueError -- the depth bound answers
        # short of the interpreter's own ceiling, past which the decoder raises it
        # first, so the arm is reachable and not decorative.
        return _fail(EXIT_REFUSAL, f"{rel} is not valid JSON this writer can extend",
                     f"repair the file (it must hold {itemschema.ITEM_SCHEMA}) or "
                     "remove it and re-file the idea with item.py add"), None
    found = itemschema.problems(value)
    if found:
        return _fail(EXIT_REFUSAL,
                     f"{rel} is not an item this writer writes: " + "; ".join(found),
                     f"repair the file to the documented shape "
                     f"({itemschema.ITEM_SCHEMA}) or remove it and re-file the idea "
                     "with item.py add"), None
    if value["id"] != item_id:
        return _fail(EXIT_REFUSAL, f"{rel} carries id {value['id']!r}, which is not "
                     "the item's own name",
                     "the id and the file's stem are the same name: repair one of "
                     "them, or remove the file and re-file the idea with item.py add"), None
    if itemschema.item_bytes(itemschema.body_of(value)) != raw:
        return _fail(EXIT_REFUSAL, f"{rel} is not in the canonical form this writer "
                     "writes (its keys, their order or its indent)",
                     "have item.py write it, or repair and commit it in that form, "
                     "then re-run item.py"), None
    return itemschema.body_of(value), None


def _listing(repo: Path) -> tuple[list[Path] | None, int | None]:
    """The store's one listing, or the refusal code a faulted read earned.

    One ``iterdir``, never ``glob``: a store the run could not list must stop the add
    rather than read as a store holding nothing, which is how a duplicate title would
    slip past a scan handed an empty listing. The fault is an environment one (exit 3)
    because nothing about the item being filed is wrong. The listing is taken once per
    run and handed to whichever scan needs it, so the gate and the scan cannot
    disagree about what the store holds.
    """
    store = repo / itemschema.ITEM_DIR
    kind, why = orderstate.file_kind(store)
    if kind == "absent":
        # The state before the first add: an honest answer to the duplicate scan
        # ('no dropped item carries that title'), never a fault to report.
        return [], None
    if kind != "dir":
        return _fail(EXIT_IO, f"{itemschema.ITEM_DIR} could not be listed: "
                   f"{why or 'not a readable directory'}",
                     f"restore {itemschema.ITEM_DIR} as a directory, then re-run "
                     "item.py"), None
    try:
        return sorted(store.iterdir()), None
    except OSError as exc:
        return _fail(EXIT_IO, f"{itemschema.ITEM_DIR} could not be listed "
                   f"({exc.__class__.__name__}: {exc.strerror or exc})",
                     f"check that {itemschema.ITEM_DIR} is readable, then re-run "
                     "item.py"), None


def _scan_item(path: Path) -> dict | None:
    """One file of the store's listing, read as far as a scan needs. None is "skip".

    Not a regular file, unreadable, unparseable, or not an item this shape describes:
    the scan is not the census and reports nothing. The probe-honesty rule of the
    census must not leak into the writer's success path, so a broken file never holds
    up an add -- it is simply a file this scan saw nothing about.
    """
    kind, _why = orderstate.file_kind(path)
    if kind != "regular":
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or itemschema.problems(value):
        return None
    return itemschema.body_of(value)


def _dropped_title_taken(repo: Path, title: str) -> int | None:
    """The exit-4 refusal for a title a dropped item already carries, or None.

    An idea already killed is recorded as killed: re-filing its title verbatim is the
    operator asking for that record again, so the add refuses and names the item that
    holds the reason. A file the scan could not read is skipped rather than fatal, so
    the run still exits 0 when the matching dropped file is itself unreadable and
    therefore unable to have matched -- the census's honesty belongs to the census.
    """
    paths, code = _listing(repo)
    if code is not None:
        return code
    for path in paths or []:
        if path.suffix != ".json":
            continue
        body = _scan_item(path)
        if (body is None or body["status"] != itemschema.STATUS_DROPPED
                or body["title"] != title):
            continue
        return _fail(EXIT_REFUSAL, f"an item titled {title!r} was already dropped "
                     f"as {path.stem}",
                     "the record of why it was dropped is the answer: file the idea "
                     "under a different title, or restore that item by its id")
    return None


def _refuse_cited_order(repo: Path, item_id: str) -> int | None:
    """The refusal ``promote`` owes an order that cites this item, or None.

    Promote is item-only in this sub-issue, so an order that already cites the item
    is refused rather than left pointing at a newly promoted item the same commit did
    not rewrite. The question is answered by the borrowed reader, which distinguishes
    "no entry cites it" from "the order could not be read", and the two get different
    codes: the first is no refusal at all, the second is exit 3 naming the order path,
    because a run that read nothing may not promote on the strength of not having read
    it. Sub-issue 2 replaces this refusal with the same-commit order rewrite.
    """
    cited, answered = item_reads.order_cites_item(repo, item_id)
    if answered and not cited:
        return None
    if not answered:
        return _fail(EXIT_IO, f"{orderschema.ORDER_REL} could not be read, so "
                     "whether an order entry cites this item cannot be answered",
                     f"repair or remove {orderschema.ORDER_REL}, then re-run item.py")
    return _fail(EXIT_REFUSAL,
                 f"{orderschema.ORDER_REL} has an entry that cites item {item_id}, "
                 "so promoting the item alone would leave the order out of step",
                 f"the order is what has to change: correct that entry in "
                 f"{orderschema.ORDER_REL} with order.py in the same commit as the "
                 "promotion; until the order carries items, remove it with "
                 "'order.py remove <issue>' and re-run item.py promote")


def _commit(repo: Path, rel: str, subject: str, shown: Path) -> int:
    """Stage and commit exactly ``rel``, or the exit-3 code naming which step failed.

    ``--only`` with the explicit path: the commit carries what this run wrote and
    never a file somebody else had staged. A timeout is its own answer (exit 3, the
    file named, never claimed as committed) rather than a traceback, so every caller
    classifies a hung git the same way.
    """
    added = gitwrite.git(repo, "add", "--", rel)
    if added.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git add timed out for {rel} after "
                   f"{gitwrite.GIT_TIMEOUT}s (the file is written, its staged state "
                   "unknown)",
                     "check 'git status --porcelain' once git answers, then stage "
                     "and commit the path by hand or re-run item.py")
    if added.returncode != 0:
        detail = added.stderr.strip() or added.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git add failed for {rel} (the file is written, "
                   f"unstaged): {detail}",
                     f"run 'git status --porcelain -- {rel}' and stage the path by "
                     "hand, or re-run item.py")
    committed = gitwrite.git(repo, "commit", "-q", "-m", subject, "--only", "--", rel)
    if committed.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git commit timed out for {rel} after "
                   f"{gitwrite.GIT_TIMEOUT}s (the file is written and staged, not "
                   "committed)",
                     "check 'git log -1 --oneline' once git answers, then commit the "
                     "path by hand or re-run item.py once git answers")
    if committed.returncode != 0:
        detail = committed.stderr.strip() or committed.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git commit failed for {rel} (the file is written and "
                   f"staged, not committed): {detail}",
                     f"commit {rel} by hand, or re-run item.py once git answers")
    print(f"{labels.ITEM}: committed {shown} ({subject.split(' [', 1)[0]})")
    return EXIT_OK


def _listing_line(body: dict) -> str:
    """One line of ``list``: the id, its status, its title, then what it cites.

    Every free text goes through the package's one renderer before it reaches the
    terminal, because a title and a reason are operator input: a value carrying a
    control character cannot split a line of the listing, and a value of any length
    cannot make a row longer than the bound.
    """
    detail = [f"created={body['created']}"]
    if body["issue"] is not None:
        detail.append(f"issue=#{body['issue']}")
    if body["decision"] is not None:
        detail.append(f"decision={body['decision']}")
    if body["why"] is not None:
        detail.append(f"why={safe_text(body['why'])}")
    return (f"  {body['id']} [{body['status']}] {safe_text(body['title'])} "
            + " ".join(detail))


def _listing_bodies(repo: Path) -> tuple[list[dict] | None, int | None]:
    """Every item the store holds, for ``list``, or the refusal code it earned.

    Same one-listing rule as the duplicate scan, same skip-don't-fail rule about
    individual files: an item nobody can read is the census's to report, and a listing
    that died on one broken file would tell the operator nothing about the store they
    asked to see. A file whose contents name another item is left out, because the
    listing prints what an item is, not what a stray file says.
    """
    paths, code = _listing(repo)
    if code is not None:
        return None, code
    bodies: list[dict] = []
    for path in paths or []:
        if path.suffix != ".json":
            continue
        body = _scan_item(path)
        if body is not None and path.stem == body["id"]:
            bodies.append(body)
    return bodies, None


def _print_listing(bodies: list[dict]) -> None:
    """The listing, newest first: one line per item, and a head naming the count."""
    plural = "y" if len(bodies) == 1 else "ies"
    print(f"{labels.ITEM}: {itemschema.ITEM_DIR} ({len(bodies)} item{plural})")
    for body in sorted(bodies, key=lambda b: (b["created"], b["id"]), reverse=True):
        print(_listing_line(body))


def _write(repo: Path, body: dict, verb: str, no_commit: bool) -> int:
    """Render, write, and commit only the one item path. Every check ran already."""
    rel = itemschema.item_rel(body["id"])
    target = repo / rel
    try:
        rendered = itemschema.item_bytes(body)
    except ValueError:
        # Not bytes this writer can produce. Every value of a plan here is validated
        # before it gets this far, so this is the writer's own bug rather than the
        # operator's: the file keeps the bytes it had and nothing is claimed.
        return _fail(EXIT_REFUSAL, "the planned item cannot be written as JSON",
                     "re-run item.py; if it repeats, remove the item and re-file "
                     "the idea")
    if target.parent.exists() and not target.parent.is_dir():
        # The one shape about the store's path the pre-read guard does not own: an
        # ordinary FILE at noni/items, under a real noni/, which the walk admits
        # because nothing above it is a link. A link there was refused with the rest
        # of the tree at exit 2; a plain file is an environment fault, and mkdir would
        # have failed anyway with a worse message.
        return _fail(EXIT_IO, f"{itemschema.ITEM_DIR} is not a directory",
                     f"remove {itemschema.ITEM_DIR} or move it aside, then re-run "
                     "item.py")
    if _unchanged(target, rendered, body, verb):
        return EXIT_OK
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        gitwrite.write_atomic(target, rendered)
    except OSError as exc:
        return _fail(EXIT_IO, gitwrite.written(exc, f"{rel} could not be written"),
                     f"check that {itemschema.ITEM_DIR} is writable, then re-run "
                     "item.py")
    print(f"{labels.ITEM}: {body['id']} is {body['status']} ({verb})")
    if no_commit:
        print(f"{labels.ITEM}: wrote {target}; left uncommitted: commit this path "
              "before running the census")
        return EXIT_OK
    return _commit(repo, rel, f"items: {verb} [{_digests(rendered)}]", target)


def _unchanged(target: Path, rendered: bytes, body: dict, verb: str) -> bool:
    """Whether the file already holds these bytes, so the run has nothing to do.

    An idempotent repeat stages nothing, commits nothing and moves no HEAD, and says
    so in one line beside the line the verb itself prints.
    """
    if not target.is_file():
        return False
    try:
        same = target.read_bytes() == rendered
    except OSError:
        return False
    if not same:
        return False
    print(f"{labels.ITEM}: {body['id']} is {body['status']} ({verb})")
    print(f"{labels.ITEM}: {itemschema.item_rel(body['id'])} is unchanged; nothing "
          "to commit")
    return True


def _state_root(args: argparse.Namespace, verb: str) -> Path | None:
    """The ``--repo`` this run works in, or None after printing its refusal."""
    repo = Path(args.repo)
    if not repo.is_dir():
        _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
              "pass the repository root that holds (or will hold) "
              f"{itemschema.ITEM_DIR}/")
        return None
    linked = _refuse_linked_state(repo, verb)
    return None if linked is not None else repo


def main(argv: list[str] | None = None) -> int:
    parser = _VerbedParser(
        prog=labels.ITEM,
        description="File one idea as its own committed record "
                    f"({itemschema.ITEM_DIR}/<id>.json) and commit it.",
        usage=_USAGE,
    )
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("subcommand", help="add, list, drop or promote")
    parser.add_argument("id", nargs="?", default=None,
                        help="the item id (required for add, drop and promote)")
    parser.add_argument("--title", default=None, metavar="TITLE",
                        help="one line naming the idea (required for add)")
    parser.add_argument("--decision", default=None, metavar="ID",
                        help="the decision record that dropped this item "
                             "(required for drop)")
    parser.add_argument("--why", default=None, metavar="REASON",
                        help="the reason the item was dropped (required for drop)")
    parser.add_argument("--issue", default=None, metavar="N",
                        help="the issue a promoted item became")
    parser.add_argument("--now", default=None, metavar="ISO-8601",
                        help="fixed UTC timestamp for the created stamp "
                             "(default: the current UTC time)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file and leave it uncommitted for the caller")
    args = parser.parse_args(argv)

    subcommand = args.subcommand
    if subcommand not in VERBS:
        return _fail(EXIT_USAGE, f"subcommand {subcommand!r} is not one of "
                     + ", ".join(VERBS),
                     f"{labels.ITEM} --repo REPO add ID --title TITLE | list | "
                     "drop ID --decision ID --why REASON | promote ID")
    # A flag that means nothing for the verb it was passed with is a usage error, not
    # a hint the run quietly ignores: --why is the dropped item's reason and no other
    # verb carries one, and a --title on drop would edit an item whose record closed.
    for flag, owner in _FLAG_OWNER.items():
        dest = flag.lstrip("-")
        if getattr(args, dest) is not None and subcommand != owner:
            return _fail(EXIT_USAGE, f"{flag} belongs to {owner}, not {subcommand}",
                         f"only {owner} takes {flag}")
    if subcommand == "list":
        return _run_list(args)
    if args.id is None:
        return _fail(EXIT_USAGE, f"{subcommand} needs an item id",
                     f"{labels.ITEM} --repo REPO {subcommand} my-idea")
    if not itemschema.is_item_id(args.id):
        return _fail(EXIT_USAGE, f"id {args.id!r} is not an item id",
                     "an item id is lowercase letters, digits and dashes, and does "
                     "not end in .json")
    repo = _state_root(args, subcommand)
    if repo is None:
        return EXIT_USAGE
    stamp, err = orderstate.now_iso(args.now)
    if err:
        return _fail(EXIT_USAGE, err, "pass --now as e.g. 2026-10-27T09:00:00Z, or "
                                      "drop it to stamp this run's time")
    if subcommand == "add":
        return _run_add(repo, args, stamp)
    if subcommand == "drop":
        return _run_drop(repo, args, stamp)
    return _run_promote(repo, args, stamp)


def _run_list(args: argparse.Namespace) -> int:
    """``list``: print the store, newest first, and change nothing."""
    repo = _state_root(args, "list")
    if repo is None:
        return EXIT_USAGE
    bodies, code = _listing_bodies(repo)
    if code is not None:
        return code
    _print_listing(bodies or [])
    return EXIT_OK


def _run_add(repo: Path, args: argparse.Namespace, stamp: str) -> int:
    """``add``: file a new candidate, refusing anything that duplicates a record."""
    if args.title is None:
        return _fail(EXIT_USAGE, "add needs --title TITLE: an idea is filed under "
                     "a name",
                     f"{labels.ITEM} --repo REPO add my-idea --title 'Cache the "
                     "census'")
    refused = _refuse_text("--title", args.title, itemschema.TITLE_MAX, "the title")
    if refused is not None:
        return refused
    existing, code = _read_item(repo / itemschema.item_rel(args.id), args.id)
    if code is not None:
        return code
    if existing is not None:
        return _fail(EXIT_REFUSAL, f"item {args.id} is already filed as "
                     f"{existing['status']}",
                     f"its record is what it is: drop it with 'item.py drop "
                     f"{args.id} --decision ID --why REASON' or leave it a candidate")
    duplicate = _dropped_title_taken(repo, args.title)
    if duplicate is not None:
        return duplicate
    body = itemschema.entry(args.id, args.title, itemschema.STATUS_CANDIDATE, stamp)
    return _write(repo, body, f"add {args.id}", args.no_commit)


def _run_drop(repo: Path, args: argparse.Namespace, stamp: str) -> int:
    """``drop``: close a candidate with a record, a reason, and the link to both."""
    if args.decision is None:
        return _fail(EXIT_USAGE, "drop needs --decision ID: a kill is a decision",
                     "name the decision record that killed the idea, in the form "
                     "YYYY-MM-DD-<slug>")
    if args.why is None:
        return _fail(EXIT_USAGE, "drop needs --why REASON: a kill without a reason "
                     "is a deletion, not a record",
                     "pass the one line that says why, e.g. --why 'duplicated #12'")
    refused = _refuse_text("--why", args.why, itemschema.WHY_MAX, "the reason")
    if refused is not None:
        return refused
    existing, code = _read_item(repo / itemschema.item_rel(args.id), args.id)
    if code is not None:
        return code
    if existing is None:
        return _fail(EXIT_REFUSAL, f"no item {args.id} is filed under "
                     f"{itemschema.ITEM_DIR}/",
                     "file it first with 'item.py add ID --title TITLE'")
    if existing["status"] in itemschema.TERMINAL_STATUSES:
        return _fail(EXIT_REFUSAL, f"item {args.id} is already "
                     f"{existing['status']}, so there is nothing to drop",
                     "the record of that decision stands: supersede it with a new "
                     "record rather than re-dropping the item")
    citation = orderstate.decision_problems(repo, args.decision, EXIT_IO, EXIT_REFUSAL)
    if citation is not None:
        return _fail(*citation)
    body = itemschema.entry(args.id, existing["title"], itemschema.STATUS_DROPPED,
                            existing["created"], None, args.decision, args.why)
    return _write(repo, body, f"drop {args.id}", args.no_commit)


def _run_promote(repo: Path, args: argparse.Namespace, stamp: str) -> int:
    """``promote``: mark a candidate as the issue it became, refusing a cited item.

    Item-only in this sub-issue: the order side is sub-issue 2's same-commit rewrite,
    so a promote that would leave an order entry citing a newly promoted item is
    refused (exit 4) naming the order path. ``created`` is carried over, never
    restamped: promoting an idea does not make it younger.
    """
    issue: int | None = None
    if args.issue is not None:
        if not orderstate.is_index_text(args.issue) or int(args.issue) < 1:
            return _fail(EXIT_USAGE, f"issue {args.issue!r} is not a positive "
                         "integer", "name the issue by its number, e.g. --issue 42")
        issue = int(args.issue)
    existing, code = _read_item(repo / itemschema.item_rel(args.id), args.id)
    if code is not None:
        return code
    if existing is None:
        return _fail(EXIT_REFUSAL, f"no item {args.id} is filed under "
                     f"{itemschema.ITEM_DIR}/",
                     "file it first with 'item.py add ID --title TITLE'")
    if existing["status"] in itemschema.TERMINAL_STATUSES:
        return _fail(EXIT_REFUSAL, f"item {args.id} is already "
                     f"{existing['status']}, so there is nothing to promote",
                     "a promoted item is ordered with order.py, not re-promoted")
    refusal = _refuse_cited_order(repo, args.id)
    if refusal is not None:
        return refusal
    body = itemschema.entry(args.id, existing["title"], itemschema.STATUS_PROMOTED,
                            existing["created"], issue, existing["decision"], None)
    return _write(repo, body, f"promote {args.id}", args.no_commit)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
