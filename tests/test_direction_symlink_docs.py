"""The symlinked-directory refusal is written down in every place that owes it.

docs/PRODUCT.md 7, the two skills, and each writer's own docstring are the operator's
only contract for what a symlinked ``noni/``, ``noni/direction/`` or
``noni/decisions/`` costs them: the code and the wording. Four copies exist and
nothing but the checks below compares them, which is how a page that dropped the
clause, or a writer that changed its code, would otherwise pass every suite.

Modelled on the direction symlink-docs pattern: the expected code is read off the
page rather than trusted from the writer's constant, and the prose is read for the
state and the code together. A clause is located by the two phrases ONLY it carries
-- the position the guard walks and the promise it makes -- and the code and the path
shapes are asserted INSIDE the text between them, so a page whose whole new clause
had been deleted still fails, and a code lifted from a neighbouring sentence is not
credited.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from _harness import DECIDE, INTENT, ORDER, REPO, _script_ast

PRODUCT = REPO / "docs" / "PRODUCT.md"
DIRECTION_SKILL_MD = REPO / "skills" / "direction" / "SKILL.md"
STEERING_SKILL_MD = REPO / "skills" / "steering-ledger" / "SKILL.md"

# What the prose owes for this one state, per writer: the code docs/PRODUCT.md 7
# gives a wrong path, and the directories that writer's guard walks. The tuple is the
# prose transcribed -- a change on either side breaks the test that reads it.
WRITER_CODES = (("order", 2, ("noni/direction", "noni/decisions")),
                ("intent", 2, ("noni/direction", "noni/decisions")),
                ("decide", 3, ("noni/decisions",)))

# The clause's two halves: the position the guard walks, and the promise a link is
# never followed. Together they are the clause, and neither phrase occurs in any other
# clause on these pages -- not in the older ``--repo``-is-a-symlink half, not in the
# state-root refusal, not in the session writers' own clause (which names the session
# file and says "this writer may follow"). A page that dropped the clause matches
# neither, and a locator cannot be satisfied by neighbouring prose.
CLAUSE_START = "from the state root down to"
CLAUSE_CLOSE = "may read or write through"

# The kinds the clause names, checked inside the window that owns the clause. A
# clause that only ever said "symlink" would send an operator hunting for a link
# where a socket or a plain file stands, so the non-link kinds are owed too.
KINDS = ("symlink", "plain file", "socket", "device")


def _flat(text: str) -> str:
    """``text`` with every run of whitespace collapsed: a clause can wrap anywhere."""
    return " ".join(text.split()).lower()


def _section(text: str, heading: str) -> str:
    """The body of one ``## `` heading, up to the next one."""
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _product_section_7() -> str:
    """docs/PRODUCT.md section 7, read from the page rather than restated here."""
    return _section(PRODUCT.read_text(encoding="utf-8"),
                    "## 7. State layout and the state root")


def _docstring(script: Path, origin: str) -> str:
    doc = ast.get_docstring(_script_ast(script))
    assert isinstance(doc, str), f"{origin} has no module docstring"
    return doc


def _clause(text: str, origin: str, *, delimiter: str = ";",
            code: str | None = None, kinds: tuple[str, ...] = KINDS,
            code_before_only: bool = False) -> str:
    """The one span of ``text`` that IS the direction-directory clause, verified.

    The clause is located by :data:`CLAUSE_START` and :data:`CLAUSE_CLOSE`, both of
    which only it carries on these pages. The window the ``kinds`` and ``code`` are
    asserted over is the delimited unit that SURROUNDS the clause: bounded on the
    left by the last delimiter before the earlier half and on the right by the first
    delimiter after the later one, so a code lifted from a neighbouring row or
    sentence is not credited. The two halves are located independently rather than
    required in one order, because on these pages the walked position comes first and
    the promise second ("... that is not a directory this writer may read or write
    through (a symlink, ... every directory from the state root down to it ...") and
    a locator that demanded one order would report a correct page as a dropped clause.

    ``delimiter`` separates one clause from the next (``;`` in prose, ``|`` between
    the cells of a markdown row). A table states its code in the cell to the LEFT of
    the clause, so a table caller passes ``code_before_only`` and the code is asserted
    over that cell alone -- which for a table row is everything between the row's
    opening pipe and the pipe that opens the meaning cell.
    """
    flat = _flat(text)
    at = flat.find(CLAUSE_START)
    stop = flat.find(CLAUSE_CLOSE)
    assert at != -1, (
        f"{origin} no longer states the walked position ({CLAUSE_START!r}): the "
        f"direction-directory clause has been dropped from this page")
    assert stop != -1, (
        f"{origin} states the walked position ({CLAUSE_START!r}) but not the promise "
        f"({CLAUSE_CLOSE!r}): the clause is incomplete")
    first, second = sorted((at, stop))
    # The window is the delimited unit that SURROUNDS the clause. Its left bound is
    # the delimiter that opens that unit, which differs between the two callers.
    #
    # A markdown row (``code_before_only``) states its code in the cell to the LEFT
    # of the clause, and both clause halves sit in the cell to the RIGHT. Bounding at
    # a delimiter just before either half lands inside the clause -- for a row whose
    # leftmost pipe is the row's own opening pipe it would land left of the code too,
    # and the row's own code would be reported missing. A row's left bound is
    # therefore the FIRST delimiter of the row text handed to this helper. That text
    # is one markdown line, whose leftmost pipe is its opening pipe and whose
    # rightmost is its closing pipe, so the window spans the whole row and the code
    # is read from the leading cell below. The leading pipe is re-added by
    # :func:`_table_row` precisely so this bound has a left boundary to find.
    #
    # Prose callers leave the flag unset and bound at the delimiter before the
    # earlier half: their unit is the ``;``-bounded sentence that carries both halves,
    # so no cell boundary is involved and the earlier bound is the sentence's start.
    left = flat.find(delimiter) + 1 if code_before_only \
        else flat.rfind(delimiter, 0, first) + 1
    # The window must reach past the LAST delimiter the clause itself carries: a
    # clause that quotes ``lstat`` in backticks or lists its kinds with commas can
    # hold the delimiter inside it, and cutting at the first one would cut the window
    # in half and report the row's own code as missing.
    tail = flat.find(delimiter, second + len(CLAUSE_CLOSE))
    window = flat[left:] if tail == -1 else flat[left:tail]
    for kind in kinds:
        assert kind in window, f"{origin}'s clause does not name {kind!r}: {window}"
    if code is not None:
        # The unit the clause owns is the row's leading cell for a table (everything
        # from the row's opening delimiter up to the delimiter that opens the clause's
        # own cell) and the whole window for prose.
        claimed = window.split(delimiter, 1)[0] if code_before_only else window
        assert code.lower() in claimed, (
            f"{origin} states the clause but not its code {code} in the unit that "
            f"owns it: {claimed}")
    return window


def test_product_md_states_the_refusal_with_each_writers_code():
    """Section 7 names each writer's directories and its own code, inside the
    clause rather than beside it.

    The page states this refusal in one paragraph: the walked position, the
    directories, the kinds, and the codes at its end. The paragraph is located by
    both clause markers, so the older session-writer paragraph above it -- which
    shares neither phrase -- cannot satisfy the search, and the code is read from the
    same paragraph so a number lifted from the ``--repo`` discussion cannot be
    credited.
    """
    section = _product_section_7()
    paragraph = _direction_paragraph(section)
    for name, code, dirs in WRITER_CODES:
        assert f"`{name}`" in paragraph, (
            f"docs/PRODUCT.md 7's direction clause never names {name!r}: {paragraph}")
        for rel in dirs:
            assert f"{rel}/" in paragraph, (
                f"docs/PRODUCT.md 7's clause for {name!r} never names {rel}/")
        assert _code_for(_flat(paragraph), code, name), (
            f"docs/PRODUCT.md 7 never gives {name!r} exit {code} for the refused "
            f"directory: {paragraph}")
    _clause(paragraph, "docs/PRODUCT.md 7", delimiter=".")


def _direction_paragraph(section: str) -> str:
    """The one paragraph of section 7 that carries the direction clause."""
    paragraphs = [p for p in section.split("\n\n") if p.strip()]
    found = [p for p in paragraphs
             if CLAUSE_START in _flat(p) and CLAUSE_CLOSE in _flat(p)]
    assert len(found) == 1, (
        f"docs/PRODUCT.md 7 should carry the direction-directory clause in exactly "
        f"one paragraph, found {len(found)}")
    return found[0]


def _code_for(flat: str, code: int, name: str) -> bool:
    """Whether ``code`` is stated for ``name`` and for no one else.

    The page groups tools under one number ("2 for `intent` and `order`, 3 for
    `decide`"), so a name may sit anywhere after its number in a backticked group;
    the separator may not carry a colon or a full stop, so a match cannot reach past
    its own sentence, and ``(?<!\\d)`` stops a 3 inside a 13 from being read as a code.
    """
    group = r"(?:`[^`]+`(?:,\s+|\s+and\s+|\s+)+)"
    return bool(re.search(rf"(?<!\d){code}\s+for\s+{group}?`{name}`", flat))


def test_direction_skill_states_it_in_the_order_rows_exit_code():
    """The operator who reads only the direction skill gets the same contract: the
    ``2`` row of the order table carries the clause, its directories and the kinds."""
    text = DIRECTION_SKILL_MD.read_text(encoding="utf-8")
    row = _table_row(text, "`2`", "skills/direction/SKILL.md")
    _clause(row, "skills/direction/SKILL.md (order 2 row)", delimiter="|",
            code="`2`", code_before_only=True,
            kinds=KINDS + ("noni/direction/", "noni/decisions/"))


def test_direction_skill_states_it_for_intent_on_its_own_code():
    """``intent.py`` publishes its codes in a sentence rather than a table, so the
    clause is located in the sentence that gives ``intent`` its 2."""
    text = DIRECTION_SKILL_MD.read_text(encoding="utf-8")
    # The paragraph of the skill that publishes intent.py's codes: one block, which
    # opens "`intent.py` publishes the same four codes" and gives 2, 3 and 4 in
    # ``;``-separated clauses.
    blocks = [p for p in text.split("\n\n") if "intent.py" in _flat(p)
              and CLAUSE_CLOSE in _flat(p)]
    assert blocks, (
        "skills/direction/SKILL.md never states the direction-directory clause for "
        "intent.py")
    paragraph = blocks[0]
    _clause(paragraph, "skills/direction/SKILL.md (intent)", delimiter=";",
            kinds=KINDS + ("noni/direction/", "noni/decisions/"))
    # The clause's own clause -- the ``;``-bounded unit that carries both halves --
    # is what must state the code, so the number is read from that unit alone.
    flat = _flat(paragraph)
    at, stop = flat.find(CLAUSE_START), flat.find(CLAUSE_CLOSE)
    first, second = sorted((at, stop))
    left, tail = flat.rfind(";", 0, first) + 1, flat.find(";", second + len(CLAUSE_CLOSE))
    unit = flat[left:] if tail == -1 else flat[left:tail]
    assert "`2`" in unit, (
        f"skills/direction/SKILL.md states the clause for intent.py but not its code "
        f"in the unit that owns it: {unit}")


def test_steering_skill_states_it_in_the_decide_rows_exit_code():
    """The steering-ledger skill's ``3`` row carries the clause for decide."""
    text = STEERING_SKILL_MD.read_text(encoding="utf-8")
    row = _table_row(text, "`3`", "skills/steering-ledger/SKILL.md")
    _clause(row, "skills/steering-ledger/SKILL.md (decide 3 row)", delimiter="|",
            code="`3`", code_before_only=True,
            kinds=KINDS + ("noni/decisions/",))


def _table_row(text: str, code_cell: str, origin: str) -> str:
    """The one ``| code | meaning |`` row whose meaning cell carries the clause.

    Returned verbatim -- a markdown table row opens and closes with a pipe, and those
    pipes are the delimiters ``_clause`` cuts the code's cell at. A code that moved to
    another row of the same table, or into the meaning cell of this one, is then not
    credited. Rows are matched on BOTH clause halves so a table that dropped one of
    them fails here rather than silently handing the caller the wrong row.
    """
    rows = [row.strip() for row in text.splitlines()
            if row.strip().startswith(f"| {code_cell} |")
            and CLAUSE_START in _flat(row) and CLAUSE_CLOSE in _flat(row)]
    assert len(rows) == 1, (
        f"{origin} should carry the clause in exactly one {code_cell} row, found "
        f"{len(rows)}")
    # The row is returned verbatim. Its own opening pipe is the left boundary
    # ``_clause`` cuts the code's cell at; prefixing a second pipe (as an earlier
    # revision did) shifted every pipe index by one and pushed the row's own code
    # outside its own cell, so a page that states the code correctly was reported as
    # dropping it. The verbatim row IS the ``| code | meaning |`` unit the contract
    # speaks of, and it already carries both of its boundary pipes.
    return rows[0]


def test_each_writers_docstring_names_the_refusal_with_its_own_code():
    """Every writer's module docstring states the clause on the code it returns.

    The parity suites compare a docstring's code SET against the constants; that says
    nothing about which state each code covers, so the wording is checked here against
    the constant the writer actually returns.
    """
    scripts = {"order": ORDER, "intent": INTENT, "decide": DECIDE}
    for name, code, dirs in WRITER_CODES:
        script = scripts[name]
        doc = _docstring(script, str(script))
        row = _exit_row(doc, code)
        kinds = ("symlink", "plain file", "socket", "device")
        for rel in dirs:
            kinds = kinds + (rel,)
        _clause(row, f"{name}.py's exit {code} row", delimiter=";", kinds=kinds)
        assert name != "order" or "first add" in row, (
            "order.py's clause must say the first add creates the directory, so the "
            f"refusal does not read as a first run being refused: {row}")


def _exit_row(doc: str, code: int) -> str:
    """The one row of a docstring's 'Exit codes:' block that carries ``code``.

    A row is the ``N  text`` line plus the continuation lines indented under it; it
    ends at the next numbered row. The whole row is joined and lower-cased, because
    a clause of the contract can sit anywhere in a row that wraps over six lines.
    """
    lines = doc.splitlines()
    start = lines.index("Exit codes:")
    row: list[str] = []
    for line in lines[start + 1:]:
        if re.match(rf"^\s+{code} \s\S", line):
            row.append(line)
        elif row:
            if re.match(r"^\s+\d+ \s\S", line):
                break
            row.append(line)
    assert row, f"the docstring names no exit {code}"
    return " ".join(row).lower()


def test_the_writers_return_named_exit_constants_for_the_refusal():
    """The guard prints through each writer's own ``_fail`` with its own constant.

    Read from the syntax tree so a docstring that drifted to a bare literal is
    caught: the refusal must go through the constant the parity suites measure, and
    the code a run exits with is the one the page states.
    """
    for name, code, _dirs in WRITER_CODES:
        script = {"order": ORDER, "intent": INTENT, "decide": DECIDE}[name]
        tree = _script_ast(script)
        wanted = _exit_constants(tree, code)
        assert wanted, f"{name}.py defines no EXIT_* constant holding {code}"
        assert _returns_constant(tree, wanted), (
            f"{name}.py must return a named EXIT_* constant for exit {code}, not a "
            f"literal")


def _exit_constants(tree, code: int) -> set[str]:
    """The names of the module's ``EXIT_*: int = <code>`` bindings."""
    found: set[str] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant) or value.value != code:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                found.add(target.id)
    return found


def _returns_constant(tree, wanted: set[str]) -> bool:
    """Whether the module passes one of ``wanted`` as the first argument of a call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id in wanted:
            return True
    return False
