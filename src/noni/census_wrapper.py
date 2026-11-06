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

The one-directory rule is enforced here, in the census's own usage code: the
wrappers take the directory positionally, which the unified census has no flag
for, and one run audits one directory. Every other argument is passed through
untouched, so ``--json``, ``--strict``, ``--now`` and the rest stay the census's
flags with the census's refusals — this module re-implements none of them.

Nothing here opens a path, evaluates a class, or invents an exit code.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .census import LEDGER_CHECKS, SESSION_CHECKS, main
from .census_report import CLASS_CODE, EXIT_USAGE

# The label each entry point prints, and the group it runs. One table, so the
# wrapper under ``skills/`` and a test in process cannot disagree about which
# group a name belongs to.
ENTRY_POINTS: dict[str, frozenset[str]] = {
    "census.sh": LEDGER_CHECKS,
    "census-sessions.sh": SESSION_CHECKS,
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


def run(label: str, argv: list[str] | None, checks: frozenset[str]) -> int:
    """One entry point's whole run: check the shape, then hand the census its argv.

    ``--help`` is the package's own text (see ``shim_help``). Anything else has to
    be exactly one directory plus whatever census options the caller named; a run
    that named none or two is the census's usage error, naming the label the
    caller typed and the shape they should have typed.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 1 and argv[0] in ("--help", "-h"):
        from . import shim_help

        return shim_help.print_help(label)
    positional = [a for a in argv if not a.startswith("-")]
    if len(positional) != 1:
        print(f"{label}: one directory at most (got {len(positional)}); usage: "
              f"{label} [--help] [census options] <dir>", file=sys.stderr)
        return EXIT_USAGE
    return main(argv_for(positional[0],
                         [a for a in argv if a.startswith("-")], checks))


def run_entry(label: str, argv: list[str] | None = None) -> int:
    """The run of one named entry point, its group taken from ``ENTRY_POINTS``.

    The thin wrapper under ``skills/`` calls this rather than naming a group of
    its own, so the class set a wrapper runs is decided here and nowhere else.
    A label the table does not name is a bug in the caller, not input to accept:
    it raises rather than quietly running the census over every group.
    """
    if label not in ENTRY_POINTS:
        raise KeyError(f"no census entry point is named {label!r}")
    return run(label, argv, ENTRY_POINTS[label])


def run_ledger(argv: list[str] | None = None) -> int:
    """The steering-ledger entry point: the unified census over one named ledger."""
    return run_entry("census.sh", argv)


def run_sessions(argv: list[str] | None = None) -> int:
    """The sessions entry point: the unified census over one named register."""
    return run_entry("census-sessions.sh", argv)
