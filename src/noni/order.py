"""Order the work the operator wants next: write noni/direction/order.json and commit it.

The order is one committed, ordered list of open issues: position in the list IS
the order, an issue appears at most once, and every entry carries the time the
operator last confirmed it. This writer is the only writer of that file and it
never contacts a tracker: an issue number is checked only to be a positive
integer, so the core stays viable with no adapter installed.

The file holds two fields:

  schema   -- "noni.order/1", the artifact's version marker
  entries  -- [{issue, decision, confirmed}] in the order the operator wants

``decision`` is the id of the decision record that set the entry's position and
is never empty: an entry whose ``decision`` is a JSON null, a blank string or
absent is not an order this writer writes (exit 4, naming the entry), and the
census reports the same artifact as ``ordering-malformed`` (15). A run that supplies
one is refused (exit 4) when no file under
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
       verb that does not own it, --now that is not a valid ISO-8601 timestamp, a
       --repo that is not a directory, or a noni/, noni/direction or noni/decisions
       directory -- every one from the state root down to the artifact -- that is not
       a plain path this writer may read or write through (a symlink, a plain file, a
       socket or a device, each asked of lstat before any read, write or mkdir, and an
       absent one admitted because the first add creates it)
    3  a path this writer needs could not be read or written, or a git call failed or
       timed out: the order file is not a regular file at its path (a symlink, a
       directory, an unreadable file), the decision ledger could not be looked in, a
       decision record it must read is unreadable, the artifact could not be written, or
       the commit step failed (the file is left written and named, never claimed as
       committed)
    4  what the order itself refuses: the issue is already listed (add), absent from the
       order (move, remove, confirm), no file under noni/decisions/ carries the given
       --decision id, the record it finds is superseded (the hint names its successor),
       an entry of the existing file whose decision is null, blank or absent (the refusal
       names the entry), or the existing order file is not the artifact this writer writes
       (unparseable, wrong schema, or malformed entries) so overwriting it would destroy an
       order

Every refusal (2, 3 or 4) leaves the artifact untouched: reads and checks
happen before any write, the write goes to a temp file in its own directory and
moves into place with os.replace, and the commit stages only the path this
command wrote (git add -- <path> then git commit --only -- <path>), so a file
somebody else had staged is neither committed nor unstaged. --no-commit writes
through the same chain, leaves the file uncommitted and prints one line saying
so. Every run prints the resulting order, one line per entry: the 1-based
position, the issue, and the decision (or -) and confirmed timestamp it carries.
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
import hashlib
import sys
from pathlib import Path

from . import _path_kind, labels, orderschema, orderstate
from . import order_gitwrite as gitwrite

# The state reader reports a refusal as a (headline, hint) pair and leaves the
# code to the writer, so the one table of codes stays here and the reader's
# answers arrive pre-coded at the call sites below.
_fail = orderstate._fail

# Every return path names one of these, and the 'Exit codes:' block above
# carries exactly this set (tests/test_order_writer_docs.py pins the two together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_IO: int = 3
EXIT_REFUSAL: int = 4


# The verbs the writer owns, in the order every document lists them. One tuple so
# the unknown-verb refusal, the missing-verb hint and the usage line cannot name
# three different sets.
VERBS: tuple[str, ...] = ("add", "move", "remove", "confirm")

# The directories this run reads or writes, in the order the guard walks them:
# ``noni`` itself first (a link there hides every path beneath it from ``lstat``),
# then the two directories this writer touches -- the artifact's, and the ledger
# ``add --decision`` looks a record up in. The wording, the walk and the
# declined-``lstat`` rule all live in the guard; see :func:`_refuse_linked_state`.
_GUARDED_DIRS: tuple[str, ...] = ("noni", orderschema.ORDER_DIR, orderstate.DECISIONS_DIR)

# The verb list the unknown-verb refusal and the usage line take, spelled once from
# ``VERBS``. The missing-subcommand hint spells its conjunction itself, and its own
# test pins that text.
_VERB_LIST = ", ".join(VERBS)

# The usage line, spelled once and handed to argparse as ``usage=``.
#
# argparse composes a usage line as ``optionals + positionals``, unconditionally, so
# with ``--repo`` required and five flags declared before the verbs, ``order.py
# --help`` rendered ``... [--no-commit] subcommand [issue]`` and buried the one word
# the caller has to choose. The docstring's ``Usage:`` block and
# ``skills/direction/SKILL.md`` both spell the verb first, and a help line that
# contradicts the two texts a reader copies from is the bug (issue #77).
#
# A literal is the only public way to put the verb first. A formatter subclass used
# to derive the line by calling argparse's private ``_format_usage`` and
# ``_format_actions_usage``, and Python 3.14 removed the second of those: on 3.14
# every usage print -- ``--help``, a missing subcommand, an unknown flag -- died
# with an ``AttributeError`` instead of printing anything (issue #98). A literal
# keeps the rendering inside argparse: it still prepends ``usage:``, still wraps the
# line at ``COLUMNS``, and still prints it on all three of those paths.
#
# The flag block is the parser's own declaration, in declaration order, with the
# metavar argparse prints for each, and it is compared against that declaration by
# ``tests/test_order_writer_usage.py`` and the flag-set parity of
# ``tests/test_order_writer_docs.py``: a flag added to the parser belongs here too.
_USAGE = (f"{labels.ORDER} --repo REPO subcommand [issue]"
          " [--at N] [--to N] [--decision ID] [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional, and
# the line argparse prints above it. argparse turns this refusal into usage-plus-
# error itself, so the verbs are added to *that* pair rather than to the message
# text: a subclass that re-raised it would print its own usage instead, and
# ``first_usage_line`` reads the ``usage:`` line out of the refusal.
_MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class _VerbedParser(argparse.ArgumentParser):
    """The parser of a one-verb writer, naming the verbs when the verb is missing.

    ``order.py --repo R`` with no verb got argparse's own refusal, which names the
    slot (``subcommand``) and not the four words that fill it: only an *invalid*
    verb reached the fix line that named them, so the commonest mistake printed the
    least useful answer (issue #98). This parser keeps argparse's own refusal and
    adds the verbs to it, so the usage line, the wording and the exit code are
    unchanged and one more line names the accepted verbs.

    The parser shape is deliberately untouched. ``add_subparsers`` or ``choices=``
    would name the verbs too, but both move the verb out of the usage line and take
    the refusal off the path the pinned wording stands for, which is what
    ``tests/test_order_writer_usage.py`` exists to catch.
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

    Joined with the same "or" the unknown-verb refusal above uses -- one sentence
    for one set, so the two refusals of the same mistake cannot answer it twice.
    """
    *first, last = VERBS
    if len(first) == 1:
        return f"{first[0]} or {last}"
    return f"{', '.join(first)} or {last}"


def _digests(data: bytes) -> str:
    """A short stable digest for a run message; never a path, never file bytes."""
    return hashlib.sha1(data).hexdigest()[:7]


def _refuse_linked_state(repo: Path) -> int | None:
    """The exit-2 refusal for a ``noni/`` this writer may not read or write, or None.

    :func:`noni._path_kind.direction_refusal` asks the directory question of every
    component of :data:`_GUARDED_DIRS`; this seam gives its refusal this writer's
    code and voice. The code is ``EXIT_USAGE``, the one docs/PRODUCT.md 7 gives
    ``order`` for a wrong path, and the guard runs before the artifact read and the
    ``--decision`` lookup, so no bytes outside the state root are read either.
    """
    refused = _path_kind.direction_refusal(repo, _GUARDED_DIRS)
    return None if refused is None else _fail(EXIT_USAGE, *refused)


def _render(body: dict):
    """The canonical bytes for ``body``, or the refusal naming why none exist.

    One call to the state module's renderer, which is the same call
    ``orderstate.read_order`` makes to compare a file it read against the form
    this writer writes: two copies of the render-and-refuse step is two places
    for the canonical contract to be broken, and the two halves must agree byte
    for byte or every canonical fixture becomes a refusal.
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
                             "(required for add)")
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
    if args.decision is not None and subcommand != "add":
        return _fail(EXIT_USAGE, f"--decision belongs to add, not {subcommand}",
                     "only add takes a position's decision; confirm restamps what is there")

    # The issue token: a positive integer spelled in ASCII decimal digits, checked
    # before the file is opened, so a typo cannot decide which entry of a real
    # order gets touched. confirm is the one verb that may omit it, which means
    # every entry at once.
    issue: int | None = None
    if subcommand == "confirm" and args.issue is None:
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
    linked = _refuse_linked_state(repo)
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
        refusal = orderstate.decision_problems(repo, args.decision, EXIT_IO, EXIT_REFUSAL)
        if refusal is not None:
            return _fail(*refusal)
        count = len(entries) + 1
        if args.at is None:
            position = count
        else:
            position, problem = orderstate.parse_index(args.at, "--at", count)
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
        position, problem = orderstate.parse_index(args.to, "--to", len(entries))
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
    if isinstance(rendered, orderstate.RenderRefused):
        # Not bytes this writer can produce. The plan is built from validated
        # values, so the file keeps the bytes it had and nothing is claimed.
        return _fail(EXIT_REFUSAL, rendered.headline, rendered.hint)
    if before is not None and rendered == before:
        # A run that changes no byte (confirming an entry already stamped at the
        # time it was given) has nothing to commit: it prints the order it read
        # and says the file is unchanged, rather than committing a --allow-empty
        # commit no one asked for.
        orderstate.print_order(entries, labels.ORDER)
        print(f"{labels.ORDER}: {orderschema.ORDER_REL} is unchanged; nothing to "
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

    orderstate.print_order(entries, labels.ORDER)
    digest = _digests(rendered)
    if args.no_commit:
        # The census reads the working tree, so this file reads as uncommitted;
        # the one line says so and names the path, and committing it is the
        # caller's job.
        # The caller-cwd form (``--repo`` plus the artifact's path under it), the
        # same token the committed route prints, so one writer prints one path
        # form whatever the flag says (issue #77, AC2).
        print(f"{labels.ORDER}: wrote {order_path}; left uncommitted: "
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
    print(f"{labels.ORDER}: committed {order_path} ({verb})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
