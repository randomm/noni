"""Record the standing intent: write noni/direction/intent.md and commit it.

The intent file is the small principles document an agent reads first at session
start: what the project is for, the principles it steers by, the things it never
does, and the questions it must ask before acting. It is prose, not a record, and
it is optional: a project that has written none has no intent rows in its census.

This writer is the only writer of that file. It validates the text before it
writes anything, and it refuses to write an intent that cites no decision: the
``--decision`` id must name a file under ``noni/decisions/`` whose status is not
``superseded``, so standing direction always traces to a record the ledger holds.

Usage:
    intent.py --repo REPO set --from FILE --decision ID [--now ISO-8601]
    [--no-commit]

Exit codes:
    0  the file was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, a subcommand outside set, a missing or
       unknown --from/--decision, a --from that is not a readable regular file (a
       directory, a symlink) or is not UTF-8, a --now that is not a UTC timestamp,
       a --repo that is not a directory, or a noni/, noni/direction or noni/decisions
       directory -- every one from the state root down to the intent file -- that is
       not a plain path this writer may read or write through (a symlink, a plain
       file, a socket or a device, each asked of lstat before any read, write or
       mkdir, and an absent one admitted because the first set creates it)
    3  a path this writer needs could not be read or written, or a git call failed
       or timed out: the intent file at its path is not a regular file (a symlink,
       a directory, a device), the decision record it must read is unreadable, the
       file could not be written, or the commit step failed (the file is left
       written and named, never claimed as committed)
    4  what the intent itself refuses: the source text is not an intent file (a
       required section missing, repeated or out of order, over the line cap, or
       the Last-confirmed line absent or repeated), or no file under
       noni/decisions/ carries the given --decision id, or that record is
       superseded (the hint names its successor)

Every refusal (2, 3 or 4) leaves the tracked files byte-identical: reads and
checks happen before any write, the write goes to a temp file in its own
directory and moves into place with os.replace, and the commit stages only the
path this command wrote (git add -- <path> then git commit --only -- <path>), so
a file somebody else had staged is neither committed nor unstaged. --no-commit
writes through the same chain, leaves the file uncommitted and prints one line
saying so. A successful run prints one line naming the path and the decision it
cites. That path names the file's real location from the caller's working
directory: --repo joined to noni/direction/intent.md, spelled the same with and
without --no-commit.

The file's shape lives in intentschema.py in the package, the same rules the
census's ``intent`` class applies to the bytes on disk; the git and atomic-write
mechanics are reused read-only from order_gitwrite.py. No directory of the
package ever goes on ``sys.path``, so a lookalike earlier on the path cannot be
trusted as this writer's schema.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path

from . import _path_kind, intentschema, labels, orderstate
from . import order_gitwrite as gitwrite

# The state reader reports a refusal as a (headline, hint) pair and leaves the
# code to the writer, so the one table of codes stays here and the reader's
# answers arrive pre-coded at the call sites below. The label is overridden so a
# refusal reached through the reader reads as coming from ``intent.py``, the
# program that ran, and not from the order writer these mechanics came from.
_fail = partial(orderstate._fail, label=f"{labels.INTENT}:")

# Every return path names one of these, and the 'Exit codes:' block above
# carries exactly this set.
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_IO: int = 3
EXIT_REFUSAL: int = 4


# The one verb the writer owns, spelled once so the usage line, the unknown-verb
# refusal and the missing-verb hint cannot name three different sets.
VERBS: tuple[str, ...] = ("set",)

# The directories this run reads or writes, in the order the guard walks them:
# ``noni`` itself first (a link there hides every path beneath it from ``lstat``),
# then the directory the intent file lives in, then the ledger the ``--decision``
# citation is looked up in. The wording, the walk and the declined-``lstat`` rule
# all live in the guard; see :func:`_refuse_linked_state`.
_GUARDED_DIRS: tuple[str, ...] = ("noni", intentschema.INTENT_DIR,
                                  orderstate.DECISIONS_DIR)

# The verb list the two refusals name, spelled once from ``VERBS``.
_VERB_LIST = ", ".join(VERBS)

# The usage line, spelled once and handed to argparse as ``usage=``.
#
# argparse composes a usage line as ``optionals + positionals``, unconditionally, so
# the verb was printed behind every flag while this docstring's ``Usage:`` block and
# ``skills/direction/SKILL.md`` both spell it first. ``order.py`` carries the same
# decision, the reasoning and the 3.14 history behind it: this is the same line for
# the parser that writer does not have (issue #98). The flag block is the parser's
# own declaration, in declaration order, with the metavar argparse prints for each,
# and the flag-set parity of ``tests/test_intent_writer_docs.py`` compares the two:
# a flag added to the parser belongs here too.
_USAGE = (f"{labels.INTENT} --repo REPO subcommand"
          " [--from FILE] [--decision ID] [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional. The
# verbs are added to argparse's own refusal rather than replacing it, so the usage
# line, the wording and the exit code stay what every other tool prints for the same
# mistake.
_MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class _VerbedParser(argparse.ArgumentParser):
    """The parser of a one-verb writer, naming the verbs when the verb is missing.

    ``intent.py --repo R`` with no verb got argparse's own refusal, which names the
    slot (``subcommand``) and not the one word that fills it: only an *invalid*
    verb reached the fix line that named it, so the commonest mistake printed the
    least useful answer (issue #98). This parser keeps argparse's own refusal and
    adds the verbs to it, so the usage line, the wording and the exit code are
    unchanged and one more line names the accepted verb.

    ``order.py`` carries the same parser; the two writers share only this shape,
    which their own verb sets make different. The parser is not reshaped with
    ``add_subparsers`` or ``choices=``, both of which would move the verb out of the
    usage line and take the refusal off the path the pinned wording stands for.
    """

    def error(self, message: str):
        if _MISSING_SUBCOMMAND in message:
            self.print_usage(sys.stderr)
            print(f"{self.prog}: {message}", file=sys.stderr)
            print(f"{self.prog}: fix: choose from: {_VERB_LIST}", file=sys.stderr)
            raise SystemExit(EXIT_USAGE)
        super().error(message)


def _refuse_linked_state(repo: Path) -> int | None:
    """The exit-2 refusal for a ``--repo`` this writer may not read or write, or None.

    One seam for both ``noni/`` questions, which :func:`noni._path_kind.refuse_state_root`
    asks of the same ``lstat`` in one order: the obstruction question over every
    component of :data:`_GUARDED_DIRS` (a link is never followed or written through),
    then the state-root question for a tree holding no ``noni/`` at all. ``set`` is
    always admitted to the second: it is this writer's one verb and its one sanctioned
    creator (the first file makes ``noni/direction``), and its citation is still
    resolved against the ledger. The code is ``EXIT_USAGE``, the one docs/PRODUCT.md 7
    gives ``intent`` for a wrong path, and the guard runs before the draft is opened,
    before the citation is looked up, and before every mkdir.
    """
    refused = _path_kind.refuse_state_root(repo, True, _GUARDED_DIRS)
    return None if refused is None else _fail(EXIT_USAGE, *refused)


def main(argv: list[str] | None = None) -> int:
    parser = _VerbedParser(
        prog=labels.INTENT,
        description="Write the standing intent file the agents read first "
                    f"({intentschema.INTENT_REL}) and commit it.",
        usage=_USAGE,
    )
    parser.add_argument("--repo", required=True,
                        help="the state root that holds (or will hold) noni/")
    parser.add_argument("subcommand", help="set")
    parser.add_argument("--from", dest="source", default=None, metavar="FILE",
                        help="the Markdown file to install as the intent (required)")
    parser.add_argument("--decision", default=None, metavar="ID",
                        help="the decision record id this intent cites (required)")
    parser.add_argument("--now", default=None, metavar="ISO-8601",
                        help="UTC timestamp to stamp the Last-confirmed line with, "
                             "instead of this run's UTC day (reproducible output)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file and leave it uncommitted for the caller")
    args = parser.parse_args(argv)

    if args.subcommand not in VERBS:
        return _fail(EXIT_USAGE, f"subcommand {args.subcommand!r} is not 'set'",
                     f"{labels.INTENT} --repo REPO set --from FILE --decision ID")
    if args.source is None:
        return _fail(EXIT_USAGE, "set needs --from FILE: the intent's text comes from a file",
                     f"{labels.INTENT} --repo REPO set --from intent.md --decision ID")
    if args.decision is None:
        return _fail(EXIT_USAGE, "set needs --decision ID: standing direction cites a record",
                     "name the decision record that set this intent, in the form "
                     "YYYY-MM-DD-<slug>")

    repo = Path(args.repo)
    if not repo.is_dir():
        return _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
                     "pass the state root that holds (or will hold) "
                     f"{intentschema.INTENT_REL}")
    # Every directory this run reads or writes, asked of ``lstat`` before the first
    # read: a linked noni/ or noni/direction would otherwise carry the intent file
    # and the citation read below into a tree outside the state root.
    linked = _refuse_linked_state(repo)
    if linked is not None:
        return linked

    # The clock is read before anything is written, so a run that stamps a day it
    # cannot name refuses before touching the tree rather than after.
    day, problem = _run_day(args.now)
    if problem:
        return _fail(EXIT_USAGE, f"--now {args.now!r} is not {problem}",
                     "pass a UTC timestamp such as 2026-10-27T12:00:00Z, or omit "
                     "--now to stamp this run's UTC day")

    # --- reads: the source text, its shape, then the decision it must cite ---
    source = Path(args.source)
    kind, why = orderstate.file_kind(source)
    if kind == "dir":
        return _fail(EXIT_USAGE, f"--from {args.source} is a directory, not a file",
                     "pass the path of the Markdown file holding the intent")
    if kind == "refusal":
        # A draft behind a link is not this writer's to read: following it puts a
        # file outside the caller's stated input into the intent, and a link is
        # never what a caller means when it names a draft.
        return _fail(EXIT_USAGE, f"--from {args.source} {why}",
                     "pass the regular file itself, not a link to it")
    if kind != "regular":
        return _fail(EXIT_USAGE, f"--from {args.source} is not a readable regular file",
                     "pass the path of the Markdown file holding the intent")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # The bytes are the operator's own draft, but a row that echoed them
        # would print unvalidated content; the refusal names the rule instead.
        return _fail(EXIT_USAGE, f"--from {args.source} is not valid UTF-8",
                     "save the intent as UTF-8 text and re-run")
    except OSError as exc:
        return _fail(EXIT_IO, f"--from {args.source} could not be read "
                     f"({exc.__class__.__name__}: {exc.strerror or exc})",
                     "check the file is readable, then re-run intent.py")
    found = intentschema.problems(text)
    if found:
        return _fail(EXIT_REFUSAL,
                     f"{args.source} is not an intent file this writer writes: "
                     + "; ".join(found),
                     "the file must carry the four level-2 headings "
                     + ", ".join(f"## {name}" for name in intentschema.REQUIRED_SECTIONS)
                     + f" in that order, exactly one '{intentschema.LAST_CONFIRMED_PREFIX} "
                     "YYYY-MM-DD' line, and stay within "
                     f"{intentschema.MAX_LINES} lines; start from "
                     "skills/direction/references/intent-template.md")

    refusal = orderstate.decision_problems(repo, args.decision, EXIT_IO, EXIT_REFUSAL)
    if refusal is not None:
        return _fail(*refusal)

    body = _stamped(text, day)

    # --- the write: every check above has passed -----------------------------
    target = repo / intentschema.INTENT_REL
    if target.parent.exists() and not target.parent.is_dir():
        return _fail(EXIT_IO, f"{intentschema.INTENT_DIR} is not a directory",
                     f"remove {intentschema.INTENT_DIR} or move it aside, then re-run "
                     "intent.py")
    kind, why = orderstate.file_kind(target)
    if kind == "dir":
        return _fail(EXIT_IO, f"{intentschema.INTENT_REL} is not a regular file: a "
                     "directory sits at that path",
                     f"remove the directory at {intentschema.INTENT_REL}, then re-run "
                     "intent.py")
    if kind == "refusal":
        return _fail(EXIT_IO, f"{intentschema.INTENT_REL} {why}",
                     "remove that path or point --repo at the tree that holds the "
                     "intent, then re-run intent.py")
    data = body.encode("utf-8")
    if target.is_file():
        try:
            if target.read_bytes() == data:
                print(f"{labels.INTENT}: {intentschema.INTENT_REL} is unchanged; "
                      "nothing to commit")
                return EXIT_OK
        except OSError as exc:
            return _fail(EXIT_IO, f"{intentschema.INTENT_REL} could not be read "
                         f"({exc.__class__.__name__}: {exc.strerror or exc})",
                         f"check that {intentschema.INTENT_REL} is readable, then "
                         "re-run intent.py")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        gitwrite.write_atomic(target, data)
    except OSError as exc:
        return _fail(EXIT_IO, gitwrite.written(exc, f"{intentschema.INTENT_REL} could "
                                               "not be written"),
                     f"check that {intentschema.INTENT_DIR} is writable, then re-run "
                     "intent.py")

    if args.no_commit:
        print(f"{labels.INTENT}: wrote {target}; left uncommitted: "
              "commit this path before running the census")
        return EXIT_OK

    rel = intentschema.INTENT_REL
    added = gitwrite.git(repo, "add", "--", rel)
    if added.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git add timed out for {rel} after {gitwrite.GIT_TIMEOUT}s "
                     f"(the file is written, its staged state unknown)",
                     "check 'git status --porcelain' once git answers, then stage and "
                     "commit the path by hand or re-run intent.py")
    if added.returncode != 0:
        detail = added.stderr.strip() or added.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git add failed for {rel} (the file is written, "
                     f"unstaged): {detail}",
                     f"run 'git status --porcelain -- {rel}' and stage the path by "
                     "hand, or re-run intent.py")
    subject = f"intent: {args.decision}"
    committed = gitwrite.git(repo, "commit", "-q", "-m", subject, "--only", "--", rel)
    if committed.returncode == gitwrite.GIT_TIMEOUT_RC:
        return _fail(EXIT_IO, f"git commit timed out for {rel} after "
                     f"{gitwrite.GIT_TIMEOUT}s (the file is written and staged, not "
                     "committed)",
                     "check 'git log -1 --oneline' once git answers, then commit the "
                     "path by hand or re-run intent.py")
    if committed.returncode != 0:
        detail = committed.stderr.strip() or committed.stdout.strip() or "no reason given"
        return _fail(EXIT_IO, f"git commit failed for {rel} (the file is written and "
                     f"staged, not committed): {detail}",
                     f"commit {rel} by hand, or re-run intent.py once git answers")
    print(f"{labels.INTENT}: committed {target} (decision {args.decision})")
    return EXIT_OK


def _run_day(value: str | None) -> tuple[date, str | None]:
    """(day, problem): the date the run stamps, or why ``value`` names none.

    ``--now`` is the reproducibility knob ``order.py`` carries for the same
    reason: a test, a replay, or a docs gate needs a file whose stamp it can
    predict, and the census compares that line against a day the operator can
    name. Only a timestamp that carries its UTC offset is accepted, and only the
    instant matters -- the calendar day it falls on in UTC is what lands in the
    file. A malformed value is a usage error rather than a silent fall back to the
    clock, because a run that stamped a day it did not say it used would be
    reporting a confirmation it did not perform.
    """
    if value is None:
        return datetime.now(timezone.utc).date(), None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return date.min, "a valid UTC timestamp"
    if parsed.tzinfo is None:
        return date.min, "a UTC timestamp: it carries no offset"
    return parsed.astimezone(timezone.utc).date(), None


def _stamped(text: str, day: date) -> str:
    """``text`` with its ``Last-confirmed:`` line restamped to ``day``.

    The writer stamps the line the way ``order.py`` stamps ``confirmed``: the day
    an operator set the intent is the writer's to record, not the draft's to
    claim. One line is guaranteed by the validation that ran before this call, so
    the rewrite replaces it rather than appending a second one.
    """
    line = intentschema.stamp_line(day)
    out = [line if intentschema.is_stamp_line(raw) else raw
           for raw in text.split("\n")]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
