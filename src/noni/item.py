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
       a missing --title on add, a missing --issue on promote, --decision or --why
       passed to a verb that does not own them, an id that is not lowercase letters, digits and dashes (or ends in
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

The artifact's shape lives in itemschema.py in the package, the two guards the verbs
run first in item_guard.py, the reads of the order and the ledger it must not
contradict in item_reads.py, and the file and git mechanics in item_write.py (whose
own git calls are reused from order_gitwrite.py). All are package imports: inside an
installed wheel there is no sibling file to load by path, and no directory of the
package ever goes on ``sys.path``, so no caller can put a lookalike ahead of them. This
file owns the verbs, the exit codes, the plan and what each run prints.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import (
    item_guard,
    item_reads,
    item_write,
    itemschema,
    labels,
    orderstate,
)


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

    The guard's rule, its walk and its wording are ``item_guard``'s; the code and the
    voice of the printed refusal are this writer's, handed over at the call.
    """
    return item_guard.linked_state(repo, verb, _GUARDED_DIRS, _fail, EXIT_USAGE)


def _commit(repo: Path, rel: str, subject: str, shown: Path) -> int:
    """Stage and commit exactly ``rel``, or the exit-3 code naming which step failed.

    The git mechanics and their four refusals are ``item_write.commit``'s; the code
    table, the printed voice and the committed line's label are this writer's, handed
    over at the call, so a hung or failing git is classified one way by every route.
    """
    return item_write.commit(repo, rel, subject, shown, _fail, EXIT_IO, EXIT_OK,
                             labels.ITEM)


def _write(repo: Path, body: dict, verb: str, no_commit: bool) -> int:
    """Render, then write and commit only the one item path. Checks all ran already.

    The three answers this step can give -- written and committed, written and left
    uncommitted, already exactly these bytes -- are the writer's contract and stay
    here, in the writer's voice and its codes. The file mechanics themselves are
    ``item_write.write_item``'s, handed back the commit step so the git answers keep
    their codes and their committed line beside the verb that ran.
    """
    rel = itemschema.item_rel(body["id"])
    try:
        rendered = itemschema.item_bytes(body)
    except ValueError:
        # Not bytes this writer can produce. Every value of a plan here is validated
        # before it gets this far, so this is the writer's own bug rather than the
        # operator's: the file keeps the bytes it had and nothing is claimed.
        return _fail(EXIT_REFUSAL, "the planned item cannot be written as JSON",
                     "re-run item.py; if it repeats, remove the item and re-file "
                     "the idea")
    verdict, headline, hint = item_write.write_item(
        repo, body, rendered, _committable(repo, verb, no_commit, rendered))
    if verdict == "refuse":
        # Two shapes reach here: the environment refusals of the file step, which
        # carry their own two lines and take exit 3, and a commit step that already
        # printed its own refusal and returned its own code -- for which this prints
        # nothing and hands back the code the commit chose.
        return EXIT_OK if not headline else _fail(EXIT_IO, headline, hint)
    print(f"{labels.ITEM}: {body['id']} is {body['status']} ({verb})")
    if verdict == "unchanged":
        print(f"{labels.ITEM}: {rel} is unchanged; nothing to commit")
    return EXIT_OK


def _committable(repo: Path, verb: str, no_commit: bool, rendered: bytes):
    """The commit step ``item_write.write_item`` runs once the file is in place.

    A step of the verb above, curried into a callback so the file module never names
    git, a code or a line of output: ``--no-commit`` answers for itself, and otherwise
    the verb's own commit runs and turns its code back into the (verdict, headline,
    hint) triple the write speaks. The digest is taken over the bytes actually put on
    disk, which is what makes a repeat of the same item a repeat of the same subject.
    """
    def commit(shown: Path, path_rel: str) -> tuple[str, str, str | None]:
        if no_commit:
            print(f"{labels.ITEM}: wrote {shown}; left uncommitted: commit this path "
                  "before running the census")
            return "ok", "", None
        code = _commit(repo, path_rel, f"items: {verb} [{_digests(rendered)}]", shown)
        return ("ok", "", None) if code == EXIT_OK else ("refuse", "", None)

    return commit


def _refuse_cited_order(repo: Path, item_id: str) -> int | None:
    """The refusal ``promote`` owes an order that cites this item, or None.

    The question, its two answers and their wording are ``item_reads``'; the code
    table and the printed voice are this writer's, handed over at the call.
    """
    return item_reads.refuse_cited_order(repo, item_id, _fail, EXIT_IO, EXIT_REFUSAL)


def _state_root(args: argparse.Namespace, verb: str) -> Path | None:
    """The ``--repo`` this run works in, or None after printing its refusal.

    A directory that is not a directory is a wrong argument on every verb; the
    state-root and symlink questions are asked of the verbs that read or write state
    (see :func:`_run_list` for the one verb that does neither).
    """
    repo = Path(args.repo)
    if not repo.is_dir():
        _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
              "pass the repository root that holds (or will hold) "
              f"{itemschema.ITEM_DIR}/")
        return None
    linked = _refuse_linked_state(repo, verb) if verb != "list" else None
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
                        help="the issue a promoted item became (required for "
                             "promote: a promoted item that names no issue was "
                             "promoted to nothing)")
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
    """``list``: print the store, newest first, and change nothing.

    The read-only verbs run no state-root question, which is the same rule the census
    follows: a tree that holds no ``noni/items/`` has no items, and that is the honest
    answer rather than a finding. ``order``'s ``move``/``remove``/``confirm`` are
    refused for the same state because they would *create* the direction directory;
    nothing a list can do creates anything, and refusing it would make the census's own
    answer (an absent store is silence, exit 0) unreachable from the tool that shows
    the store.
    """
    repo = _state_root(args, "list")
    if repo is None:
        return EXIT_USAGE
    bodies, code = item_reads.listing_bodies(repo, _fail, EXIT_IO)
    if code is not None:
        return code
    print(f"{labels.ITEM}: {itemschema.ITEM_DIR} "
          f"({len(bodies or [])} item{'y' if len(bodies or []) == 1 else 'ies'})")
    for body in sorted(bodies or [], key=lambda b: (b["created"], b["id"]),
                       reverse=True):
        print(item_reads.listing_line(body))
    return EXIT_OK


def _run_add(repo: Path, args: argparse.Namespace, stamp: str) -> int:
    """``add``: file a new candidate, refusing anything that duplicates a record."""
    if args.title is None:
        return _fail(EXIT_USAGE, "add needs --title TITLE: an idea is filed under "
                     "a name",
                     f"{labels.ITEM} --repo REPO add my-idea --title 'Cache the "
                     "census'")
    refused = item_guard.bad_text("--title", args.title, itemschema.TITLE_MAX,
                                      "the title", _fail, EXIT_USAGE)
    if refused is not None:
        return refused
    existing, code = item_reads.read_item(repo / itemschema.item_rel(args.id),
                                          args.id, _fail, EXIT_IO, EXIT_REFUSAL)
    if code is not None:
        return code
    if existing is not None:
        return _fail(EXIT_REFUSAL, f"item {args.id} is already filed as "
                     f"{existing['status']}",
                     f"its record is what it is: drop it with 'item.py drop "
                     f"{args.id} --decision ID --why REASON' or leave it a candidate")
    duplicate = item_reads.dropped_title_taken(repo, args.title, _fail, EXIT_IO,
                                               EXIT_REFUSAL)
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
    refused = item_guard.bad_text("--why", args.why, itemschema.WHY_MAX,
                                    "the reason", _fail, EXIT_USAGE)
    if refused is not None:
        return refused
    existing, code = item_reads.read_item(repo / itemschema.item_rel(args.id),
                                          args.id, _fail, EXIT_IO, EXIT_REFUSAL)
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
    if issue is None:
        # A promoted item is one that became an issue, and the schema refuses a
        # ``promoted`` item that carries none, so a verb that wrote one would leave a
        # file the next ``add`` refuses to write over and the census reports
        # ``item-malformed``. Refused here, at the verb that owes the field, for the
        # same reason ``drop`` owes ``--decision`` and ``--why``.
        return _fail(EXIT_USAGE, "promote needs --issue N: a promoted item is one "
                     "that became an issue, and one that names none was promoted to "
                     "nothing", "name the issue it became, e.g. --issue 42, or leave "
                     "it a candidate until an issue is filed for it")
    existing, code = item_reads.read_item(repo / itemschema.item_rel(args.id),
                                          args.id, _fail, EXIT_IO, EXIT_REFUSAL)
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
                            existing["created"], issue)
    return _write(repo, body, f"promote {args.id}", args.no_commit)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
