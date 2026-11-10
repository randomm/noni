"""Doubles for the seams the census reads.

``_UnreadableGit`` stands in for a Git object whose history read failed, which is how
a test reaches the cannot-tell paths without a fixture repo that is broken in some
other way. Copied verbatim from ``tests/test_census_unified.py``.

``_RecordedCensusCall`` stands in for the census behind the ledger wrapper, which
is how a test pins what the wrapper hands over without running a census over a
fixture tree it did not name.
"""

from __future__ import annotations


class _UnreadableGit:
    """A stand-in for a Git object whose history read failed.

    The real object leaves ``available`` False when ``rev-parse``/``log`` or
    ``git log`` cannot answer, so the test drives the shape git actually
    presents rather than one no real run reaches."""

    top = None
    available = False


class _RecordedCensusCall:
    """A census that records the argv it was handed and reports nothing.

    The wrapper's contract is the call it makes, not the verdict it prints: this
    double keeps the ledger it was given and the options it forwarded, and returns
    the census's own clean code so a refusal cannot pass as a pass-through."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, argv: list[str]) -> int:
        # The wrapper builds ["--repo", <parent>, "--ledger", <target>,
        # (--only <class>)…, <caller's options>]. The target is the argument the
        # caller spelled and the tail is what they named, in the order they named
        # it; both are what a caller of run_ledger is owed. The group's own
        # --only pairs are the wrapper's doing, so they are stripped here rather
        # than asserted here -- which classes a wrapper runs is the check
        # contract's business, pinned in test_census_check_contract.py.
        target = argv[argv.index("--ledger") + 1]
        rest = argv[argv.index("--only"):] if "--only" in argv else []
        while rest[:1] == ["--only"] and len(rest) > 1:
            rest = rest[2:]
        self.calls.append((target, list(rest)))
        return 0
