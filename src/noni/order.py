"""Order the work the operator wants next: write noni/direction/order.json and commit it.

The order is one committed, ordered list of open issues: position in the list IS
the order, an issue appears at most once, and every entry carries the time the
operator last confirmed it. This writer is the only writer of that file and it
never contacts a tracker: an issue number is checked only to be a positive
integer, so the core stays viable with no adapter installed.

The file holds two fields:

  schema   -- "noni.order/1", or "noni.order/2" for an order that cites an item
  entries  -- [{issue, decision, confirmed, why}] in the order the operator wants,
              where an entry of a /2 order names item instead of issue

``decision`` is the id of the decision record that set the entry's position and
is never empty: an entry whose ``decision`` is a JSON null, a blank string or
absent is not an order this writer writes (exit 4, naming the entry), and the
census reports the same artifact as ``ordering-malformed`` (15). A run that supplies
one is refused (exit 4) when no file under
noni/decisions/ carries that id, or when the record it finds is already
superseded, and the hint names the record that superseded it. ``confirmed`` is
stamped by the writer (add and confirm stamp it with this run's UTC time, or
with --now when given); a run never leaves it empty. ``why`` is optional: an entry
written without it holds the three fields it held before the field existed, byte for
byte, and ``add --why REASON`` records the operator's one line of reason for the
position. It is the same rule a decision record's rationale obeys: one non-blank
line within the bound ``itemschema.WHY_MAX`` states, refused at the flag (exit 2) and
reported by both censuses naming the field ``why``. A move or a confirm restamps an
entry and never drops the reason it carries. ``move`` may also take ``--decision ID``,
which replaces the moved entry's citation with that record's id under the same
live-record rule ``add`` obeys, so an entry re-ranked under a new decision keeps its
position and carries the record that explains it. Without ``--to`` the position is
unchanged, and ``confirmed`` is still restamped: a run that re-cites a position is the
operator answering for it. A correction of the order
is another run of this command, so the file keeps one owner.

An entry may cite a filed idea instead of an issue: ``add --item ID`` writes an
``item`` entry, which is what makes the artifact ``noni.order/2``. The two subjects are
exclusive -- an entry names one of them, never both and never neither -- and the id is
the store's own, checked against ``noni/items/`` before a position is granted to it. The
writer emits ``/2`` for a run that has an item entry to write and ``/1`` for every run
over an order that holds none, so a queue of issues is never restamped into a version it
does not use; both versions are read.

Usage:
    order.py --repo REPO add ISSUE [--at N] [--decision ID] [--why REASON] [--now ISO-8601] [--no-commit]
    order.py --repo REPO add --item ID [--at N] --decision ID [--why REASON] [--now ISO-8601] [--no-commit]
    order.py --repo REPO move ISSUE [--to N] [--decision ID] [--now ISO-8601] [--no-commit]
    order.py --repo REPO remove ISSUE [--now ISO-8601] [--no-commit]
    order.py --repo REPO confirm [ISSUE] [--now ISO-8601] [--no-commit]

Exit codes:
    0  the order was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, a subcommand outside add/move/remove/confirm,
       an issue that is not a positive integer, a missing --decision on add, an add that
       names both an issue and --item or neither, an --item that is not an item id, an
       empty, multi-line or over-long --why, a --why handed to a verb that is not
       add, a --decision handed to remove or confirm, an --at or
       --to that is not a 1-based position of the resulting list, a flag passed to the
       verb that does not own it, --now that is not a valid ISO-8601 timestamp, a
       --repo that is not a directory, or a noni/, noni/direction or noni/decisions
       directory -- every one from the state root down to the artifact -- that is not
       a plain path this writer may read or write through (a symlink, a plain file, a
       socket or a device, each asked of lstat before any read, write or mkdir, and an
       absent one admitted because the first add creates it)
    3  a path this writer needs could not be read or written, or a git call failed or
       timed out: the order file is not a regular file at its path (a symlink, a
       directory, an unreadable file), the decision ledger could not be looked in, a
       decision record it must read is unreadable, the item store could not be listed
       for an --item check or an item file it must read is unreadable, the artifact could not be written, or the commit step failed (the file is left written and named, never claimed as
       committed), or the freshness probe could not answer (a ``git show`` that
       timed out or failed for a reason that told us nothing)
    4  what the order itself refuses: the issue is already listed (add), absent from the
       order (move, remove, confirm), no file under noni/decisions/ carries the given
       --decision id (add, or a move that re-cites an entry), the record it finds is
       superseded (the hint names its successor),
       no item of that id is filed under noni/items/ or the one it finds is dropped
       (add --item),
       an entry of the existing file whose decision is null, blank or absent (the refusal
       names the entry), or the existing order file is not the artifact this writer writes
       (unparseable, wrong schema, or malformed entries) so overwriting it would destroy an
       order, or nothing this run planned from is what it read: the committed
       order bytes moved ("the order changed since it was read; re-run", so the
       caller's re-run plans against what the other writer committed), or the file
       at the artifact's path did ("the file changed since it was read; restore it
       or discard the change", which no re-run settles -- the fix names the
       checkout that does)

Every refusal (2, 3 or 4) leaves the artifact untouched: reads and checks
happen before any write -- including the re-read of the committed bytes that
refuses a run whose order moved underneath it, which is answered before a byte
is written or staged -- the write goes to a temp file in its own directory and
moves into place with os.replace, and the commit stages only the path this
command wrote (git add -- <path> then git commit --only -- <path>), so a file
somebody else had staged is neither committed nor unstaged. --no-commit writes
through the same chain, leaves the file uncommitted and prints one line saying
so. Every run prints the resulting order, one line per entry: the 1-based
position, the issue (or the item an entry of a /2 order cites), and the decision
(or -) and confirmed timestamp it carries.
The path the success line names (wrote, committed, or left uncommitted) is the
artifact's real location as seen from the caller's working directory: ``--repo``
followed by noni/direction/order.json, spelled exactly the same with and without
--no-commit.

The artifact's shape lives in orderschema.py in the package, the git and
atomic-write mechanics in order_gitwrite.py, the reads of that state (the
artifact, the ledger and its records) in orderstate.py, and the usage line and the
verb parser in order_plan.py, beside the plans it parses to. All four are package
imports: inside an installed wheel there is no sibling file to load by path, and
no directory of the package ever goes on ``sys.path``, so no caller can put a
lookalike ahead of them. This file owns the verbs, the exit codes, the plan and
the commit.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from . import (
    _path_kind,
    itemschema,
    labels,
    order_add,
    order_commit,
    order_plan,
    order_probe,
    orderschema,
    orderstate,
)

# The state reader reports a refusal as a (headline, hint) pair and leaves the
# code to the writer, so the one table of codes stays here and the reader's
# answers arrive pre-coded at the call sites below.
_fail = orderstate._fail

# The git layer the run ends with: ``order_commit`` calls it, and the writer's git-layer
# tests replace this name to drive a hung or failing git.
gitwrite = order_commit.gitwrite

# Every return path names one of these, and the 'Exit codes:' block above carries
# exactly this set (tests/test_order_writer_docs.py pins the two together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_IO: int = 3
EXIT_REFUSAL: int = 4


# The verbs the writer owns, in the order every document lists them, so the unknown-verb
# refusal, the missing-verb hint and the usage line cannot name three different sets.
VERBS: tuple[str, ...] = ("add", "move", "remove", "confirm")

# The directories this run reads or writes, in the order the guard walks them: ``noni``
# first (a link there hides every path beneath it from ``lstat``), then the artifact's
# directory and the ledger ``add --decision`` looks a record up in. The wording and the
# walk live in the guard; see :func:`_refuse_linked_state`.
_GUARDED_DIRS: tuple[str, ...] = ("noni", orderschema.ORDER_DIR, orderstate.DECISIONS_DIR)

# The usage line and the parser of the verb slot live in ``order_plan.py`` (which is
# where ``add``'s plan already moved for the same size limit): both are decisions about
# the command line rather than about the order, and the file whose docstring publishes
# the codes stays the owner of the codes themselves.
_USAGE = order_plan.USAGE


class _VerbedParser(order_plan.VerbedParser):
    """The writer's parser: the verb parser of :mod:`noni.order_plan`, on this code.

    A subclass rather than the shared class because the exit code and the verb list are
    this writer's own, and handing them at every call site would be a second place to
    get them wrong. The tests that run ``--help`` drive the class through ``main``, so
    the parser the help prints is the parser this writer builds.
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs["verbs"] = VERBS
        kwargs["usage_exit"] = EXIT_USAGE
        super().__init__(*args, **kwargs)


def _digests(data: bytes) -> str:
    """A short stable digest for a run message; never a path, never file bytes."""
    return hashlib.sha1(data).hexdigest()[:7]


def _refuse_linked_state(repo: Path, verb: str) -> int | None:
    """The exit-2 refusal for a ``--repo`` this writer may not read or write, or None.

    One seam for both ``noni/`` questions of :data:`_GUARDED_DIRS`, in the order and
    with the wording :func:`noni._path_kind.refuse_state_root` owns. Only ``add`` is
    admitted to the state-root question: it is this writer's one sanctioned creator,
    while ``move``, ``remove`` and ``confirm`` create nothing legitimate and are
    refused ahead of the reads that would otherwise answer "no decision record is in
    the ledger". ``EXIT_USAGE`` is the code docs/PRODUCT.md 7 gives ``order`` for a
    wrong path; the guard runs before the artifact read, the lookup and every mkdir.
    """
    refused = _path_kind.refuse_state_root(repo, verb == "add", _GUARDED_DIRS)
    return None if refused is None else _fail(EXIT_USAGE, *refused)


def _render(body: dict):
    """The canonical bytes for ``body``, or the refusal naming why none exist.

    One call to the state module's renderer -- the same call ``orderstate.read_order``
    makes when it compares a file it read against the form this writer writes, so the
    two halves cannot drift apart on the canonical contract.
    """
    return orderstate.render(body)


def main(argv: list[str] | None = None) -> int:
    parser = _VerbedParser(
        prog=labels.ORDER,
        description="Write the ordered list of issues the operator wants worked next "
                    "(noni/direction/order.json) and commit it.",
        usage=_USAGE,
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
                             "(required for add; move may take one to re-cite an "
                             "entry it restamps)")
    parser.add_argument("--item", default=None, metavar="ID",
                        help="the id of a filed item to order instead of an issue "
                             "(add only; an entry naming an item makes the artifact "
                             "noni.order/2)")
    parser.add_argument("--why", default=None, metavar="REASON",
                        help="the operator's one line of reason for the position "
                             "(add only; a non-empty single line within the "
                             "rationale bound)")
    parser.add_argument("--now", default=None, metavar="ISO-8601",
                        help="fixed UTC timestamp for the confirmed stamp "
                             "(default: the current UTC time)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file and leave it uncommitted for the caller")
    args = parser.parse_args(argv)

    subcommand = args.subcommand
    if subcommand not in VERBS:
        return _fail(EXIT_USAGE, f"subcommand {subcommand!r} is not one of "
                     "add, move, remove or confirm",
                     f"{labels.ORDER} --repo REPO add ISSUE --decision ID | "
                     "move ISSUE --to N | remove ISSUE | confirm [ISSUE]")

    # --at belongs to add and --to to move and nothing else: a flag that means
    # nothing for the verb it was passed with is a usage error, not a hint the
    # run quietly ignores.
    if subcommand != "add" and args.at is not None:
        return _fail(EXIT_USAGE, f"--at belongs to add, not {subcommand}",
                     f"to place an entry with {subcommand} pass --to N")
    if subcommand != "move" and args.to is not None:
        return _fail(EXIT_USAGE, f"--to belongs to move, not {subcommand}",
                     "--to is only how move names a position")
    if args.decision is not None and subcommand not in ("add", "move"):
        # ``move`` owns the flag too since issue #134: an entry re-ranked under a new
        # decision keeps its position and takes the new citation, resolved by the same
        # live-record rule ``add`` obeys. ``remove`` and ``confirm`` still own nothing of
        # it: one drops the entry and the other restamps what is there, so neither can
        # answer for a citation the operator handed it.
        return _fail(EXIT_USAGE, f"--decision belongs to add and move, not {subcommand}",
                     "only add and move set a position's decision; confirm restamps "
                     "what is there")
    if args.why is not None and subcommand != "add":
        # A reason belongs to the moment a position is taken. A verb that quietly
        # dropped one would lose what the operator typed, so the run is refused and
        # names the flag instead.
        return _fail(EXIT_USAGE, f"--why belongs to add, not {subcommand}",
                     "only add records a reason; the other verbs answer to an entry "
                     "that already carries one")


    # add names one subject and never two: an issue number or --item ID, asked of the
    # two tokens before either is validated, so `add 7 --item x` is refused for naming
    # two subjects and not for whichever one is also malformed.
    if args.issue is not None and args.item is not None:
        # Asked of every verb: a run naming two subjects has to be told which it meant.
        problem = order_add.subject_problems(args.issue, args.item)
        if problem is not None:
            return _fail(EXIT_USAGE, *problem)
    if subcommand == "add":
        problem = order_add.subject_problems(args.issue, args.item)
        if problem is not None:
            return _fail(EXIT_USAGE, *problem)

    # The subject token: a positive integer in ASCII decimal digits, checked before the
    # file is opened, so a typo cannot decide which entry of a real order gets touched.
    # confirm is the one verb that may omit it, which means every entry at once. An
    # ``--item`` may name an entry for the three rearranging verbs too, and then the
    # token is the id: the type of ``subject`` tells the plan which kind of entry to
    # reach, so ``move 7`` can never move an item's position.
    issue: int | None = None
    subject: int | str | None = None
    if subcommand == "confirm" and args.issue is None and args.item is None:
        pass
    elif subcommand != "add" and args.item is not None:
        subject = args.item
    elif subcommand == "add" and args.item is not None:
        pass
    else:
        token = args.issue
        if token is None:
            return _fail(EXIT_USAGE, f"{subcommand} needs an issue number",
                         f"{labels.ORDER} --repo REPO {subcommand} 42")
        if not orderstate.is_index_text(token) or int(token) < 1:
            return _fail(EXIT_USAGE, f"issue {token!r} is not a positive integer",
                         "name the issue by its number, e.g. 42")
        issue = int(token)
        subject = issue

    if subcommand == "add" and args.decision is None:
        return _fail(EXIT_USAGE, "add needs --decision ID: an added position is a decision",
                     "name the decision record that put this issue there, or order it "
                     "with order.py confirm if it is already listed")

    stamp, err = orderstate.now_iso(args.now)
    if err:
        return _fail(EXIT_USAGE, err, "pass --now as e.g. 2026-10-27T09:00:00Z, or drop it "
                                      "to stamp this run's time")

    repo = Path(args.repo)
    # The state root is checked before the artifact is read or the decision
    # looked up: --repo naming no directory is a usage error (the code every
    # other flag mistake takes), not a missing order or an absent decision, and
    # the message names the argument the caller passed. Same shape as
    # register.py, close.py, release.py and claim.py, which all refuse here too.
    if not repo.is_dir():
        return _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
                     "pass the repository root that holds (or will hold) "
                     "noni/direction/order.json")
    # Every directory this run reads or writes, asked of ``lstat`` before the first
    # read: a linked noni/ or noni/direction would otherwise carry the artifact and
    # the decision read below into a tree outside the state root.
    linked = _refuse_linked_state(repo, subcommand)
    if linked is not None:
        return linked
    order_path = repo / orderschema.ORDER_REL

    # --- reads: the artifact, then the decision it must cite -----------------
    # Read once, before anything is written: a --no-commit run leaves its own
    # bytes in the working tree for the next run to read, and a plan built from
    # entries this run has already restamped would not be a plan at all.
    read = orderstate.read_order(order_path)
    if isinstance(read, orderstate.OrderFaulted):
        return _fail(EXIT_IO, read.headline, read.hint)
    if isinstance(read, orderstate.OrderRefused):
        return _fail(EXIT_REFUSAL, read.headline, read.hint)
    entries = [dict(entry) for entry in read.entries]
    before = read.before

    # --- the plan: what the entries become, decided before any write ---------
    # The item store joins the guarded list for a run that names one, so an
    # ``add --item`` whose store is a link is refused as a bad ``--repo`` (2) rather
    # than reached through: the same walk, the same code and the same wording the
    # writer already applies to ``noni`` and ``noni/direction``.
    if args.item is not None and subcommand == "add":
        refused = _path_kind.refuse_state_root(repo, True,
                                               (*_GUARDED_DIRS, itemschema.ITEM_DIR))
        if refused is not None:
            return _fail(EXIT_USAGE, *refused)
    verb: str
    if subcommand == "add":
        assert args.decision is not None
        planned = order_add.plan_add(repo, entries, issue, args.item, args.decision,
                                     args.at, stamp, _fail, EXIT_IO, EXIT_USAGE,
                                     EXIT_REFUSAL, why=args.why)
        if planned.refusal is not None:
            return planned.refusal
        entries, verb = planned.entries, planned.verb
    elif subcommand == "move":
        assert subject is not None
        planned = order_plan.plan_move(entries, subject, args.to, stamp, _fail,
                                      EXIT_USAGE, EXIT_REFUSAL, repo=repo,
                                      decision=args.decision, exit_io=EXIT_IO)
    elif subcommand == "remove":
        assert subject is not None
        planned = order_plan.plan_remove(entries, subject, _fail, EXIT_REFUSAL)
    else:
        planned = order_plan.plan_confirm(entries, subject, stamp, _fail, EXIT_REFUSAL)
    if planned.refusal is not None:
        return planned.refusal
    entries, verb = planned.entries, planned.verb

    # --- the write: every check above has passed -----------------------------
    # The version the plan's own entries describe, never a constant: a queue of issues
    # stays ``/1`` and an order holding an item entry is ``/2``, which is the whole rule
    # for how a ``/2`` artifact ever comes to exist. Restamping a document into the
    # version its contents do not use would make the marker say nothing.
    body = {"schema": orderschema.schema_for(entries), "entries": entries}
    rendered = _render(body)
    if isinstance(rendered, orderstate.RenderRefused):
        # Not bytes this writer can produce. The plan is built from validated
        # values, so the file keeps the bytes it had and nothing is claimed.
        return _fail(EXIT_REFUSAL, rendered.headline, rendered.hint)
    # --- the freshness probe: did anything move under this run? ----------------
    # The lost-update guard; order_probe.py owns it and the reason it sits here.
    # --no-commit is exempt because that route runs no git at all.
    #
    # It runs BEFORE the no-change shortcut below, and that ordering is load-bearing.
    # ``rendered == before`` compares the bytes this run would write against the bytes it
    # read out of the file, so a run whose file has been moved and moved back -- or
    # whose file has been restamped to exactly what this verb would have stamped --
    # reaches "nothing left to add" while HEAD and the index hold an order it never
    # compared itself against. Reporting success for that run is a lie about the state of
    # the repository: the guard is the step that says whether this run may write, and a
    # run that may not write is refused whether or not its own bytes happen to match.
    if not args.no_commit:
        refused = order_probe.probe(repo, order_path, before, verb, args.repo,
                                    EXIT_IO, EXIT_REFUSAL)
        if refused is not None:
            return refused
    if before is not None and rendered == before:
        # The file already holds the bytes this run would write, so there is nothing
        # left to add: nothing is staged, nothing is committed, no HEAD moves.
        #
        # The probe owns the decision about whether this run may write at all, and it
        # runs ABOVE this shortcut: a no-change run still commits its index entry
        # when HEAD moved, so a guard that sat below it would let the one run shape
        # that commits without planning anything slip the lost-update check.
        #
        # So this arm is reached only once the guard has said HEAD, the index and the
        # file all still hold what this run read -- which is exactly when "unchanged"
        # is a true sentence, and the only reading under which the order below can
        # print it. --no-commit keeps its own no-git contract and #76's idempotent
        # repeat by taking the shortcut on the file's bytes alone.
        orderstate.print_order(entries, labels.ORDER)
        print(f"{labels.ORDER}: {orderschema.ORDER_REL} is unchanged; nothing to "
              "commit")
        return EXIT_OK

    # The three steps to the end of the run belong to the module that owns them: the
    # parent-directory fault the pre-read walk does not cover, the atomic write, and the
    # two git calls. Each hands back its (headline, hint) pair for this file to print
    # under the I/O code, so the voice and the table of codes stay here.
    faulty = order_commit.parent_refusal(repo)
    if faulty is not None:
        return _fail(EXIT_IO, *faulty)
    faulty = order_commit.write(repo, rendered)
    if faulty is not None:
        return _fail(EXIT_IO, *faulty)

    orderstate.print_order(entries, labels.ORDER)
    digest = _digests(rendered)
    if args.no_commit:
        # The census reads the working tree, so this file reads as uncommitted;
        # the one line says so and names the path, and committing it is the
        # caller's job.
        order_commit.report(order_path, verb, True)
        return EXIT_OK

    refused = order_commit.commit(repo, verb, digest)
    if refused is not None:
        return _fail(EXIT_IO, *refused)
    order_commit.report(order_path, verb, False)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
