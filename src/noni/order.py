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
       verb that does not own it, --now that is not a valid ISO-8601 timestamp, or a
       --repo that is not a directory
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
import re
import sys
from pathlib import Path

from . import labels, orderschema, orderstate
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


# One token of a usage line, as argparse recognises them: a bracketed group stays
# together, anything else is a word. Same expression argparse's own
# ``_format_usage`` uses to pack a long usage line, kept here so the formatter
# below can pack the two halves of the line itself.
_USAGE_PART_RE = re.compile(r"\(.*?\)+(?=\s|$)|\[.*?\]+(?=\s|$)|\S+")


def _pack_usage_parts(parts: list[str], indent: str, prefix: str | None,
                      text_width: int) -> list[str]:
    """Fill ``parts`` into lines no wider than ``text_width``, the way argparse does.

    A copy of the inner ``get_lines`` of argparse's ``_format_usage`` (including its
    rule that the first line loses the indent when a prefix already sits before it),
    lifted to a module function so :class:`_VerbFirstFormatter` can pack the
    positionals and the optionals separately instead of handing both to one call.
    """
    lines: list[str] = []
    line: list[str] = []
    line_len = len(prefix) - 1 if prefix is not None else len(indent) - 1
    for part in parts:
        if line and line_len + 1 + len(part) > text_width:
            lines.append(indent + " ".join(line))
            line = []
            line_len = len(indent) - 1
        line.append(part)
        line_len += len(part) + 1
    if line:
        lines.append(indent + " ".join(line))
    if prefix is not None and lines:
        lines[0] = lines[0][len(indent):]
    return lines


class _VerbFirstFormatter(argparse.HelpFormatter):
    """Put the verb positionals ahead of the flag block in the ``usage:`` line.

    argparse composes the usage line as ``optionals + positionals``, unconditionally:
    with ``--repo`` required and five flags declared before the verbs, ``order.py
    --help`` rendered ``... [--no-commit] subcommand [issue]``, burying the one word
    the caller has to choose. The docstring's Usage block and
    ``skills/direction/SKILL.md`` both spell the verb first, and a help line that
    contradicts the two texts a reader copies from is the bug (issue #77).

    Handing the parent a reordered action list does not work: it splits the list
    back into optionals and positionals before it renders. So this formatter renders
    the two halves itself with argparse's own action formatter -- which is what
    keeps every ``metavar``, bracket and required-argument marking exactly as
    argparse would print them -- and packs them with :func:`_pack_usage_parts`, so
    ``COLUMNS`` still decides where the line breaks. The argument surface, the group
    sections, the ``choices``/``metavar`` table and the refusal wording of an
    argparse error are untouched, and a caller that passed its own ``usage=`` is
    passed straight through.
    """

    def _format_usage(self, usage, actions, groups, prefix):
        positionals = [action for action in actions if not action.option_strings]
        optionals = [action for action in actions if action.option_strings]
        if usage is not None or not positionals or not optionals:
            # Nothing to move: a caller-supplied line, a flags-only parser and a
            # positionals-only parser all render as the parent renders them.
            return super()._format_usage(usage, actions, groups, prefix)
        if prefix is None:
            prefix = " " * self._current_indent + "usage: "
        parts = [self._format_actions_usage(positionals, groups),
                 self._format_actions_usage(optionals, groups)]
        text_width = max(self._width - self._current_indent, 11)
        indent = " " * (len(prefix) + len(self._prog) + 1)
        lines = _pack_usage_parts([self._prog] + _USAGE_PART_RE.findall(parts[0]),
                                  indent, prefix, text_width)
        lines.extend(_pack_usage_parts(_USAGE_PART_RE.findall(parts[1]),
                                       indent, None, text_width))
        return prefix + "\n".join(lines) + "\n\n"


def _digests(data: bytes) -> str:
    """A short stable digest for a run message; never a path, never file bytes."""
    return hashlib.sha1(data).hexdigest()[:7]


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
    parser = argparse.ArgumentParser(
        prog=labels.ORDER,
        description="Write the ordered list of issues the operator wants worked next "
                    "(noni/direction/order.json) and commit it.",
        formatter_class=_VerbFirstFormatter,
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
