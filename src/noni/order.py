"""Order the work the operator wants next: write noni/direction/order.json and commit it.

The order is one committed, ordered list of open issues: position in the list IS
the order, an issue appears at most once, and every entry carries the time the
operator last confirmed it. This writer is the only writer of that file and it
never contacts a tracker: an issue number is checked only to be a positive
integer, so the core stays viable with no adapter installed.

The file holds two fields:

  schema   -- "noni.order/1"
  entries  -- [{issue, decision, confirmed, why}] in the order the operator wants

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
line within the bound ``_why.WHY_MAX`` states, refused at the flag (exit 2) and
reported by both censuses naming the field ``why``. A move or a confirm restamps an
entry and never drops the reason it carries. A correction of the order
is another run of this command, so the file keeps one owner.

``move`` owns the decision field as well as the position: ``move ISSUE --decision ID``
replaces the entry's decision with ``ID`` and leaves its position alone, and with
``--to`` it does both in one run. The record is resolved by the same live-record rule as
``add --decision`` and on the same codes (exit 3 for an unreadable ledger, exit 4 for a
record that is missing or superseded), the entry's ``confirmed`` is restamped as a move
always restamps it, and a run that changes no byte commits nothing. ``--to`` is required
only when ``--decision`` is absent: a move of neither is not a move.

An order that still names the removed item store is refused, never rewritten. A file
whose ``schema`` is ``noni.order/2``, or an entry that carries an ``item`` key, is
reported by every reader and by the census as ``ordering-malformed`` with a message that
says item entries are no longer supported and names the repair (re-add each entry with
``add ISSUE --decision ID`` after filing it as an issue). Nothing is silently dropped and
no file is restamped down to ``/1``, because every verb rebuilds the whole list and an
accepting reader would delete the operator's entry.

Usage:
    order.py --repo REPO add ISSUE [--at N] [--decision ID] [--why REASON] [--now ISO-8601] [--no-commit]
    order.py --repo REPO move ISSUE [--to N] [--decision ID] [--now ISO-8601] [--no-commit]
    order.py --repo REPO remove ISSUE [--now ISO-8601] [--no-commit]
    order.py --repo REPO confirm [ISSUE] [--now ISO-8601] [--no-commit]

Exit codes:
    0  the order was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, a subcommand outside add/move/remove/confirm,
       an issue that is not a positive integer, a missing --decision on add, a move that
       names neither --to nor --decision, an
       empty, multi-line or over-long --why or a --why handed to a verb that is not
       add, an --at or
       --to that is not a 1-based position of the resulting list, a flag passed to the
       verb that does not own it (--decision belongs to add and move), --now that is not a valid ISO-8601 timestamp, a
       --repo that is not a directory, or a noni/, noni/direction or noni/decisions
       directory -- every one from the state root down to the artifact -- that is not
       a plain path this writer may read or write through (a symlink, a plain file, a
       socket or a device, each asked of lstat before any read, write or mkdir, and an
       absent one admitted because the first add creates it)
    3  a path this writer needs could not be read or written, or a git call failed or
       timed out: the order file is not a regular file at its path (a symlink, a
       directory, an unreadable file), the decision ledger could not be looked in, a
       decision record it must read is unreadable, the artifact could not be written, or the commit step failed (the file is left written and named, never claimed as
       committed), or the freshness probe could not answer (a ``git show`` that
       timed out or failed for a reason that told us nothing)
    4  what the order itself refuses: the issue is already listed (add), absent from the
       order (move, remove, confirm), no file under noni/decisions/ carries the given
       --decision id (add or move), the record it finds is superseded (the hint names its
       successor),
       an entry of the existing file whose decision is null, blank or absent (the refusal
       names the entry), or the existing order file is not the artifact this writer writes
       (unparseable, wrong schema, an order still carrying the removed item store, or
       malformed entries) so overwriting it would destroy an
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
position, the issue, and the decision
(or -) and confirmed timestamp it carries.
The path the success line names (wrote, committed, or left uncommitted) is the
artifact's real location as seen from the caller's working directory: ``--repo``
followed by noni/direction/order.json, spelled exactly the same with and without
--no-commit.

The artifact's shape lives in orderschema.py in the package, the git and
atomic-write mechanics in order_gitwrite.py, and the reads of that state (the
artifact, the ledger and its records) in orderstate.py. All three are package
imports: inside an installed wheel there is no sibling file to load by path, and
no directory of the package ever goes on ``sys.path``, so no caller can put a
lookalike ahead of them. This file owns the verbs, the exit codes, the plan and
the commit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    _path_kind,
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

_MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class _VerbedParser(argparse.ArgumentParser):
    """The parser of a one-verb writer, naming the verbs when the verb is missing.

    ``order.py --repo R`` with no verb got argparse's own refusal, which names the
    slot (``subcommand``) and not the four words that fill it: only an *invalid*
    verb reached the fix line that named them, so the commonest mistake printed the
    least useful answer (issue #98). This parser keeps argparse's own refusal and
    adds the verbs to it, so the usage line, the wording and the exit code are
    unchanged and one more line names the accepted verbs.

    The parser shape is deliberately untouched: ``add_subparsers`` or ``choices=``
    would name the verbs too, but both move the verb out of the usage line and take the
    refusal off the path the pinned wording stands for.
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

    Joined with the same "or" the unknown-verb refusal uses, so the two refusals of
    one mistake cannot answer it twice.
    """
    *first, last = VERBS
    return f"{first[0]} or {last}" if len(first) == 1 \
        else f"{', '.join(first)} or {last}"


def _refuse_linked_state(repo: Path, verb: str) -> int | None:
    """The exit-2 refusal for a ``--repo`` this writer may not read or write, or None.

    One seam for both ``noni/`` questions of :data:`_GUARDED_DIRS`, in the order and with
    the wording :func:`noni._path_kind.refuse_state_root` owns. Only ``add`` is admitted
    to the state-root question: it is this writer's one sanctioned creator, while the
    three rearranging verbs create nothing and are refused ahead of the reads that would
    otherwise answer "no decision record is in the ledger". ``EXIT_USAGE`` is the code
    docs/PRODUCT.md 7 gives ``order`` for a wrong path; the guard runs before the artifact
    read, the lookup and every mkdir.
    """
    refused = _path_kind.refuse_state_root(repo, verb == "add", _GUARDED_DIRS)
    return None if refused is None else _fail(EXIT_USAGE, *refused)


def _plan_move(repo: Path, entries: list, subject: int | str, to: str | None,
               decision: str | None,
               stamp: str) -> order_plan.Planned:
    """The move's plan, called with this writer's codes and its own printer.

    Codes and printer travel in as arguments the way ``orderstate`` takes them, so the one
    table of exit codes stays in the file whose docstring publishes it. The move's own
    questions -- which entry, what position, which record, and whether the ledger still
    stands behind that record -- belong to :func:`noni.order_plan.plan_move`.
    """
    return order_plan.plan_move(repo, entries, subject, to, stamp, decision,
                                _fail, EXIT_IO, EXIT_USAGE, EXIT_REFUSAL)


# The one-line description argparse prints above the flag block, spelled here beside the
# ``Usage:`` line it sits under and handed to the parser's builder.
DESCRIPTION = ("Write the ordered list of issues the operator wants worked next "
               "(noni/direction/order.json) and commit it.")


def _subject_tokens(subcommand: str, issue_token: str | None, label: str,
                    fail) -> tuple[int | str | None, int | str | int | None]:
    """The verb's ``(issue, subject_or_code)``: the token the plan reaches by.

    A positive integer in ASCII decimal digits, asked before the file is opened, so a
    typo cannot decide which entry of a real order gets touched. ``confirm`` may omit it,
    which means every entry at once. A refused token leaves the exit code of the refusal
    ``fail`` already printed in the second slot, which the caller returns.
    """
    if subcommand == "confirm" and issue_token is None:
        return None, None
    if issue_token is None:
        return None, fail(EXIT_USAGE, f"{subcommand} needs an issue number",
                          f"{label} --repo REPO {subcommand} 42")
    if not orderstate.is_index_text(issue_token) or int(issue_token) < 1:
        return None, fail(EXIT_USAGE,
                          f"issue {issue_token!r} is not a positive integer",
                          "name the issue by its number, e.g. 42")
    return int(issue_token), int(issue_token)


def _repo_refusals(repo: Path, repo_arg: str, verb: str) -> int | None:
    """The exit-2 refusal for a ``--repo`` this run may not read or write, or None.

    Two questions about the one path the caller passed, in this order, both before the
    first read: that it is a directory at all; and that the directories it leads to are
    plain paths (:func:`_refuse_linked_state` gives the reason each is asked of ``lstat``
    ahead of the reads). A ``--repo``
    naming no directory is the usage error every other flag mistake
    takes -- not a missing order and not an absent decision -- and the message names the
    argument as the caller passed it, the shape every writer in this package
    takes at the same step.
    """
    if not repo.is_dir():
        return _fail(EXIT_USAGE, f"--repo {repo_arg} is not a directory",
                     "pass the repository root that holds (or will hold) "
                     "noni/direction/order.json")
    return _refuse_linked_state(repo, verb)


def _read_entries(order_path: Path):
    """The entries a run plans from, and the bytes it read, or the code already printed.

    Read once, before anything is written: a ``--no-commit`` run leaves its own bytes in
    the working tree for the next run to read, and a plan built from entries this run has
    already restamped would not be a plan at all. The second slot is the refusal's exit
    code once ``fail`` has printed it; a list of entries is never an int.
    """
    read = orderstate.read_order(order_path)
    if isinstance(read, orderstate.OrderFaulted):
        return None, _fail(EXIT_IO, read.headline, read.hint)
    if isinstance(read, orderstate.OrderRefused):
        return None, _fail(EXIT_REFUSAL, read.headline, read.hint)
    return [dict(entry) for entry in read.entries], read.before


def _write_unchanged(entries: list, rendered: bytes, before: bytes | None) -> int | None:
    """The success of a run whose plan needs no write, or None when it does.

    ``rendered == before`` compares the bytes this run would write against the bytes it
    read out of the file. The probe owns whether this run may write at all, and it runs
    ABOVE this shortcut: a no-change run still commits its index entry when HEAD moved, so
    a guard below the shortcut would let the one run shape that commits without planning
    anything slip the lost-update check. This arm is therefore reached only once the guard
    has said HEAD, the index and the file all still hold what this run read, which is
    exactly when "unchanged" is a true sentence. --no-commit keeps its no-git contract and
    #76's idempotent repeat on the file's bytes alone.
    """
    if before is None or rendered != before:
        return None
    orderstate.print_order(entries, labels.ORDER)
    print(f"{labels.ORDER}: {orderschema.ORDER_REL} is unchanged; nothing to commit")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    # The parser's declarations stay spelled here, beside the ``Usage:`` block they must
    # match: the reader that pins the two together reads the ``add_argument`` calls out of
    # ``main``. Building the parser is the add module's job, and this file's own parser
    # class -- the answer to a missing verb -- is handed to it rather than imported there.
    parser = order_plan.build_parser(_VerbedParser, order_plan.USAGE, labels.ORDER,
                                      DESCRIPTION)
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
                             "(required for add; move replaces the entry's decision "
                             "with it)")
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
        return _fail(EXIT_USAGE, *order_add.unknown_verb(subcommand, labels.ORDER))

    # Every flag the verb was handed but does not own: a flag that means nothing for the
    # verb it came with is a usage error, not a hint the run quietly ignores. The table of
    # owners lives with the verb that owns most of them.
    misplaced = order_add.misplaced_flag(subcommand, args.at, args.to,
                                         args.decision, args.why)
    if misplaced is not None:
        return _fail(EXIT_USAGE, *misplaced)


    # The subject token: an issue number, or nothing at all for a bare ``confirm``.
    issue, subject = _subject_tokens(subcommand, args.issue, labels.ORDER, _fail)
    if isinstance(subject, int) and issue is None:
        # The slot holds a refusal's exit code, not an issue number: see the helper.
        return subject

    if subcommand == "add" and args.decision is None:
        return _fail(EXIT_USAGE, "add needs --decision ID: an added position is a decision",
                     "name the decision record that put this issue there, or order it "
                     "with order.py confirm if it is already listed")

    stamp, err = orderstate.now_iso(args.now)
    if err:
        return _fail(EXIT_USAGE, err, "pass --now as e.g. 2026-10-27T09:00:00Z, or drop it "
                                      "to stamp this run's time")

    repo = Path(args.repo)
    # The state root is asked about before the artifact is read or the decision looked
    # up, so a bad path cannot be reported as a missing order.
    refused = _repo_refusals(repo, args.repo, subcommand)
    if refused is not None:
        return refused
    order_path = repo / orderschema.ORDER_REL

    # --- reads: the artifact, then the decision it must cite -----------------
    entries, before = _read_entries(order_path)
    if isinstance(before, int) and entries is None:
        return before

    # --- the plan: what the entries become, decided before any write ---------
    verb: str
    if subcommand == "add":
        assert args.decision is not None
        planned = order_add.plan_add(repo, entries, issue, args.decision,
                                     args.at, stamp, _fail, EXIT_IO, EXIT_USAGE,
                                     EXIT_REFUSAL, why=args.why)
        if planned.refusal is not None:
            return planned.refusal
        entries, verb = planned.entries, planned.verb
    elif subcommand == "move":
        assert subject is not None
        planned = _plan_move(repo, entries, subject, args.to, args.decision, stamp)
    elif subcommand == "remove":
        assert subject is not None
        planned = order_plan.plan_remove(entries, subject, _fail, EXIT_REFUSAL)
    else:
        planned = order_plan.plan_confirm(entries, subject, stamp, _fail, EXIT_REFUSAL)
    if planned.refusal is not None:
        return planned.refusal
    entries, verb = planned.entries, planned.verb

    # --- the write: every check above has passed -----------------------------
    # The one version the artifact has, stated as a constant: a run can no longer plan an
    # entry of any other shape, and a file that holds one was refused by the read above.
    body = {"schema": orderschema.ORDER_SCHEMA, "entries": entries}
    # The state module's own renderer, the same call ``orderstate.read_order`` makes when
    # it compares a file it read against the form this writer writes, so the two halves
    # cannot drift apart on the canonical contract. Not bytes this writer can produce is a
    # refusal: the plan is built from validated values, so the file keeps the bytes it had
    # and nothing is claimed.
    rendered = orderstate.render(body)
    if isinstance(rendered, orderstate.RenderRefused):
        return _fail(EXIT_REFUSAL, rendered.headline, rendered.hint)
    # --- the freshness probe: did anything move under this run? ----------------
    # The lost-update guard; order_probe.py owns it, the reason it sits here, and the
    # reason it runs before the no-change shortcut below.
    # --no-commit is exempt because that route runs no git at all.
    if not args.no_commit:
        refused = order_probe.probe(repo, order_path, before, verb, args.repo,
                                    EXIT_IO, EXIT_REFUSAL)
        if refused is not None:
            return refused
    unchanged = _write_unchanged(entries, rendered, before)
    if unchanged is not None:
        return unchanged

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
    digest = order_commit.digest(rendered)
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
