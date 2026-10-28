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

Those three are a *net*, not a guarantee: a regex can only guess at what a path
looks like, and every round of review has found another shape it missed (a bare
``~user``, a component outside the ASCII alphabet, a path whose only separator
sits behind an escaped quote). The guarantee lives one step earlier, in
:func:`fault_text`, which builds a row's fault wording from the structured
fields of an ``OSError`` so the filename part of the fault is never in the text
the row renders at all. A path the producer never wrote cannot be missed by a
scrubber.

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


# The rules of the scrub, compiled once. Each is named for the shape it answers,
# so the docstrings below can point at a rule instead of restating it.
#
# Two arms, kept apart because their anchors answer different questions. The
# tilde arm is ``\B``-anchored rather than given an explicit delimiter set:
# ``~user`` must scrub but ``a~b`` and ``v1.2~3`` must not, and ``\B`` is the
# test that says so without listing every character that may precede a home
# path. Its tail is the other half of the rule: the path ends at a separator or
# at a character that cannot continue one (``\B`` cannot answer that question at
# the end of the string, so ``$`` answers it there), which is what lets the bare
# ``~deploy`` of a service account scrub as well as ``~deploy/x`` does while
# ``a~b`` and ``v1.2~3`` stay untouched. The leading-separator arm keeps the
# explicit anchor, because there the character before the ``/`` is the whole
# question -- it must be the start of the string or something that cannot
# continue a path (a delimiter, a quote, a bracket, ``=``), never a word
# character or a ``.``.
#
# A quoted fragment is matched first, and whole (``[^']*``): that is what lets a
# path inside a quote hold a space, and what lets its opening separator sit
# behind the quote, where no delimiter set would have found it. An escaped quote
# (``\'``, the form a repr of a path carries) does not open a fragment.
_QUOTED = re.compile(r"(?<!\\)'[^']*'")
_HOME_PATH = re.compile(r"\B~[A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]*)*(?:/|(?=[^\w./~-])|$)")
# The absolute arm, with no floor on the number of components and no stop at the
# second separator: ``/home`` is one component and a path, and a rule that
# matched only ``/home`` of ``/home/dev/x`` left ``/dev/x`` standing beside the
# marker that replaced it. A space is not in the alphabet: outside a quote a
# space ends a word, and with it a path.
_LEADING_ABSOLUTE = re.compile(r"(?:(?<=^)|(?<=[^\w./~$-]))/[A-Za-z0-9._/-]+")
# A whole path as the text of a quoted fragment: an absolute path, or a home
# path whose tilde may name a user and must then hold at least one separator, or
# a bare tilde, which inside a fragment that quotes one path is the home
# directory the fragment holds. A component may hold an interior space — a
# directory name may — but may not open or end with one, and the separator is
# what makes the space part of a path rather than part of a sentence: ``/home``
# is one component and a path while ``my dir`` is two words and is not. Each arm
# is anchored at both ends so a fragment must read as a path from its first
# character to its last; a fragment with prose in it falls through to the inner
# arms, which scrub only the path inside the prose.
_PATH_COMPONENT = r"[A-Za-z0-9._-](?:[A-Za-z0-9._ -]*[A-Za-z0-9._-])?"
_QUOTED_PATH = re.compile(rf"/{_PATH_COMPONENT}(?:/[A-Za-z0-9._ -]+)*"
                          rf"|~[A-Za-z0-9._-]*(?:/{_PATH_COMPONENT})+|~")
# The inner arms, for a quoted fragment that did not read as one path: the same
# two, except that the fragment's alphabet is the quoted one, so the tilde's
# components may hold a space (``'~me/my dir/x'``) and the tilde may open with an
# empty first component (``'~/x'``). The absolute arm is unchanged: a fragment
# that is prose may hold ``input/output`` as prose, and prose does not span a
# space.
_INNER_HOME_PATH = re.compile(r"\B~[A-Za-z0-9._-]*(?:/[A-Za-z0-9._ -]+)+")
# The inner absolute arm: the outer one's anchor, plus the fragment's own start.
# A fragment's leading ``/`` has no character before it for the outer lookbehind
# to approve, so the start of the fragment is approved by hand here. The
# alphabet is the outer one — no space — because this arm answers a path that sit
# inside prose, and prose separates its words at a space.
_INNER_ABSOLUTE = re.compile(r"(?:(?<=^)|(?<=[^\w./~$-]))/[A-Za-z0-9._/-]+")


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
    cannot itself continue a path, never a word character or a ``.``.

    Three shapes the two-run floor missed, each a way the row used to print a
    host path while claiming not to:

    - A host path can be shorter than two components. ``/home``, ``/srv`` and the
      mount point of a bad device are what a fault names outright, and a floor of
      two runs left every one of them standing. The arm runs to the last
      character that can be part of the path, so it does not stop after the first
      separator and leave the rest of the path standing either.
    - A path inside quotes may hold a space, which is not a path character, so a
      run of components ends at the space and leaves the rest of the directory
      name — ``'/home/me/my dir/decisions'`` used to lose ``/home/me`` and keep
      ``dir/decisions``. Within quotes the space therefore continues the path, and
      the closing quote is where it ends.
    - ``PermissionError`` appends the filename it failed on in quotes, so
      ``denied: '/home/dev/x'`` is absolute with its only separator behind a
      quote. The quoted fragment is matched first and handed to
      :func:`_scrub_inner`, which is the only rule that knows a path may hold a
      space there and that the fragment's own start is an anchor.

    A tilde is a home directory wherever it opens a path, quoted or not. The
    quotes themselves stay: they are the message's punctuation, not part of the
    path, and the sentence around the fault is this run's own wording.
    """
    return _outer_scrub(" ".join(message.split()))


def _outer_scrub(text: str) -> str:
    """The scrub of unquoted text: quoted fragments first, then the two arms.

    Ordered so a quoted fragment is consumed whole before either arm sees the
    text — a path inside a quote is :func:`_scrub_inner`'s to answer, and only
    its alphabet admits a space.
    """
    text = _QUOTED.sub(_scrub_quoted, text)
    text = _HOME_PATH.sub("<path>", text)
    return _LEADING_ABSOLUTE.sub("<path>", text)


def _scrub_quoted(match: re.Match[str]) -> str:
    """The replacement for one quoted fragment: the quotes, and the scrubbed path.

    The quotes are passed to :func:`_scrub_inner` and put back around its answer
    rather than stripped and re-added, because the arms anchor a path on the
    character before it: inside a fragment stripped of its quotes the ``/`` that
    opened the path has nothing before it and is no longer an anchored separator.
    """
    return "'" + _scrub_inner(match.group(0)[1:-1]) + "'"


def _scrub_inner(text: str) -> str:
    """The scrub applied to what sits between a pair of quotes.

    A fragment that reads as one path (:data:`_QUOTED_PATH`) becomes the marker:
    within quotes a space is a directory character, not a word separator, so the
    whole fragment is the path the message quoted.

    A fragment that does not read as a path (``'the ledger'``, or a sentence that
    quotes a path in the middle) is scrubbed by the two inner arms instead, so
    ``'a b /home/x c'`` loses the path and keeps the prose around it: quoting a
    message does not make its sentences into paths.
    """
    if _QUOTED_PATH.fullmatch(text):
        return "<path>"
    text = _INNER_HOME_PATH.sub("<path>", text)
    return _INNER_ABSOLUTE.sub("<path>", text)


def fault_text(e: OSError) -> str:
    """The row text of a filesystem fault, built without its filename.

    ``OSError`` renders itself as the errno words *plus the path it failed on*
    (``[Errno 13] Permission denied: '/home/someone/my dir/x'``), and it keeps
    that path outright on ``e.filename`` and ``e.filename2``. A row that quotes
    ``str(e)`` therefore starts with a host path already in it and relies on a
    regex downstream to take it out — and the regex has lost every race it has
    been in, because the shapes a path can take are not enumerable. So the row
    is built from the structured fields instead: the exception's class and its
    ``strerror``, which are the half that says what failed.

    The row never needs the path. Every caller of this helper reports a fault on
    an artifact the census already names itself — the ledger group's row puts the
    root-relative ledger path in ``subject``, ``artifact`` and its own prose, and
    the ordering group's listing fault does the same — so the filename would add
    a machine-local location to a report that promises not to print one, and
    nothing else. The words the exception carries alongside it are a different
    matter: ``strerror`` says what failed, which is the finding the row exists to
    print, so it stays. ``str(e)`` mixes the two in one string, which is exactly
    why the string is not what is quoted here.

    An ``OSError`` raised from a plain message (``OSError("input/output error")``,
    which is what a test and what a hand-written raise produce) has no
    ``strerror`` and no filename: its message *is* the finding, so it is kept --
    ``str(e)`` of that shape is the message alone, with no path to carry. A
    fault that carries a filename and an errno pair keeps the words and loses the
    path: the two are different fields and only one of them is the location.
    Keeping the plain-message text is safe for the same reason the rest of this
    helper is -- there is no filename in it -- and it is what a caller that
    raised with its own sentence expects, whose words the row exists to print.
    """
    name = type(e).__name__
    strerror = getattr(e, "strerror", None)
    filename = getattr(e, "filename", None)
    filename2 = getattr(e, "filename2", None)
    if strerror:
        # The words are kept whether or not a filename came with them: a fault
        # that knows both is the common case, and the path is simply not quoted.
        return f"{name}: {strerror}"
    if filename is not None or filename2 is not None:
        # A fault with a path and no words: str(e) of this shape is the path.
        return name
    if getattr(e, "errno", None) is not None:
        # An errno with no words of its own: str(e) would be "[Errno 13] None".
        return name
    # A fault built from a plain message: str(e) is that message and nothing
    # else, and no filename field is set to contradict it.
    return f"{name}: {e}"


def _clipped(message: str, limit: int = 300) -> str:
    """``message`` cut to ``limit`` characters, with an ellipsis when it was cut.

    The length half of :func:`_bounded`, alone: the bound a row keeps is a property
    of the row, so it is applied to the finished sentence a reporter composed,
    whose own path fragments must survive (see :func:`_bounded`).
    """
    return message if len(message) <= limit else message[: limit - 3] + "..."
