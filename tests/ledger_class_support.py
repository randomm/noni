"""The readers that parse the shipped ``line_free`` apart, shared by its tests.

``line_free`` is one predicate carrying two rules -- the blank class and the
line-break class -- and the parity tests compare each against the Python set it
mirrors. Doing that needs the class text pulled out of the shipped program and
then decoded, so the comparison is against what the class *names* rather than
what its characters look like: the reading this replaced scanned the class text,
matched only the ``\\n`` and ``\\r`` that happen to sit in it, and passed against
a set it never compared. Both steps are held here, in a module pytest does not
collect, so the class-parity tests and the doc-wording test can read the shipped
bytes through one pair of eyes rather than two copies that can drift.

``_comment_above`` belongs with them for the same reason: the wording that names
a set's basis is as easy to write wrong as the set, and the way to check it is to
read it off the file that carries it.
"""

from __future__ import annotations

import json
import re


def _decode_jq_class(class_text: str) -> set[str]:
    """The characters a jq bracketed class names, decoded from its two-character escapes.

    Takes the text rather than the file so a caller can hand it a mutated copy: a
    decoder that ignored the ``\\uXXXX`` forms would still answer the two breaks the
    class spells with a backslash letter, and pass against a set it never compared.
    jq's string escapes are json's, so json is the decoder -- no table of ours to
    drift from the syntax the shipped program uses. A stray character is refused
    rather than joined in: LF and CR entered the old assertion that way, from the
    class text rather than from what the class names.
    """
    # The blank class is anchored, the line class is not, so the anchors belong to
    # the text and not to what the class names: they are taken off the ends here and
    # refused anywhere else, so a class that named a caret fails loudly rather than
    # being quietly stripped of it.
    core = class_text.lstrip("^").rstrip("$*")
    assert core.startswith("[") and core.endswith("]"), (
        f"not a bracketed class: {class_text!r}")
    body = core[1:-1]
    assert "^" not in body and "$" not in body, (
        f"an anchor sits inside the class: {class_text!r}")
    # The file writes every member as two characters, a backslash and a letter, and
    # the blank class carries a doubled lead for the members json would otherwise
    # read as an escaped backslash. Halving the pairs puts the text in the form json
    # -- and jq, whose string escapes are json's -- actually parses.
    body = body.replace("\\\\", "\\")
    try:
        decoded = json.loads(f'"{body}"')
    except json.JSONDecodeError as err:
        msg = f"class is not a decodable json string: {class_text!r} ({err})"
        raise AssertionError(msg) from err
    assert "\\" not in decoded, f"an escape survived decoding: {decoded!r}"
    named = set(decoded)
    assert len(named) == len(decoded), (
        f"the class names one character twice: {class_text!r} -> {decoded!r}")
    return named


def _line_free_classes(text: str) -> tuple[str, str]:
    """The blank class and the line-break class of ``line_free``, in that order.

    Each class is read with one regex, as the body of a ``test()`` string. The
    pattern's own classes are written with escapes, so a backslash in the shipped
    text stays a member instead of ending the match: a scan that walked the text
    two characters at a time dropped the blank class that way, leaving the parity
    assertion to compare one class against ten breaks.
    """
    definition = re.search(r"def line_free:.*?\)\);", text, re.S)
    assert definition, "line_free no longer holds the two test() forms to parse"
    classes = re.findall(r"test[(]\"([^\"]*)\"", definition.group(0))
    # The blank class is anchored -- "^[ ... ]*$" -- so its trailing "]" is not the
    # last character, and a test for the brackets at the two ends would drop it and
    # leave one class to compare against the ten breaks.
    def _bracketed(candidate: str) -> bool:
        core = candidate.lstrip("^").rstrip("$*")
        return core.startswith("[") and core.endswith("]")

    bracketed = [c for c in classes if _bracketed(c)]
    assert len(bracketed) == 2, (
        f"expected the blank class and the line class, got {classes}")
    return bracketed[0], bracketed[1]


def _comment_above(text: str, anchor: str) -> str:
    """The contiguous ``#`` comment block sitting directly above ``anchor``.

    Read from the shipped file rather than retyped by a caller: a copy of the
    wording in a test module would drift alongside the wording it is meant to
    catch. The block is the lines above the anchor that start with ``#``, walked
    back to the first line that does not, so a comment that stopped naming what it
    refuses is caught whether it grew or shrank around the assertion.
    """
    lines = text.splitlines()
    position = _index_of_anchor_line(lines, anchor)
    start = position
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    block = "\n".join(lines[start:position])
    assert block, f"no comment sits above {anchor!r}"
    return block


def _names_strip_as_basis(line: str) -> bool:
    """Whether one comment line states ``str.strip`` as what the blank set *is*.

    A line may name ``str.strip`` to say what the set is *not* -- the wider basis
    the old wording wrongly claimed -- and that negation is the sentence that keeps
    the next reader from restoring it. Only an assertion that the set *is* what
    ``str.strip`` removes names the wrong basis; that is the ``is`` + ``removes``
    shape the two old comments both used.
    """
    text = line.lower()
    return ("str.strip" in text and "removes" in text and " is " in text)


def _index_of_anchor_line(lines: list[str], anchor: str) -> int:
    """The line number of ``anchor``, which must open a line of the file.

    A helper rather than a ``for``/``else`` in the caller: an enumerate loop that
    reads its counter only after the loop trips ruff's unused-variable rule, and a
    helper that returns the index makes the "must be present" refusal a single
    assertion at the one place that knows the anchor's shape.
    """
    found = [i for i, line in enumerate(lines) if line.startswith(anchor)]
    assert found, f"{anchor!r} is no longer at the start of a line"
    return found[0]
