"""The two input guards ``item.py`` runs before it reads or writes anything.

Mechanics, not the writer's contract. Each guard answers one question about a value the
operator passed and hands the writer a ready-made refusal (its code, headline and hint)
or None: whether the ``--repo`` this run was given is a path the writer may read and
write through at all, and whether a free-text flag still is the one bounded line it
names. Both are asked before any read, so a run refused here has touched nothing.

Both are shared rules rather than this writer's inventions: the path walk and its
wording are :func:`noni._path_kind.refuse_state_root`'s and the one-line predicate is
the ledger's, so an item's title and a decision record's name field are held to one
rule and refuse with one sentence.
"""

from __future__ import annotations

from pathlib import Path

from . import _path_kind, ledger_schema


def linked_state(repo: Path, verb: str, guarded: tuple[str, ...], report,
                 exit_usage: int) -> int | None:
    """The exit-2 refusal for a ``--repo`` this writer may not read or write, or None.

    One seam for both ``noni/`` questions of :data:`_GUARDED_DIRS`, in the order and
    with the wording :func:`noni._path_kind.refuse_state_root` owns. Only ``add`` is
    admitted to the state-root question: it is this writer's one sanctioned creator,
    while ``list``, ``drop`` and ``promote`` create nothing legitimate and are refused
    ahead of the reads that would otherwise answer "no such item". ``exit_usage`` is
    the code docs/PRODUCT.md 7 gives ``item`` for a wrong path; the guard runs before
    the artifact read, the ledger lookup and every mkdir.
    """
    refused = _path_kind.refuse_state_root(repo, verb == "add", guarded)
    return None if refused is None else report(exit_usage, *refused)


def bad_text(flag: str, value: str, limit: int, what: str, report,
             exit_usage: int) -> int | None:
    """The exit-2 refusal for a flag whose value is not one bounded line, or None.

    Blank, multi-line and over-long are the three ways a free-text flag stops being
    the one line it names, and all three are refused at the flag rather than at the
    file: a value carrying a newline into the artifact would put a second line into a
    listing, and one past the bound would put an unbounded row into the census. The
    predicate is the ledger's, so one rule holds a decision record's name field and
    an item's title.
    """
    if not ledger_schema.is_single_line(value):
        return report(exit_usage, f"{flag} {value!r} is not a non-blank single line",
                      f"{what} is one line of text: pass it without a newline and "
                      "with something in it")
    if len(value) > limit:
        return report(exit_usage, f"{flag} is {len(value)} characters, past the "
                      f"{limit} limit", f"shorten {flag} to at most {limit} characters")
    return None
