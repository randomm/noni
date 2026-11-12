"""The direction skill's documents against the intent writer that produced them.

The intent half of the skill: the module docstring's Usage and exit table, the
template a reader copies, and the rows of the census the reader repairs with this
writer. The ordering half is covered by ``tests/test_order_writer_docs.py``, whose
shape this file follows; the two are separate files because the two writers share
no rules and a change to one should not look like a change to the other.
"""

from __future__ import annotations

import ast
import re

from _harness import INTENT, REPO
from intent_fixtures import GOOD_INTENT, INTENT_REL
from intent_writer_support import INTENT_SKILL_DIR, intent_ast, parser_flags

from noni import intentschema

# The four codes the writer publishes, pinned to the settled set the whole
# product uses: nothing documents a code nothing returns, and nothing returns a
# code the docstring does not explain.
EXIT_CODES = {0, 2, 3, 4}


def test_docstring_exit_codes_match_the_exit_constants():
    tree = intent_ast()
    published = exit_codes_of(tree)
    documented = doc_block(docstring(tree), "Exit codes:")
    assert documented.keys() == published, (
        f"docstring lists {sorted(documented)} but the constants are "
        f"{sorted(published)}")
    assert published == EXIT_CODES, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block, and the block
    names nothing the parser would reject."""
    tree = intent_ast()
    parser = parser_flags(tree) - {"--help"}
    documented = doc_usage_flags(docstring(tree))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--strict", "--json", "--force"):
        assert forbidden not in parser, f"{forbidden} is out of scope for intent.py"


def test_help_names_repo_the_state_root():
    """``intent --help`` calls ``--repo`` the state root, the word the product uses.

    The writer commits into the tree the flag names, which is not always the caller's own
    (docs/PRODUCT.md 7), so the help line and the refusal name the tree by what it is.
    """
    help_text = _parser_repo_help(intent_ast())
    assert "the state root" in help_text, help_text
    assert "repository root" not in help_text, help_text
    # The refusal a bad ``--repo`` answers with uses the same words the help page does.
    source = (REPO / "src" / "noni" / "intent.py").read_text(encoding="utf-8")
    assert "pass the state root that holds" in source, source


def _parser_repo_help(tree) -> str:
    """The ``--repo`` help string the parser declares, read out of ``main``.

    Read from the source rather than from a launched ``--help``: the flag's help is a literal the
    module holds, so answering the question needs no tree, no identity and no git run.
    """
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    for node in ast.walk(main):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "--repo"):
            for keyword in node.keywords:
                if keyword.arg == "help":
                    return ast.literal_eval(keyword.value)
    raise AssertionError("the parser declares no --repo help string")


def test_docstring_names_the_refusals_the_code_performs():
    """The table is what a caller predicts a run's exit code from, so each
    refusal the code actually performs is named in it."""
    block = doc_block(docstring(intent_ast()), "Exit codes:")
    four = block[4].lower()
    for condition in ("section", "line cap", "last-confirmed", "no file under",
                      "superseded"):
        assert condition in four, f"the exit 4 row omits {condition!r}: {block[4]}"
    three = block[3].lower()
    for condition in ("not a regular file", "could not be written", "commit",
                      "timed out"):
        assert condition in three, f"the exit 3 row omits {condition!r}: {block[3]}"
    two = block[2].lower()
    for condition in ("--from", "--decision", "subcommand", "utf-8", "utc timestamp"):
        assert condition in two, f"the exit 2 row omits {condition!r}: {block[2]}"


def test_skill_md_documents_the_writer_within_the_line_cap():
    """SKILL.md documents intent.py: its Usage, the four sections, the exit
    table, and the census rows a reader repairs with it."""
    text = (INTENT_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/intent.py" in text, "SKILL.md does not document the writer"
    assert "intent.py set" in text, "SKILL.md omits the one verb"
    for flag in ("--from", "--decision", "--no-commit"):
        assert flag in text, f"SKILL.md omits {flag}"
    assert INTENT_REL in text, "SKILL.md does not name the artifact"
    for section in intentschema.REQUIRED_SECTIONS:
        assert f"## {section}" in text, f"SKILL.md omits the {section} section"
    assert intentschema.LAST_CONFIRMED_PREFIX in text, "SKILL.md omits the stamp line"
    assert str(intentschema.MAX_LINES) in text, "SKILL.md omits the line cap"
    for code in sorted(EXIT_CODES):
        assert f"| `{code}` |" in text, f"SKILL.md's exit table omits code {code}"
    for subject in ("section-missing", "over-cap", "uncited", "cannot-tell"):
        assert subject in text, f"SKILL.md does not say how to repair a {subject} row"
    assert text.count("\n") <= 400, f"SKILL.md is {text.count(chr(10))} lines; cap is 400"


def test_skill_md_states_the_precedence_rule_and_the_session_protocol():
    """The two promises the intent file exists to keep, in the skill an agent
    loads: where an answer comes from, and when the agent must ask."""
    text = (INTENT_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    precedence = text.lower()
    assert "precedence" in precedence, "SKILL.md states no precedence rule"
    # The order of the three sources, in the order the rule applies them.
    ledger_at = precedence.index("most recent applicable ledger decision")
    intent_at = precedence.index("otherwise `noni/direction/intent.md`")
    ask_at = precedence.index("wait and ask")
    assert ledger_at < intent_at < ask_at, (
        "the precedence rule does not put the ledger above the intent, or the "
        "intent above asking")
    assert "never" in precedence.split("ask first", 1)[-1][:600], (
        "SKILL.md does not say an Ask-first item is never decided autonomously")
    assert "session start" in precedence, "SKILL.md omits the per-session protocol"


def test_the_template_is_a_draft_the_writer_accepts():
    """The file a reader copies validates, stays within the cap, and names the
    writer's own command: a template the writer refuses is a page that lies."""
    path = INTENT_SKILL_DIR / "references" / "intent-template.md"
    text = path.read_text(encoding="utf-8")
    assert intentschema.problems(text) == [], intentschema.problems(text)
    assert len(text.split("\n")) <= intentschema.MAX_LINES, "the template is over its own cap"
    assert "scripts/intent.py" in text, "the template does not say how to install it"
    for section in intentschema.REQUIRED_SECTIONS:
        assert f"## {section}" in text, f"the template omits {section}"


def test_the_good_draft_both_suites_build_validates():
    """The one draft the fixtures share is an intent file, so a fixture drift
    shows up as a schema failure rather than as a puzzling row elsewhere."""
    assert intentschema.problems(GOOD_INTENT) == []


def test_the_census_skill_documents_the_class_and_its_code():
    """The census's SKILL.md is the reader's only table for what a row means."""
    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    assert "| `intent` | 51 |" in text, "census SKILL.md omits the intent class"
    assert "51  intent" in text, "census SKILL.md's exit table omits the intent class"
    assert "<repo>/noni/direction/intent.md" in text, "the intent default is undocumented"
    assert "--intent" in text, "the --intent override is undocumented"


def test_the_writer_is_the_only_writer_and_carries_the_executable_bit():
    """The skill's layout assertion knows about scripts/intent.py, and the file
    is executable like the other skill scripts."""
    assert (INTENT_SKILL_DIR / "scripts" / "intent.py").is_file()
    assert INTENT.stat().st_mode & 0o111, "intent.py is not executable"
    layout = (REPO / "tests" / "test_skill_scrub.py").read_text(encoding="utf-8")
    assert "scripts/intent.py" in layout, "test_skill_scrub.py omits scripts/intent.py"


def test_no_secrets_or_machine_local_paths_in_the_new_files():
    """The scrub's own patterns, applied to the three new files by name: the
    gate that covers them is parametrised over the skill directories, and a
    parametrisation that quietly stopped including a file would be invisible
    without this."""
    from public_safety import (
        FIXTURE_HOME_PATH_PATTERNS,
        HOME_PATH_PATTERNS,
        SECRET_PATTERNS,
    )
    paths = (INTENT_SKILL_DIR / "SKILL.md", INTENT,
             INTENT_SKILL_DIR / "references" / "intent-template.md")
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in (*HOME_PATH_PATTERNS, *FIXTURE_HOME_PATH_PATTERNS,
                                   *SECRET_PATTERNS):
                assert not pattern.search(line), f"{path.name}:{lineno}: {label}"


# --- the reader for the docstring's blocks ------------------------------------
# Same shapes as the order fixtures' helpers, kept here rather than shared: the
# two writers document themselves and the readers follow their wording.

def doc_block(doc: str, header: str) -> dict[int, str]:
    """The numbered rows of one indented docstring block, keyed by exit code."""
    lines = doc.splitlines()
    start = _line_of(lines, header)
    block: dict[int, str] = {}
    current: int | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif current is not None:
            block[current] += " " + line.strip()
    assert block, f"docstring block {header!r} has no numbered rows"
    return block


def doc_usage_flags(doc: str) -> set[str]:
    """The long options the Usage block names."""
    lines = doc.splitlines()
    start = _line_of(lines, "Usage:")
    flags: set[str] = set()
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, "the Usage block names no flags"
    return flags


def docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "intent.py has no module docstring"
    return doc


def exit_codes_of(tree: ast.Module) -> set[int]:
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
    assert codes, "intent.py defines no EXIT_* constants"
    return codes


def _line_of(lines: list[str], header: str) -> int:
    try:
        return next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise AssertionError(f"docstring has no {header!r} block") from None
