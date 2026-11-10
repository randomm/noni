"""Reading the three texts that spell the order command (issue #77, AC1).

The verb's position in ``order --help`` is agreed between three sources: the
``usage:`` line argparse renders from the parser, the ``Usage:`` block in
``order.py``'s docstring, and the four command lines under
``skills/direction/SKILL.md``. A check that reads one of them with its own
hand-rolled parser of the other two can pass while the line still hides the
verb, which is the bug the ticket reports.

So the reading lives here, once, and both test modules that assert the
contract call it: ``tests/test_order_writer_usage.py`` runs the two ``--help``
routes and compares them against these readers, and
``tests/test_order_writer_docs.py`` asserts what the documents themselves say.
The docstring reader is ``order_fixtures``' (it parses the shipped source), and
the width the help wraps at is the harness's pinned ``HELP_COLUMNS`` -- an
unpinned ``COLUMNS`` would move the line break and make the assertion depend on
the terminal it ran in.

A helper module: never named ``test_*``.
"""

from __future__ import annotations

import re

from _harness import REPO
from order_fixtures import (
    SKILL_DIR,
    _docstring,
    _order_ast,
)

# The four verbs the writer accepts, in the order the documents list them.
VERBS = ("add", "move", "remove", "confirm")

# The token argparse prints for the verb positional.
_VERB_TOKEN = "subcommand"
# One token of a usage line: a bracketed group stays together (argparse renders
# an optional positional as ``[issue]`` and every flag as ``[--at N]``), and a
# bracket is never a word boundary, so the group is the unit that may sit either
# side of the verb.
_USAGE_TOKEN_RE = re.compile(r"\[[^\]]*\]|\S+")
# Everything a line may place before the verb without burying it: the program
# name and ``--repo`` with its value, which the documents put first too.
_ALLOWED_BEFORE_VERB = ("order.py", "scripts/order.py", "noni order", "--repo", "REPO")


def first_usage_line(text: str) -> str:
    """The ``usage:`` line, joined across argparse's wraps.

    argparse breaks the line at ``COLUMNS`` (the harness pins 100), so the
    assertion reads the whole usage statement rather than one arbitrary row of
    it. Continuation lines are indented under the prog; joining on a space
    restores the single line argparse composed.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("usage: ")), None)
    assert start is not None, f"no usage line in:\n{text}"
    collected = [lines[start][len("usage: "):]]
    for line in lines[start + 1:]:
        if not line.startswith(" "):
            break
        collected.append(line.strip())
    return " ".join(collected).strip()


def assert_verb_precedes_flags(usage: str, source: str) -> None:
    """Nothing but ``--repo`` and its value comes before the verb in one line.

    Accepts both spellings of the verb: ``subcommand`` as argparse prints it,
    and a real verb (``add``, ``move``, ...) as the two documents print it. The
    comparison is positional, and it is strict: a line whose verb follows the
    flag block fails even when it also mentions ``--repo``, which a bare
    "verb before the first ``--``" test would pass for the pre-fix help line
    (whose ``[issue]`` group carries the only double dash). AC1 forbids a line
    the reader must scan past the flags to find the word they must choose.
    """
    verb_at = _at(usage, _VERB_TOKEN)
    if verb_at < 0:
        verb_at = min((at for at in (_at(usage, verb) for verb in VERBS) if at >= 0),
                      default=-1)
    assert verb_at >= 0, f"{source}: the usage line names no subcommand: {usage!r}"
    assert "--" in usage, f"{source}: the usage line names no flags: {usage!r}"
    head = usage[:verb_at]
    for token in _USAGE_TOKEN_RE.findall(head):
        assert token in _ALLOWED_BEFORE_VERB, (
            f"{source}: the verb is buried behind the flags, so the line "
            f"contradicts the verb-first form the documents print: {usage!r}"
        )
    return None


def _at(text: str, needle: str) -> int:
    """The offset of ``needle`` when it stands as its own word, else -1.

    ``add`` is a substring of a flag name, so a bare ``find`` could read a flag
    as the verb.
    """
    index = text.find(needle)
    while index >= 0:
        before = text[index - 1] if index else " "
        after = text[index + len(needle)] if index + len(needle) < len(text) else " "
        if before.isspace() and after.isspace():
            return index
        index = text.find(needle, index + 1)
    return -1


def docstring_verb_lines() -> list[str]:
    """The ``Usage:`` lines of ``order.py``'s own docstring, one per verb.

    Read from the shipped source through ``order_fixtures``, so the assertion
    holds the product's text and not a copy kept in a test file.

    One line per verb, four verbs: no verb has a second subject form, so the count
    the tests hold a document to is the count of verbs and of lines at once.
    """
    doc = _docstring(_order_ast())
    return usage_verb_lines(doc.splitlines(), "order.py --repo REPO",
                            "docstring Usage block")


def skill_md_verb_lines() -> list[str]:
    """The command lines ``skills/direction/SKILL.md`` prints, one per verb.

    The page is the form the ticket names as correct, so it is read from disk
    rather than quoted here: a page that dropped a verb fails the count rather
    than passing on a stale copy of it.
    """
    text = (REPO / "skills" / "direction" / "SKILL.md").read_text(encoding="utf-8")
    return usage_verb_lines(text.splitlines(), "scripts/order.py --repo REPO",
                            str(SKILL_DIR / "SKILL.md"))


def usage_verb_lines(lines: list[str], prefix: str, where: str) -> list[str]:
    """The command lines of ``lines`` that start with ``prefix``, one verb each.

    Shared by the two documents so the shape they are held to is one shape: every
    line names a verb the parser accepts, and the verbs covered are exactly
    :data:`VERBS` -- each one present once, since no verb has a second subject form.
    """
    found = [line.strip() for line in lines if line.strip().startswith(prefix)]
    assert found, f"{where} prints no order command lines"
    covered: list[str] = []
    for line in found:
        verb = line.split()[3]
        assert verb in VERBS, f"unexpected verb in {where}: {line!r}"
        covered.append(verb)
    assert sorted(covered) == sorted(VERBS), (
        f"{where} must print exactly one line per verb, one of each of "
        f"{sorted(VERBS)}: {found}")
    assert not [line for line in found if "--item" in line], (
        f"{where} still prints the removed item form of add: {found}")
    return found
