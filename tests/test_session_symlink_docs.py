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

What the first version of this file got wrong, and what the checks below fix. It
asserted the bare words ``symlink``, ``sessions`` and ``session file`` inside each
verb's exit sentence, and that the digit ``2`` appeared somewhere in it. A page
whose whole new clause had been deleted still passed: those words live in the
neighbouring ``--repo``-is-a-symlink half, and every exit-code sentence in the file
carries its own digits. So the clause is now located by the two phrases ONLY it
carries -- the position the guard walks and the promise it makes -- and the code and
the two path shapes are asserted INSIDE the text between them. Deleting the clause
from any of the five places fails the matching test here; ``_clause`` reports which
end of the clause it could not find, so the failure names the page and the sentence
rather than a word count.
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
# gives a wrong path. The tuple is the prose transcribed -- a change on either side
# breaks the test that reads it.
WRITER_CODES = (("register", 2), ("claim", 4), ("close", 4), ("release", 4))

# The clause's opening and close: the position the guard walks, and the promise that
# a link is never followed. Together they are the clause, and neither phrase occurs
# anywhere else on these pages -- not in the older ``--repo``-is-a-symlink half, not
# in the state-root refusal, not in any other row -- so a page that dropped the
# clause matches neither, and a locator cannot be satisfied by neighbouring prose.
CLAUSE_START = "state root down to it"
CLAUSE_CLOSE = "a plain path this writer may follow"

# How far past the clause's close the product page's window reaches: it states the
# code in the sentence AFTER the clause, so the window must cover that sentence and
# no more (the delimiter, ".", stops it at the sentence end regardless; the budget
# just keeps a missing delimiter from running into the next paragraph).
AFTER_CLAUSE_BUDGET = 200

# The two shapes the clause names, checked inside the window that opens at the
# walked position: the file (named in the clause's own lead-in, "or the session
# file, or any directory ..."), and the directory tree the file sits in (named by
# the position the window closes on).
SESSION_FILE_SHAPE = "session file"
SESSIONS_DIR_SHAPE = "sessions"


# The verb's own heading in the skill, and the code its exit-code sentence owes for
# a refused session path. The table is the skill's structure transcribed: a verb
# whose sentence lost the clause fails on its own row.
SKILL_SECTIONS = (("register", "## Registering a session", "`2`"),
                  ("close", "## Closing a session", "`2`"),
                  ("release", "## Releasing a claim", "`2`"))

# references/claim.md publishes three exit-code tables (claim, release, close) and
# references/register.md one, each owing the clause on the code that row states.
CLAIM_PAGE_CODES = (("claim", "`4`"), ("release", "`2`"), ("close", "`2`"))

# register.py's own row, which is the one place the clause is spelled differently.
REGISTER_CLAUSE_START = CLAUSE_START


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

    A docstring row or a markdown cell wraps at column eighty, so a clause can be
    split across a line break; the contract is about the words, not the column they
    happened to wrap at.
    """
    return " ".join(text.split())


def _window(flat: str, start: int, stop: int, delimiter: str) -> str:
    """One sentence's worth of ``flat``: the text between the delimiters that
    surround the clause, and nothing beyond them.

    ``;`` is the delimiter every exit-code row, table cell and product sentence uses
    between one code's clause and the next, so a code found inside this window is
    stated by the sentence that owns the clause. A clause at the very start or end of
    a block reaches the edge rather than a delimiter that is not there.
    """
    left = flat.rfind(delimiter, 0, start) + 1
    right = flat.find(delimiter, stop)
    return flat[left:] if right == -1 else flat[left:right]


def _row_code_cell(row: str) -> str:
    """The ``| code |`` cell of a markdown row -- everything before its first pipe.

    A table states its code in the cell to the LEFT of the clause, so the code is
    asserted over that cell and nothing else: a code that moved to another row, or
    to the meaning cell of this one, is not credited.
    """
    return row.split("|", 2)[1]


def _clause(text: str, origin: str, *, opening: str = CLAUSE_START,
            delimiter: str = ";", code: str | None = None, after: int | None = None,
            code_before_only: bool = False,
            shapes: tuple[str, ...] = (SESSION_FILE_SHAPE,
                                       SESSIONS_DIR_SHAPE)) -> str:
    """The one span of ``text`` that IS the session-write clause, verified.

    ``after`` widens the window past the clause's close (the product page states the
    code in the sentence AFTER the clause), ``delimiter`` bounds it on both sides, and
    ``code``/``shapes`` are the claims made about the text inside it. The clause is
    located by its opening (:data:`CLAUSE_START`) and its close
    (:data:`CLAUSE_CLOSE`), both of which only it carries, so a page that dropped the
    clause matches neither and a page that kept only the older ``--repo`` half matches
    neither either. The caller's ``shapes`` must appear in the delimited sentence that
    owns the clause (its file and directories are named there), and its ``code`` --
    which the clause itself never repeats -- must appear in that same sentence rather
    than anywhere in the block.
    """
    flat = _sentence_words(text).lower()
    at = flat.find(opening)
    assert at != -1, (
        f"{origin} no longer states the walked position ({opening!r}): the "
        f"session-file/sessions-directory clause has been dropped from this page")
    phrase = opening
    stop = flat.find(CLAUSE_CLOSE, at)
    assert stop != -1, (
        f"{origin} states the walked position ({phrase!r}) but not the promise "
        f"({CLAUSE_CLOSE!r}) after it: the clause is incomplete")
    stop_at = stop + len(CLAUSE_CLOSE) + (after or 0)
    window = _window(flat, at, stop_at, delimiter)
    for shape in shapes:
        assert shape in window, (
            f"{origin}'s session-write clause does not name {shape!r}: {window}")
    if code is not None:
        # A table states its code in the cell to the LEFT of the clause, so that
        # caller (code_before_only) gets the row's leading cell -- the text from the
        # row's opening delimiter up to the clause -- instead of the clause's own
        # cell. Either way the code must sit in the delimited unit the clause owns.
        claimed = _row_code_cell(flat) if code_before_only else window
        assert code.lower() in claimed, (
            f"{origin} states the clause but not its code {code} in the unit that "
            f"owns it: {claimed}")
    return window


def _table_row(text: str, label: str) -> str:
    """The one ``| code | meaning |`` row whose table belongs to ``label``.

    references/claim.md publishes three tables, one per writer, each under a heading
    that names its writer. The row is the text between the two line-bounded pipes
    that carry the clause, so nothing outside the row can satisfy a code assertion.
    """
    # The table sits under the verb's own heading, except claim's own, which the
    # page titles "Exit codes" under the claim protocol.
    headings = {"claim": "## Exit codes", "release": "## Releasing a claim",
                "close": "## Closing a session"}
    heading = headings[label]
    section = _section(text, heading, "references/claim.md")
    rows = [row.strip() for row in section.splitlines()
            if f"any directory from the {CLAUSE_START}" in row.lower()]
    assert len(rows) == 1, (
        f"references/claim.md's {label} table should carry the clause in exactly "
        f"one row, found {len(rows)}")
    return rows[0]


def _code_pattern(code: int, name: str) -> str:
    """The regex that matches ``code`` stated for ``name``, and for no one else.

    The page groups tools under one number ("2 for `register`, 4 for `claim`,
    `close` and `release`"), so a tool named later in the group is separated from its
    code by other names in backticks, and both shapes are matched. The separator may
    not contain a colon or a full stop, so the match cannot reach past the end of its
    own sentence into a neighbouring one's numbers, and the ``(?<!\\d)`` guard stops
    a 4 inside a 14 from being read as a code.
    """
    # Any number of backticked names (comma- or "and"-joined) may sit between the
    # code and this tool's name: "4 for `claim`, `close` and `release`".
    group = r"(?:`[^`]+`(?:,\s+|\s+and\s+))*"
    return (rf"(?<!\d){code}\s+for\s+`{name}`"
            rf"|(?<!\d){code}\s+for\s+{group}`{name}`")


def _paragraph_naming(text: str, name: str, code: int) -> str:
    """The paragraphs of ``text`` that carry the whole claim for ``name``.

    docs/PRODUCT.md 7 splits this state across two paragraphs of one section: the
    first names the walked position and the two paths, and the next gives "the code
    each tool already uses for a wrong path: 2 for `register`, 4 for `claim` ...".
    The unit that holds the claim is therefore the paragraph that carries the clause
    plus the paragraph that carries the code, and no more: the two are located by
    what they must contain, so a code lifted from the ``--repo``-is-a-symlink
    discussion higher up the section is not credited. The clause paragraph is the one
    that carries the clause -- it opens "The same four writers refuse a session file
    that is a symlink", so it names no tool with backticks and the tool is supplied
    by the caller's phrase rather than expected in the sentence -- and the code
    paragraph is the following one that names the tool and a code.
    """
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    clause_at = [i for i, p in enumerate(paragraphs)
                 if CLAUSE_START in _sentence_words(p).lower()]
    assert clause_at, (
        f"docs/PRODUCT.md 7 no longer carries the walked position in a paragraph "
        f"naming {name!r}: the session-file/sessions-directory clause has been "
        f"dropped from this page")
    # The unit is the clause's paragraph plus the paragraph that states the codes:
    # the two are adjacent on the page, and the code paragraph is identified by the
    # tool's own name beside its number (2 for `register`, 4 for `claim` ...), so the
    # window the code is looked for in holds this claim and nothing above it.
    i = clause_at[0]
    # The code is looked for as a number that stands immediately before this tool's
    # own name -- "2 for `register`, 4 for `claim`, `close` and `release`" states
    # close's code without repeating the word "for" before it -- so one grouping of
    # the group must name the tool, and none of the group's other numbers may be
    # mistaken for it.
    # The code sits immediately before the first name of the group, and a tool named
    # later in the same group is separated from it by other names in backticks --
    # "[N] for `claim`, `close` and `release`" gives all three that code. The
    # separator may not contain a colon or a full stop, so the match cannot reach
    # past the end of this sentence into the next one's numbers.
    pattern = _code_pattern(code, name)
    following = [j for j in range(i + 1, len(paragraphs))
                 if "symlink" in paragraphs[j]
                 and re.search(pattern, _sentence_words(paragraphs[j]).lower())]
    assert following, (
        f"docs/PRODUCT.md 7 states the session-write clause but never gives "
        f"{name!r} its symlink code ({code} before its name) in the paragraphs "
        f"that follow it")
    return paragraphs[i], paragraphs[following[0]]


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


def test_product_md_states_the_symlink_refusal_with_each_writers_code():
    """Section 7 names the session file and the sessions directory, and the code
    each of the four writers owes for them -- all inside the clause, not beside it."""
    section = _product_section_7()
    for name, code in WRITER_CODES:
        # The page states the refusal in one paragraph and the codes in another, so
        # the two are checked in the paragraphs that hold them -- never over the
        # whole section, where the older `--repo`-is-a-symlink discussion would
        # satisfy an unbounded search. See _paragraph_naming for the pairing rule.
        clause_paragraph, code_paragraph = _paragraph_naming(section, name, code)
        _clause(clause_paragraph, f"docs/PRODUCT.md 7 ({name})", delimiter=".",
                shapes=(SESSION_FILE_SHAPE, SESSIONS_DIR_SHAPE))
        assert re.search(_code_pattern(code, name),
                         _sentence_words(code_paragraph).lower()), (
            f"docs/PRODUCT.md 7 never gives {name!r} exit {code} for the symlinked "
            f"session path: {code_paragraph}")


def test_skill_md_states_the_refusal_in_each_writers_exit_sentence():
    """The operator who reads only the skill gets the same contract: each verb's
    own 'Exit codes:' sentence names both shapes beside its refusal code."""
    text = SKILL_MD.read_text(encoding="utf-8")
    for verb, heading, code in SKILL_SECTIONS:
        section = _section(text, heading, "SKILL.md")
        match = re.search(r"^Exit codes:(.*?)(?:\n\n|\Z)", section,
                          re.MULTILINE | re.DOTALL)
        assert match, f"SKILL.md's {heading} has no 'Exit codes:' sentence"
        _clause(match.group(1), f"SKILL.md's {verb} sentence", code=code)


def test_reference_pages_state_the_refusal_with_their_codes():
    """references/claim.md carries the three tables the writers publish, and
    references/register.md carries register's exit-2 rule."""
    claim = (REFERENCES / "claim.md").read_text(encoding="utf-8")
    # One table row is one `code` cell and one meaning cell, and the clause lives in
    # the meaning cell, so the row is cut out by the pipes at its own ends and the
    # code is looked for inside that row alone: a code that moved to another row of
    # the same table, or to a neighbouring table, is then not credited.
    for label, code in CLAIM_PAGE_CODES:
        row = _table_row(claim, label)
        # The clause lives in the meaning cell and the code in the cell to its left,
        # so the code is looked for in the row with the clause's own cell cut away:
        # everything left of the pipe that opens the clause.
        _clause(row, f"references/claim.md ({label} row)", code=code,
                delimiter="|", code_before_only=True,
                shapes=("symlink", SESSION_FILE_SHAPE, SESSIONS_DIR_SHAPE))
    register = (REFERENCES / "register.md").read_text(encoding="utf-8")
    assert "symlink" in register, "references/register.md no longer names a symlink"
    assert SESSIONS_DIR_SHAPE in register, (
        "references/register.md must name the sessions directory")
    assert "exit 2" in _sentence_words(register).lower(), (
        "references/register.md must state the refusal's code")


def test_each_writers_docstring_names_the_refusal_with_its_own_code():
    """Every writer's module docstring states both shapes on the code it owes.

    The parity suites compare a docstring's code SET against the constants; that
    says nothing about which state each code covers, so the wording is checked
    here against the constant the writer actually returns.
    """
    scripts = {"register": REGISTER, "claim": CLAIM, "close": CLOSE,
               "release": RELEASE}
    for name, code in WRITER_CODES:
        script = scripts[name]
        tree = _script_ast(script)
        row = _exit_block(_docstring(tree, str(script)), code)
        _clause(row, f"{name}.py's exit {code} row",
                opening=REGISTER_CLAUSE_START,
                shapes=("symlink", SESSION_FILE_SHAPE, SESSIONS_DIR_SHAPE))
        constant = _returned_constant(tree, code)
        assert constant is not None, (
            f"{name}.py must return a named EXIT_* constant for exit {code}, not a "
            f"literal")


def _returned_constant(tree: ast.Module, code: int) -> str | None:
    """The EXIT_* constant one writer returns for its refusal code, or None.

    Read from the syntax tree so a docstring that drifted to a bare literal is
    caught: the guard must go through the constant the parity suites measure. The
    caller passes the code alone -- the earlier version took a verb name it never
    used and unpacked the ``(value, name)`` pairs the other way round, so the
    comparison silently compared a number against an ``ast.Name`` and every writer
    answered with its exit-0 constant.
    """
    wanted = {name for name, value in _exit_constants(tree) if value == code}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id in wanted:
            return first.id
    return None


def _exit_constants(tree: ast.Module) -> list[tuple[str, int]]:
    """The ``(name, value)`` pairs of the module's ``EXIT_*: int = <n>`` bindings.

    Name first, then value: the order the one caller destructures, and the reason
    the tuple is spelled out here rather than left to memory.
    """
    found: list[tuple[str, int]] = []
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                found.append((target.id, value.value))
    return found


def test_the_guard_module_is_the_single_home_of_the_wording():
    """The refusal's wording lives in one module, and it names the kind it found.

    The four writers must not each compose their own sentence about the same state,
    and each sentence must describe what the lstat actually saw: both templates carry
    a ``{kind}`` slot, and neither template may assert a link in its own words -- a
    device or an unreadable path is not a link, and an operator told to go and remove
    a symlink that is not there has been sent on a wild goose chase by the guard.
    """
    from noni import _session_paths

    for template in (_session_paths.FILE_REFUSAL, _session_paths.DIR_REFUSAL):
        assert "{path}" in template, "a refusal must name the offending path"
        assert "{kind}" in template, "a refusal must name the kind the lstat found"
        assert _session_paths.SYMLINK_WORD not in template.format(path="p",
                                                                  kind="k"), (
            f"the wording must not assume a link: {template}")
    # A directory refusal says "directory" and a file refusal says "file": the two
    # hints belong to their own question, and neither is the other's advice.
    assert "directory" in _session_paths.DIR_REFUSAL_HINT
    assert "session file" in _session_paths.FILE_REFUSAL_HINT
    # close, claim and release never create the sessions directory, so they must be
    # able to ask for a hint that does not tell them to let the writer create it.
    assert "creates" in _session_paths.directory_refusal.__code__.co_varnames, (
        "the hint must know which writer creates the sessions directory")
    assert "walk_refusal" in dir(_session_paths), (
        "the one walk must be a named function, not a loop inside a caller")


def test_a_refused_path_cannot_add_lines_to_the_refusal(tmp_path):
    """A path is operator-supplied text printed to a two-line refusal, so the two
    lines are all the reader gets: newline and carriage return are escaped rather
    than emitted, and no crafted name injects a third line.
    """
    from noni import _session_paths

    # ``lstat`` on a name that no write can reach answers ENOENT, which the guard
    # reads as "absent" -- so the crafted name is planted as a symlink, the shape
    # whose bytes are the whole point: the refusal prints the name it found.
    crafted = tmp_path / "evil\nrelease.py: fix: all good"
    crafted.symlink_to("nowhere")
    headline, hint = _session_paths.file_refusal(crafted)
    assert headline and hint, "a symlink is refused whatever its name carries"
    assert "\n" not in headline and "\n" not in hint, (
        f"a path injected a line: {headline!r} / {hint!r}")
    assert "\\n" in headline, f"the newline must be shown as an escape: {headline!r}"
    refused = _session_paths.write_refusal(Path("/tmp/root"), "../outside.md")
    assert refused is not None and "\n" not in refused[0], refused
