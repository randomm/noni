"""What the two shell census entry points run: the unified census, one group.

``skills/steering-ledger/scripts/census.sh`` and
``skills/sessions-claims/scripts/census-sessions.sh`` are bash wrappers that
carry no rules of their own. Each takes the one directory its caller names,
resolves it, and hands it here; this module turns that (directory, options)
pair into the argv of a unified-census run restricted to the group the entry
point belongs to, and calls ``census.main`` with it. The wrapper's exit code is
therefore the census's own, and the classes it runs are the ones the check
contract declares — not a list a shell script keeps a copy of.

``--repo`` is set to the *parent* of the named directory, never to the directory
itself. Every path the census reports is rooted into the tree ``--repo`` names,
and a ledger or register the caller passed from outside that tree — an absolute
path, or a relative walk out of the cwd — has no root-relative name to take, so
the census falls back to the path's last segment. Naming the directory itself as
the repo would put every row of a run the docs tell people to type into that
fallback: the single word ``decisions`` where a reader expects a path. Naming the
parent keeps an in-tree ledger spelled the way a census over the whole repo
spells it, and leaves the genuinely out-of-tree case to the census's own naming
rule.

The one-directory rule, the refusal of a register that is not there, and the
refusal of a path the caller points at through a link are enforced here, before
the census is called. All three belong to the wrapper because the census cannot
see them: the unified census takes its state paths as flags and audits the tree
``--repo`` names, so an unnamed directory, a second directory, or a path that is
not a directory at all is invisible to a run over the tree that contains it --
and a census that reads nothing has no verdict to give.

The options a caller may type are an allowlist, not a walk: one directory,
``--json``, ``--strict``, and ``--now`` in either ``--now VALUE`` or
``--now=VALUE`` form (see :data:`_ALLOWED_SWITCHES` and :data:`_VALUE_FLAG`),
plus ``--help``/``-h`` as the whole command line.
Everything else is refused here with the census's usage code and never reaches
the census -- any other option, any prefix of one, a bare ``--``, a single-dash
token, and any second directory.

That the list is short is the point, and it is why the wrappers no longer ask
the census's parser what a token means. Each round of review of the old
pass-through found one more token the hand-written walk had misread -- a state
path typed as ``--led=/x``, a ``--help`` in the middle of a line, a single-dash
token, a filter whose value was stranded by the token before it -- and every one
of them ended as a census run the caller had not asked for, usually an exit 0
where the plain run fails. A wrapper that recognises four spellings and refuses
the rest cannot misread a token: the refused set is whatever is not on the list,
so it includes every flag the census gains later, and no token has to be
classified to be answered.

Filters are the deliberate casualty. ``--only`` and ``--skip`` belong to
``noni census``, which takes them, resolves them against the check contract, and
refuses a class it does not define; a wrapper that forwarded one would be a
second route to a filtered verdict, filtered by a list this module does not own,
over one group. The caller who wants a filter runs the census itself.

Nothing here opens a path, evaluates a class, or invents an exit code. Every
refusal below returns the census's usage code and names what it refused, in the
census's own style.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .census import LEDGER_CHECKS, SESSION_CHECKS, main
from .census_report import CLASS_CODE, EXIT_USAGE

# Whether the wrapper's help, its refusals and its usage line are spelled with
# the entry point's own name: the word a reader has to match against the
# terminal they typed into.
_ENTRY_POINTS: dict[str, tuple[str, frozenset[str]]] = {
    "census.sh": ("decisions", LEDGER_CHECKS),
    "census-sessions.sh": ("sessions", SESSION_CHECKS),
}

# The flag each group's directory reaches the census through, keyed by the
# group's own class set rather than by a name a caller could mistype.
_GROUP_FLAG: dict[frozenset[str], str] = {
    LEDGER_CHECKS: "ledger",
    SESSION_CHECKS: "sessions",
}

# The options a caller may type at an entry point. Everything outside these two
# sets is refused (see the module docstring for why the rule is an allowlist and
# not a translation), so both sets are compared to a token exactly as typed.
#
# The switches take no value. ``--now`` is the only value-taking entry, because
# it is the one a reproducible run has to be able to pin; both its forms are
# spelled here rather than derived, so the list a reviewer reads is the list the
# walk compares against.
_ALLOWED_SWITCHES = frozenset({"--json", "--strict"})
_VALUE_FLAG = "--now"
_VALUE_FLAG_PREFIX = "--now="

# The whole command line that asks for the entry point's help text instead of a
# census. ``--help`` beside a directory is not that: the caller wanted a census
# and mistyped something, and guessing which half they meant is not this
# module's call.
_HELP_TOKENS = frozenset({"--help", "-h"})


def _only(checks: frozenset[str]) -> list[str]:
    """Repeated ``--only`` flags for one group, in the check contract's own order.

    The order comes from ``CHECKS`` and not from the frozenset, so the bytes of a
    wrapper's command line do not depend on a hash.
    """
    args: list[str] = []
    for name in CLASS_CODE:
        if name in checks:
            args += ["--only", name]
    return args


def argv_for(target: str, options: list[str], checks: frozenset[str]) -> list[str]:
    """The unified census's argv for one group's census of ``target``.

    ``target`` reaches ``--ledger`` / ``--sessions`` exactly as the caller
    spelled it — including the empty string, which the census names in its own
    refusal — while ``--repo`` is built from the resolved path, the only form
    whose parent reliably means the directory above it. ``options`` is the
    allowlisted tail :func:`_allowed_options` returned, in the order typed.
    """
    resolved = Path(target).resolve()
    return ["--repo", str(resolved.parent), "--" + _GROUP_FLAG[checks], target,
            *_only(checks), *options]


def _positionals(argv: list[str]) -> list[str]:
    """The bare tokens of one permitted command line: the directories the caller named.

    ``--now`` consumes the token after it here as well as in the option check, and
    both walks must agree or the timestamp a caller typed for ``--now`` arrives
    here as a second directory and the run is refused for a path nobody named.
    The rule is the same one the check applies -- an exact ``--now`` swallows the
    token after it, ``--now=<stamp>`` swallows nothing -- so there is one meaning
    for a token in this module, not one per walk.
    """
    positional: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == _VALUE_FLAG:
            index += 2
        elif not token.startswith("-"):
            positional.append(token)
            index += 1
        else:
            index += 1
    return positional


def _refuse(label: str, noun: str, detail: str) -> int:
    """One usage refusal, in the census's style, returning the census's code.

    The line names the entry point the caller typed, the fault, and the path they
    named -- the three things a reader needs to fix a command line -- and the code
    is ``EXIT_USAGE``, the code the census's own argparse refusals carry.
    """
    print(f"{label}: error: {detail} (usage: {label} [--help] "
          f"[--json | --strict | --now <ISO-8601>] <state-root>/noni/{noun})",
          file=sys.stderr)
    return EXIT_USAGE


def _first_refused_option(argv: list[str]) -> str | None:
    """The first token an entry point may not accept, or ``None`` for a clean line.

    The walk is the whole classifier: a token is accepted when it is exactly one
    of the allowlisted names, when it is ``--now=VALUE`` (any value -- the census
    decides what a timestamp is), when it is the value standing after a
    recognised ``--now``, or when it is a bare token at all -- a bare token is the
    directory, which is the argument the entry point exists to take, and its
    shape (none, one, two) is the directory checks' business, not this walk's.
    Nothing else is recognised, so nothing else can be
    misread as a flag or a value: an option that does not exist
    yet, a prefix of one, a bare ``--``, and a single-dash token are all refused
    on the same plain rule.

    The value of ``--now`` is consumed by position and never re-examined, so a
    stamp beginning with a dash stays the census's timestamp to refuse rather
    than becoming an option here. A ``--now`` with nothing after it is refused
    here too: it has no value to hand on, and the option check runs first so the
    option-less line never reaches :func:`_allowed_options`, which indexes that
    value.
    """
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _ALLOWED_SWITCHES or token.startswith(_VALUE_FLAG_PREFIX):
            index += 1
        elif token == _VALUE_FLAG:
            if index + 1 >= len(argv):
                return token
            index += 2
        elif not token.startswith("-"):
            index += 1
        else:
            return token
    return None


def _refuse_unlisted_option(label: str, noun: str, argv: list[str]) -> int | None:
    """The refusal of anything off the allowlist, or ``None`` for a permitted line.

    One line naming the token as the caller typed it and pointing at the tool
    that does take the option, so the caller is not left guessing which flags a
    wrapper happens to know. The census is never reached by this path: a wrapper
    that forwarded what it could not classify was the false clean the allowlist
    exists to close.
    """
    token = _first_refused_option(argv)
    if token is None:
        return None
    if token == _VALUE_FLAG:
        # The one refused token that is a real option: it was typed, it just
        # stands at the end of the line with nothing to take as its value.
        return _refuse(label, noun, f"{_VALUE_FLAG} needs a value")
    return _refuse(label, noun, f"{token} is not a {label} option: run "
                                f"`noni census` for filters and other options")


def run(label: str, noun: str, argv: list[str] | None,
        checks: frozenset[str]) -> int:
    """One entry point's whole run: check the shape, then hand the census its argv.

    ``--help`` as the whole command line is the package's own text (see
    ``shim_help``). Anything else has to be exactly one directory that exists and
    is a directory, plus whatever options the allowlist admits. Each refusal is
    the census's usage code and names the path or token the caller gave: a census
    of nothing -- or of a tree the caller pointed at through a flag the wrapper
    does not take -- would print a verdict nobody asked for, and whoever scripts
    the run reads an exit 0 as a clean census.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 1 and argv[0] in _HELP_TOKENS:
        from . import shim_help

        return shim_help.print_help(label)
    unlisted = _refuse_unlisted_option(label, noun, argv)
    if unlisted is not None:
        return unlisted
    positional = _positionals(argv)
    # An empty argument is a positional argparse would hand on, and ``Path("")``
    # is the cwd: a caller who left the directory empty in a script would have its
    # census run over whatever `noni/decisions` sat beside, and read the verdict as
    # the one they asked for. Refused with the other no-directory answer.
    if not positional or positional[0] == "":
        return _refuse(label, noun, f"no {noun} directory given")
    if len(positional) > 1:
        listed = " ".join(positional)
        return _refuse(label, noun, f"one directory at most, got {len(positional)}: {listed}")
    target = Path(positional[0])
    if target.is_symlink():
        # `is_dir` follows links, and ``--repo`` is built from the resolved path
        # while the state flag keeps the spelling the caller typed: a link would
        # census a directory the caller named only through it.
        return _refuse(label, noun, f"the {noun} path {positional[0]} "
                                    f"is a symlink: the census does not read "
                                    f"through links")
    if not target.is_dir():
        reason = "is not a directory" if target.exists() else "does not exist"
        return _refuse(label, noun, f"the {noun} path {positional[0]} {reason}")
    # ``is_symlink`` above sees only the last component: a link standing where a
    # parent should be (``link/noni/decisions`` with ``link`` a symlink) passes
    # every check so far, and ``argv_for`` would then build ``--repo`` from the
    # resolved path while the state flag keeps the caller's spelling -- the same
    # split verdict a link at the leaf gave, reached one level up.
    if target.resolve() != Path(os.path.abspath(positional[0])):
        return _refuse(label, noun, f"a component of {positional[0]} is a "
                                    f"symlink: the census does not read "
                                    f"through links")
    return main(argv_for(positional[0], _allowed_options(argv), checks))


def _allowed_options(argv: list[str]) -> list[str]:
    """The caller's permitted options, in the order they were typed.

    Every token here has already been admitted by :func:`_first_refused_option`,
    which is what makes this a filter rather than a second classifier: it keeps
    what the check accepted and adds nothing, so the census sees the bytes the
    caller typed and no token the wrapper invented.
    """
    kept: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _ALLOWED_SWITCHES or token.startswith(_VALUE_FLAG_PREFIX):
            kept.append(token)
            index += 1
        elif token == _VALUE_FLAG:
            kept += [token, argv[index + 1]]
            index += 2
        else:
            index += 1
    return kept


def run_entry(label: str, argv: list[str] | None = None) -> int:
    """The run of one named entry point, its group and noun from one table.

    The thin wrapper under ``skills/`` calls this rather than naming a group of
    its own, so the class set a wrapper runs is decided here and nowhere else.
    A label the table does not name is a bug in the caller, not input to accept:
    it raises rather than quietly running the census over every group.
    """
    if label not in _ENTRY_POINTS:
        raise KeyError(f"no census entry point is named {label!r}")
    noun, checks = _ENTRY_POINTS[label]
    return run(label, noun, argv, checks)


def run_ledger(argv: list[str] | None = None) -> int:
    """The steering-ledger entry point: the unified census over one named ledger."""
    return run_entry("census.sh", argv)


def run_sessions(argv: list[str] | None = None) -> int:
    """The sessions entry point: the unified census over one named register."""
    return run_entry("census-sessions.sh", argv)
