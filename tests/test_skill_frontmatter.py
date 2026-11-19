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
unwrapped ``description:`` line, never a folded or literal block. The wording
the quoting preserves is guarded by review of the two-character diff, not here.
"""

from __future__ import annotations

import re
from pathlib import Path

from _harness import REPO

FIELD = re.compile(r"^([a-z-]+):(.*)$")
REQUIRED_FIELDS = ("name", "description")


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

    An empty value is out of scope: ruling 1 names only the colon and quote
    rules, and a page whose block carries no field at all is already reported by
    ``page_defects``.
    """
    body = value[1:] if value.startswith(" ") else value
    marker = body[:1]
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

    Field presence is checked here and value shape by ``value_defect``, so there
    is one rule per shape and no second place to update.
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


def test_the_guard_refuses_a_planted_page_whose_value_is_unquoted() -> None:
    """The gate fires, rather than finding nothing to fire on.

    Driven directly over planted text (no monkeypatch, no shared reader), so a
    green run above means the rule rejected something and is not the absence of
    a match. Each planted shape is one of the three rules the ticket names, and
    the first is the real defect: this page's own wording, left unquoted.
    """
    planted = {
        '---\nname: demo\ndescription: a fresh agent in an attached project: '
            "one read-only screen of the operator's decisions\n---\n":
            'an unquoted value contains ": "',
        '---\nname: demo\ndescription: a value ending in a colon:\n---\n':
            "ends in a colon",
        '---\nname: demo\ndescription: "unterminated\n---\n': "does not close",
        '---\nname: demo\ndescription: " a value with text and no close\n---\n':
            "does not close",
        '---\nname: demo\ndescription: "holds \\"a quote\\""\n---\n':
            'holds an unescaped',
        '---\nname: demo\ndescription: "holds a \\\\backslash"\n---\n':
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
