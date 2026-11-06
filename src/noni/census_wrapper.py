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

The one-directory rule, and the refusal of a register that is not there, are
enforced here, before the census is called. Both belong to the wrapper because
the census cannot see them: the unified census takes its state paths as flags and
audits the tree ``--repo`` names, so an unnamed directory, a second directory, or
a path that is not a directory at all is invisible to a run over the tree that
contains it -- and a census that reads nothing has no verdict to give. Everything
every other argument is passed through untouched, so ``--json``, ``--strict``,
``--now`` and the rest stay the census's flags with the census's refusals -- this
module re-implements none of them.

Nothing here opens a path, evaluates a class, or invents an exit code. The three
refusals below return the census's usage code and name the path they refused, in
the census's own style.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .census import LEDGER_CHECKS, SESSION_CHECKS, main
from .census_report import CLASS_CODE, EXIT_USAGE

# The noun each entry point's directory is called, in the usage line and in its
# refusals: the word a reader has to match against the tree they are standing in.
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
    whose parent reliably means the directory above it.
    """
    resolved = Path(target).resolve()
    return ["--repo", str(resolved.parent), "--" + _GROUP_FLAG[checks], target,
            *_only(checks), *options]


def _refuse(label: str, noun: str, detail: str) -> int:
    """One usage refusal, in the census's style, returning the census's code.

    The line names the entry point the caller typed, the fault, and the path they
    named -- the three things a reader needs to fix a command line -- and the code
    is ``EXIT_USAGE``, the code the census's own argparse refusals carry.
    """
    print(f"{label}: error: {detail} (usage: {label} [--help] [census options] "
          f"<state-root>/noni/{noun})", file=sys.stderr)
    return EXIT_USAGE


def run(label: str, noun: str, argv: list[str] | None,
        checks: frozenset[str]) -> int:
    """One entry point's whole run: check the shape, then hand the census its argv.

    ``--help`` is the package's own text (see ``shim_help``). Anything else has to
    be exactly one directory that exists and is a directory, plus whatever census
    options the caller named. Each refusal is the census's usage code and names the
    path the caller gave: a census of nothing -- or of one of two registers --
    would print a verdict the caller never pointed at, and whoever scripts the run
    reads an exit 0 as a clean census.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 1 and argv[0] in ("--help", "-h"):
        from . import shim_help

        return shim_help.print_help(label)
    positional = [a for a in argv if not a.startswith("-")]
    if not positional:
        return _refuse(label, noun, f"no {noun} directory given")
    if len(positional) > 1:
        listed = " ".join(positional)
        return _refuse(label, noun, f"one directory at most, got {len(positional)}: {listed}")
    target = Path(positional[0])
    if not target.is_dir():
        reason = "is not a directory" if target.exists() else "does not exist"
        return _refuse(label, noun, f"the {noun} path {positional[0]} {reason}")
    return main(argv_for(positional[0],
                         [a for a in argv if a.startswith("-")], checks))
    return main(argv_for(positional[0],
                         [a for a in argv if a.startswith("-")], checks))


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


# The label each entry point runs under, exported for the tests that compare the
# two forms of one entry point without restating the table above.
ENTRY_POINTS: dict[str, frozenset[str]] = {
    label: checks for label, (_noun, checks) in _ENTRY_POINTS.items()
}


def run_ledger(argv: list[str] | None = None) -> int:
    """The steering-ledger entry point: the unified census over one named ledger."""
    return run_entry("census.sh", argv)


def run_sessions(argv: list[str] | None = None) -> int:
    """The sessions entry point: the unified census over one named register."""
    return run_entry("census-sessions.sh", argv)
