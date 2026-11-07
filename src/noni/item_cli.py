"""The command line ``item`` accepts: the usage line, the verb parser, the flag owners.

Split out of ``item.py`` for the size limit, along the seam the writer already had:
``item.py`` owns the verbs, their refusals and their exit codes, and this module owns
the shape of the command line that reaches them. Three things live here because each is
a decision about *parsing* rather than about the store:

- :data:`USAGE`, the one usage line argparse prints (see its own comment for why it
  cannot be derived from the parser);
- :class:`VerbedParser`, the parser that names the four verbs when the verb is missing;
- :data:`FLAG_OWNER`, which verb owns which flag, read by the writer to refuse a flag
  passed to the verb that does not carry it.

The exit code the parser raises with is the writer's own usage code, handed in at the
call so the parser holds no number of its own and one code table stays in the writer.
"""

from __future__ import annotations

import argparse
import sys

from . import labels

# The verbs the writer owns, in the order every document lists them. One tuple here so
# the unknown-verb refusal in the writer, the missing-verb hint and the usage line
# cannot name three different sets.
VERBS: tuple[str, ...] = ("add", "list", "drop", "promote")

# The flags each verb owns, spelled once so the refusal that names the verb a flag
# belongs to and the parser's own declaration cannot drift apart.
FLAG_OWNER = {"--title": "add", "--decision": "drop", "--why": "drop",
              "--issue": "promote"}

# The usage code the parser raises with when the verb slot is empty. It is the
# writer's own code (docs/PRODUCT.md 7 gives ``item`` 2 for a wrong command line), and
# it is repeated here rather than imported because the parser must not reach back into
# the module that constructs it; tests/test_item_writer_docs.py pins the writer's
# ``Exit codes:`` block, the parser's refusal and this number together.
_USAGE_EXIT = 2

# The verb list the missing-subcommand hint prints, spelled once from ``VERBS``.
VERBS_JOINED = ", ".join(VERBS)

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
USAGE = (f"{labels.ITEM} --repo REPO subcommand [id]"
          " [--title TITLE] [--decision ID] [--why REASON] [--issue N]"
          " [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional, and the
# line argparse prints above it. argparse turns this refusal into usage-plus-error
# itself, so the verbs are added to *that* pair rather than to the message text.
MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class VerbedParser(argparse.ArgumentParser):
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
        if MISSING_SUBCOMMAND in message:
            self.print_usage(sys.stderr)
            print(f"{self.prog}: {message}", file=sys.stderr)
            print(f"{self.prog}: fix: choose from: {missing_verb_hint()}",
                  file=sys.stderr)
            raise SystemExit(_USAGE_EXIT)
        super().error(message)


def missing_verb_hint() -> str:
    """The verb list the missing-subcommand hint prints.

    Joined with the same "or" the unknown-verb refusal above uses -- one sentence for
    one set, so the two refusals of the same mistake cannot answer it twice.
    """
    *first, last = VERBS
    if len(first) == 1:
        return f"{first[0]} or {last}"
    return f"{', '.join(first)} or {last}"
