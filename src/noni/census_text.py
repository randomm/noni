"""The census's message scrub: path stripping, clipping, and the two composed.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the text rules a row's message passes
through. It is imported by the package (``from . import census_text``), never by
path, so inside an installed wheel there is no sibling file to load and no
directory a lookalike could be found on.

Three rules, one standard — a row built from someone else's words must not
smuggle a machine path into a report that promises not to print one, and must
stay short enough to read:

- :func:`_stripped` — collapse whitespace runs and replace host paths.
- :func:`_clipped` — cut to a length, with an ellipsis when it was cut.
- :func:`_bounded` — both halves, for text that came from outside.

The names are the ones ``census.py`` re-exports and the group call sites pass as
arguments, so a helper is never redefined by whichever module needs it.
"""

from __future__ import annotations

import re


def _bounded(message: str, limit: int = 300) -> str:
    """Bound an exception-derived message and strip machine-local absolute
    paths from it: a row built from someone else's error text must not smuggle
    a host path into a report that promises not to print one.

    The scrubbing is what makes this the right wrapper for a foreign message, and
    the wrong one for a sentence this census composed itself: a row that names the
    ledger as ``noni/decisions`` is naming a root-relative path on purpose, and a
    wrapper that shortened it to ``<path>`` would destroy the very thing the row
    is telling the operator to look at. So the two halves are separate here and
    the group hands each one what it needs: this for text that came from outside,
    :func:`_clipped` for the finished sentence around it.
    """
    return _clipped(_stripped(message), limit)


def _stripped(message: str) -> str:
    """``message`` with runs of whitespace collapsed and host paths replaced.

    The path-stripping half of :func:`_bounded`, alone: a caller that composed a
    sentence out of root-relative paths it derived itself needs the collapsing and
    nothing else.

    The rule is about a machine-local path: one written from the root (``/…``) or
    from a home directory (``~/…``, ``~someone/…``). The anchor is what makes it
    that rule and not a hunt for the first ``/`` anywhere. Unanchored it ate the
    middle of a root-relative path, so a scrubbed ``noni/decisions`` came out as
    ``noni<path>`` — neither the path nor a usable stand-in — and it ate
    ``input/output`` out of an ``OSError`` whose text the row exists to carry.
    Both are the finding the row states, so neither may be touched: the separator
    must open the path, following only the start of the string or a character that
    cannot itself continue a path (a delimiter, a quote, a bracket, ``=``), never a
    word character or a ``.``.

    That anchor is a character test and not a list of punctuation, which is what
    covers the absolute paths a two-run floor would miss: a host path can be
    shorter than two components, and ``PermissionError`` appends the filename it
    failed on in quotes, so ``denied: '/home/dev/x'`` is absolute with its only
    separator behind a quote.
    """
    collapsed = " ".join(message.split())
    return re.sub(r"(?:(?<=^)|(?<=[^\w./~$-]))(?:/[A-Za-z0-9._-]+){2,}"
                  r"|~[A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)+",
                  "<path>", collapsed)


def _clipped(message: str, limit: int = 300) -> str:
    """``message`` cut to ``limit`` characters, with an ellipsis when it was cut.

    The length half of :func:`_bounded`, alone: the bound a row keeps is a property
    of the row, so it is applied to the finished sentence a reporter composed,
    whose own path fragments must survive (see :func:`_bounded`).
    """
    return message if len(message) <= limit else message[: limit - 3] + "..."
