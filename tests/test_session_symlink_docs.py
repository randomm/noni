"""The symlink refusal is written down in every place that owes it (issue #68).

docs/PRODUCT.md 7 and the sessions-claims skill are the operator's only contract
for what a symlinked session file or a symlinked ``noni/sessions/`` costs them:
the code and the wording. Four copies exist (the product page, the skill, the two
reference pages, and each writer's own docstring), and a fifth lives in the guard
itself. Nothing but the checks below compares the five, which is how a doc that
renamed the code, or a writer that changed it, would otherwise pass every suite.

Modelled on ``tests/test_state_root_refusal.py``: the expected code is read off
the page rather than trusted from the writer's constant, and the prose is read
for the state and the code together so a sentence that dropped the symlink half
fails here instead of silently disagreeing with the runs in
``test_session_symlink_refusal.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, REPO, _script_ast

PRODUCT = REPO / "docs" / "PRODUCT.md"
SKILL_MD = REPO / "skills" / "sessions-claims" / "SKILL.md"
REFERENCES = REPO / "skills" / "sessions-claims" / "references"

# What the prose owes for this one state, per writer: the code docs/PRODUCT.md 7
# gives a wrong path, and the two paths the guard inspects. The tuple is the prose
# transcribed -- a change on either side breaks the test that reads it.
SYMLINK_REFUSAL = (
    ("register", REGISTER, 2),
    ("claim", CLAIM, 4),
    ("close", CLOSE, 4),
    ("release", RELEASE, 4),
)

# The two shapes every doc must name, as substrings of its own sentence. A page
# that said only "symlink" without saying WHICH path is the ambiguity that caused
# the disagreement in the first place.
SESSION_FILE_SHAPE = "session file"
SESSIONS_DIR_SHAPE = "sessions"


def _section(text: str, heading: str, origin: str) -> str:
    """The body of one ``## `` heading, up to the next one."""
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _product_section_7() -> str:
    """docs/PRODUCT.md section 7, read from the page rather than restated here."""
    return _section(PRODUCT.read_text(encoding="utf-8"),
                    "## 7. State layout and the state root", "docs/PRODUCT.md")


def _docstring(tree: ast.Module, origin: str) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), f"{origin} has no module docstring"
    return doc


def _sentence_words(text: str) -> str:
    """``text`` with every run of whitespace collapsed to one space.

    A docstring row or a markdown cell wraps at column eighty, so "session file"
    can be split across a line break; the contract is about the words, not the
    column they happened to wrap at.
    """
    return " ".join(text.split())


def _exit_block(doc: str, code: int) -> str:
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

def test_product_md_states_the_symlink_refusal_with_each_writers_code():
    """Section 7 names the session file and the sessions directory, and the code
    each of the four writers owes for them."""
    section = _product_section_7().lower()
    assert "symlink" in section, "section 7 no longer speaks of a symlink at all"
    for name, _script, code in SYMLINK_REFUSAL:
        sentence = _sentence_words(_sentence_naming(section, name))
        assert SESSION_FILE_SHAPE in sentence, (
            f"docs/PRODUCT.md 7 must name the session file for {name}: {sentence}")
        assert SESSIONS_DIR_SHAPE in sentence, (
            f"docs/PRODUCT.md 7 must name the sessions directory for {name}: "
            f"{sentence}")
        assert str(code) in sentence, (
            f"docs/PRODUCT.md 7 must state exit {code} for {name}: {sentence}")


def test_skill_md_states_the_refusal_in_each_writers_exit_sentence():
    """The operator who reads only the skill gets the same contract: each verb's
    own 'Exit codes:' sentence names both shapes beside its refusal code."""
    text = SKILL_MD.read_text(encoding="utf-8")
    for verb, heading in (("close", "## Closing a session"),
                          ("release", "## Releasing a claim")):
        section = _section(text, heading, "SKILL.md")
        match = re.search(r"^Exit codes:(.*?)(?:\n\n|\Z)", section,
                          re.MULTILINE | re.DOTALL)
        assert match, f"SKILL.md's {heading} has no 'Exit codes:' sentence"
        sentence = match.group(1).lower()
        assert "symlink" in sentence, f"SKILL.md's {verb} sentence dropped symlink"
        assert SESSIONS_DIR_SHAPE in sentence, (
            f"SKILL.md's {verb} sentence must name the sessions directory")
        assert "`2`" in sentence, f"SKILL.md's {verb} sentence must name code 2"


def test_reference_pages_state_the_refusal_with_their_codes():
    """references/claim.md carries the three tables the writers publish, and
    references/register.md carries register's exit-2 rule."""
    claim = (REFERENCES / "claim.md").read_text(encoding="utf-8").lower()
    for shape in (SESSION_FILE_SHAPE, SESSIONS_DIR_SHAPE, "symlink"):
        assert shape in claim, f"references/claim.md no longer names {shape!r}"
    register = (REFERENCES / "register.md").read_text(encoding="utf-8").lower()
    assert "symlink" in register, "references/register.md no longer names a symlink"
    assert SESSIONS_DIR_SHAPE in register, (
        "references/register.md must name the sessions directory")
    assert "exit 2" in register, (
        "references/register.md must state the refusal's code")


def test_each_writers_docstring_names_the_refusal_with_its_own_code():
    """Every writer's module docstring states both shapes on the code it owes.

    The parity suites compare a docstring's code SET against the constants; that
    says nothing about which state each code covers, so the wording is checked
    here against the constant the writer actually returns.
    """
    for name, script, code in SYMLINK_REFUSAL:
        tree = _script_ast(script)
        row = _sentence_words(_exit_block(_docstring(tree, str(script)), code))
        assert "symlink" in row, f"{name}.py's exit {code} row dropped symlink"
        assert SESSION_FILE_SHAPE in row, (
            f"{name}.py's exit {code} row must name the session file: {row}")
        assert SESSIONS_DIR_SHAPE in row, (
            f"{name}.py's exit {code} row must name the sessions directory: {row}")
        constant = _returned_constant(tree, name, code)
        assert constant is not None, (
            f"{name}.py must name a constant for the symlink refusal, not a literal")


def _returned_constant(tree: ast.Module, name: str, code: int) -> str | None:
    """The EXIT_* constant one writer returns for its refusal code, or None.

    Read from the syntax tree so a docstring that drifted to a bare literal is
    caught: the guard must go through the constant the parity suites measure.
    """
    wanted = {value.id: target.value
              for target, value in _exit_constants(tree)
              if target.value == code}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id in wanted:
            return first.id
    return None


def _exit_constants(tree: ast.Module) -> list[tuple[ast.Constant, ast.Name]]:
    """The ``(value, name)`` pairs of the module's ``EXIT_*: int = <n>`` bindings."""
    found: list[tuple[ast.Constant, ast.Name]] = []
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                found.append((value, target))
    return found


def _sentence_naming(text: str, name: str) -> str:
    """The sentence of ``text`` that both names the tool and refuses the link.

    The page states one code per group of tools, so the sentence sought is the one
    that names the tool *and* the state: a page that dropped the symlink half, or
    moved the code to a neighbouring sentence, fails here instead of passing on an
    unrelated mention of the tool's name.
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if f"`{name}`" in s]
    assert sentences, f"docs/PRODUCT.md 7 no longer names {f'`{name}`'}"
    for sentence in sentences:
        if "symlink" in sentence:
            return sentence
    raise AssertionError(
        f"docs/PRODUCT.md 7 no longer states a symlink refusal naming {name}: "
        f"{sentences}")


def test_the_guard_module_is_the_single_home_of_the_wording():
    """The refusal's wording lives in one module, so the four writers cannot each
    compose their own sentence about the same state."""
    from noni import _session_paths
    assert _session_paths.SYMLINK_WORD in str(_session_paths.FILE_REFUSAL)
    for template in (_session_paths.FILE_REFUSAL, _session_paths.DIR_REFUSAL):
        assert "{path}" in template, "a refusal must name the offending path"
        assert "{kind}" in template, "a refusal must name the kind the lstat found"
    assert isinstance(Path, type)  # the module speaks in Path objects, not strings
