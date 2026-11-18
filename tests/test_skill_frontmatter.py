"""Every shipped SKILL.md frontmatter value reads as one string, not a mapping.

Pi's skill loader parses the block between the first two ``---`` fences with a
strict YAML parser, and an unquoted value that carries ": " is read as a nested
mapping. That is how skills/noni/SKILL.md broke on every start: its description
holds "an attached project: one read-only screen", and the loader reported
"Nested mappings are not allowed in compact mappings".

No gate caught it because no gate looked. ``test_start_here_page_docs.py``
matches the block with ``^([a-z-]+):(.*)$`` and hands the value back verbatim,
which matches the broken line happily; ``test_skill_scrub.py`` walks the same
pages for secrets and length only. This module is the check the bug needed.

Parser-free by design (issue #200). No YAML parser is a dev dependency,
pyproject.toml is a gate file, and ``test_gate_wiring.py`` pins CI against the
dev extra, so a guarded ``import yaml`` would report zero assertions on the venv
that has to catch this. The rules below are the subset of YAML's plain-scalar
rule this repo's frontmatter actually uses: each page is one ``name:`` and one
unwrapped ``description:`` line, never a folded or literal block.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from _harness import REPO

FIELD = re.compile(r"^([a-z-]+):(.*)$")
REQUIRED_FIELDS = ("name", "description")
# The commit whose skills/noni/SKILL.md first carries the wording this ticket's
# quoting must preserve: the page landed there intact and was untouched until
# this ticket, so the wording check has a committed reference, not a literal.
PRE_FIX_REV = "60838c6"


def skill_pages() -> list[Path]:
    """Every shipped skill page, so a fifth skill is covered the day it lands."""
    return sorted((REPO / "skills").glob("*/SKILL.md"))


def frontmatter_fields(text: str) -> dict[str, str]:
    """The ``{field: raw value}`` block between the first two ``---`` fences.

    The raw value is returned with its leading space and any quotes intact: the
    caller judges the shape, so stripping here would hide exactly what is checked.
    """
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("the page has no frontmatter opener")
    end = next((n for n in range(1, len(lines)) if lines[n] == "---"), None)
    if end is None:
        raise AssertionError("the page's frontmatter is never closed")
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = FIELD.match(line)
        if match is None:
            raise AssertionError(f"frontmatter line is not a field: {line!r}")
        fields[match.group(1)] = match.group(2)
    return fields


def value_defect(value: str) -> str | None:
    """Why this raw frontmatter value would not load as one string, or None.

    Three shapes, each one YAML's plain-scalar rule rather than a style opinion:

    - A bare (unquoted) value holding ": " splits into a nested mapping. A bare
      colon alone does not, so the sequence is colon-space, and a value ending
      in a bare colon hangs the scan on the next line.
    - A double-quoted value must close, and its interior may hold neither ``"``
      nor ``\\``: PyYAML raises on the first and eats the escape in the second,
      so the parsed text silently differs from the source line.
    - A single-quoted value must close, and ``''`` is the only inner quote it
      may hold; one lone ``'`` ends the scalar early.

    A quote character is checked inside the quotes only where one can be told
    apart from content: a lone ``"`` or ``'`` closes nothing, so it is reported
    as the empty value it loads to rather than as an unclosed scalar.
    """
    body = value[1:] if value.startswith(" ") else value
    marker = body[:1]
    if not body.strip(' "\''):
        # Covers the bare empty value, "" and '' (and a lone quote, which is no
        # pair): an empty quoted scalar is what YAML hands back as None, so the
        # field a loader needs is gone.
        return "the value is empty, so the field a loader needs would be missing"
    if marker in ("'", '"'):
        if len(body) < 2 or not body.endswith(marker):
            named = {"'": "single", '"': "double"}[marker]
            return f"a {named}-quoted value does not close"
        inner = body[1:-1]
        if marker == '"' and ('"' in inner or "\\" in inner):
            return 'a double-quoted value holds an unescaped " or backslash'
        if marker == "'" and "'" in inner.replace("''", ""):
            return "a single-quoted value holds a quote that '' does not escape"
        return None
    if ": " in body:
        return 'an unquoted value contains ": ", which loads as a nested mapping'
    if body.endswith(":"):
        return "an unquoted value ends in a colon, which breaks the scan"
    return None


def page_defects(page: Path) -> list[str]:
    """Every reason this page's frontmatter would not load as string values.

    The two field-presence and field-emptiness checks are delegated to
    ``value_defect`` by the loop at the bottom, so there is one rule per shape
    and no second place to update.
    """
    try:
        fields = frontmatter_fields(page.read_text(encoding="utf-8"))
    except AssertionError as exc:
        return [str(exc)]
    except OSError as exc:
        # A page the listing named but the tree cannot offer is a failure to
        # report, not a crash and not a skip: same shape as the size gate.
        return [f"unreadable: {type(exc).__name__}"]
    defects = [] if fields else ["the frontmatter block holds no field at all"]
    defects += [f"the frontmatter has no {name!r} field"
                for name in REQUIRED_FIELDS if name not in fields]
    for name, raw in fields.items():
        defect = value_defect(raw)
        if defect is not None:
            defects.append(f"{name}: {defect}")
    return defects


def test_every_shipped_skill_page_has_the_frontmatter_a_loader_reads() -> None:
    """Each page's block yields name and description, each reading as one string.

    The listing is asserted non-empty first: a gate that globbed nothing would
    find no defects and pass green while measuring nothing.
    """
    pages = skill_pages()
    assert pages, f"no SKILL.md found under {REPO / 'skills'}; the gate measures nothing"
    reports = [f"{page}: {'; '.join(page_defects(page))}"
               for page in pages if page_defects(page)]
    assert not reports, "these skill pages would not load as string frontmatter:\n" + \
        "\n".join(f"  {line}" for line in reports)


def test_quoted_values_round_trip_to_their_own_text() -> None:
    """Quoting changed the line, not the wording it carries.

    Three halves. On every page: the raw value, unwrapped, re-quotes to the
    exact text it came from and carries no surrounding space, so a quote pair
    can neither eat nor gain a character. On the page this ticket changed: the
    working tree's description must equal what ``git`` holds at ``PRE_FIX_REV``,
    the commit whose page first carries that wording, so a rewording cannot hide
    inside a quoting change and the reference is committed text, not a literal
    that would rot. And the check itself is proved to fire: the same comparison
    over a reworded page must refuse it, because a wording check that compared
    the page to itself would pass forever.
    """
    def unwrapped(text: str) -> str:
        raw = frontmatter_fields(text)["description"]
        body = raw[1:] if raw.startswith(" ") else raw
        if body[:1] in ("'", '"'):
            return body[1:-1].replace("''", "'")
        return body

    def git_show(rev: str, path: str) -> str:
        proc = subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"],
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, f"git show {rev}:{path} failed: {proc.stderr}"
        return proc.stdout

    pages = skill_pages()
    for page in pages:
        for name, raw in frontmatter_fields(page.read_text(encoding="utf-8")).items():
            body = raw[1:] if raw.startswith(" ") else raw
            marker = body[:1] if body[:1] in ("'", '"') else ""
            text = body[1:-1] if marker else body
            if marker:
                # The unescape the loader does: '' stands for one apostrophe.
                text = text.replace("''", "'")
            assert text and text == text.strip(), (
                f"{page}: {name} carries no text or gained surrounding space")
            rejoined = f"{marker}{text}{marker}" if marker else text
            assert rejoined == body, f"{page}: {name} lost characters under quoting"

    noni = REPO / "skills" / "noni" / "SKILL.md"
    assert noni in pages, (
        f"{noni} is not in the gate's page listing, so the wording check below "
        "would compare a page the gate never measured")
    reference = unwrapped(git_show(PRE_FIX_REV, "skills/noni/SKILL.md"))
    assert unwrapped(noni.read_text(encoding="utf-8")) == reference, (
        f"skills/noni/SKILL.md's description is no longer the wording it carried "
        f"at {PRE_FIX_REV}: this ticket was allowed to add a quote pair, not to reword")
    # The proof that the comparison above is a real check: the same comparison
    # against planted wording refuses, so a green run is not the two sides being
    # the same string by construction.
    reworded = noni.read_text(encoding="utf-8").replace("read-only screen",
                                                         "read-only pane", 1)
    assert unwrapped(reworded) != reference, (
        "the wording comparison accepts a reworded description, so it checks nothing")


def test_the_guard_refuses_a_planted_page_whose_value_is_unquoted() -> None:
    """The gate fires, rather than finding nothing to fire on.

    Driven directly over planted text (no monkeypatch, no shared reader), so a
    green run above means the rule rejected something and is not the absence of
    a match. Each planted shape is the one the ticket names, plus the shapes the
    three rules exist for.
    """
    planted = {
        '---\nname: demo\ndescription: an attached project: one screen\n---\n':
            'an unquoted value contains ": "',
        '---\nname: demo\ndescription:\n---\n': "the value is empty",
        '---\nname: demo\ndescription: ""\n---\n': "the value is empty",
        "---\nname: demo\ndescription: ''\n---\n": "the value is empty",
        '---\nname: demo\ndescription: a value ending in a colon:\n---\n':
            "ends in a colon",
        '---\nname: demo\ndescription: "\n---\n': "the value is empty",
        '---\nname: demo\ndescription: "unterminated\n---\n': "does not close",
        '---\nname: demo\ndescription: " a value with text and no close\n---\n':
            "does not close",
        '---\nname: demo\ndescription: "holds \\"a quote\\""\n---\n':
            'holds an unescaped',
        "---\nname: demo\ndescription: 'holds 'a quote'\n---\n":
            "holds a quote that '' does not escape",
        "---\nname: demo\ndescription: it's fine\n---\n": None,
        "---\nname: demo\ndescription: a colon:without a space is a string\n---\n": None,
        '---\nname: demo\ndescription: "quoted: and fine"\n---\n': None,
        "---\nname: demo\ndescription: 'it''s quoted and fine'\n---\n": None,
    }
    for text, expected in planted.items():
        defect = value_defect(frontmatter_fields(text)["description"])
        if expected is None:
            assert defect is None, f"{text!r} was refused: {defect}"
        else:
            assert defect is not None and expected in defect, (
                f"{text!r} returned {defect!r}, expected a refusal naming {expected!r}")
