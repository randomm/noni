"""The readers behind the order writer's document pins.

Split out of ``order_fixtures`` when that module passed the 500-line cap its own
size test enforces: the fixtures there are the writer's state (repos, seeds,
rival commits), and these are the two documents a test compares that state
against -- ``order.py``'s docstring and ``skills/direction/SKILL.md``. Both are
read from the shipped files rather than quoted, so a test that pins a sentence
holds the product's text and not a copy kept in a test file.

``order_fixtures`` keeps re-exporting this module's readers, so the order suite
imports its fixtures from one place; a test that wants only the readers imports
here.
"""

from __future__ import annotations

import ast
import re

from _harness import (
    ORDER,
    REPO,
    _script_ast,
)

SKILL_DIR = REPO / "skills" / "direction"


def _order_ast() -> ast.Module:
    return _script_ast(ORDER)


def _docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "order.py has no module docstring"
    return doc


def _module_exit_codes(tree: ast.Module) -> set[int]:
    """The codes the EXIT_* module constants hold, read from the source."""
    codes: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{target.id} is not an int"
                codes.add(value.value)
    assert codes, "order.py defines no EXIT_* constants"
    return codes


def _doc_block(doc: str, header: str) -> dict[int, str] | dict[str, str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise AssertionError(f"docstring has no {header!r} block") from None
    block: dict = {}
    current = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif isinstance(current, int):
            block[current] += " " + line.strip()
    assert block, f"the {header!r} block is empty"
    return block


def _skill_section(heading: str) -> str:
    """One section of ``skills/direction/SKILL.md``, from its heading to the next.

    A whole-file ``in`` check passes on any mention of a phrase, which is how a
    sentence that only quotes another writer's wording could stand in for the row
    that documents this behaviour. Reading the section bounds the check to the
    table row or paragraph that has to carry it.

    Whitespace is left as the page wrote it: callers that compare a sentence
    against a pinned phrase collapse it themselves, so a table row can still be
    read line by line.
    """
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == f"## {heading}")
    except StopIteration:
        raise AssertionError(f"SKILL.md has no {heading!r} section") from None
    body: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    section = "\n".join(body).strip()
    assert section, f"the {heading!r} section of SKILL.md is empty"
    return section


def _parser_flags(tree: ast.Module) -> set[str]:
    """The long options the parser declares, read from main()."""
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.startswith("--"):
                            flags.add(arg.value)
    assert flags, "no add_argument calls found in main()"
    return flags


def _doc_usage_flags(doc: str) -> set[str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Usage:")
    except StopIteration:
        raise AssertionError("docstring has no 'Usage:' block") from None
    flags: set[str] = set()
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, "the 'Usage:' block names no flags"
    return flags
