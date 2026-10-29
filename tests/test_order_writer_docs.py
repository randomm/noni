"""The order skill's documents against the writer that produced them.

Extracted from the order writer suite: SKILL.md, the reference, and the fixture
the census and the writer both read."""

from _harness import (
    ORDER,
    REPO,
)
from order_fixtures import (
    FIXTURE,
    ORDERING_CHECKS,
    SKILL_DIR,
    _doc_block,
    _doc_usage_flags,
    _docstring,
    _module_exit_codes,
    _order_ast,
    _parser_flags,
)


def test_docstring_exit_codes_match_the_exit_constants():
    """The docstring's exit table and the EXIT_* constants are one contract,
    pinned to the settled set 0/2/3/4: no code is documented that nothing
    returns, and none is returned that the table does not explain."""
    tree = _order_ast()
    published = _module_exit_codes(tree)
    documented = set(_doc_block(_docstring(tree), "Exit codes:"))
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}")
    assert published == {0, 2, 3, 4}, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block and the block
    names nothing the parser would reject; no --push, --strict or --json."""
    tree = _order_ast()
    parser = _parser_flags(tree) - {"--help"}
    documented = _doc_usage_flags(_docstring(tree))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--strict", "--json"):
        assert forbidden not in parser, f"{forbidden} is out of scope for order.py"


def test_docstring_names_the_refusals_the_code_performs():
    """The table is what a caller predicts a run's exit code from, so each
    refusal the code actually performs is named in it."""
    block = _doc_block(_docstring(_order_ast()), "Exit codes:")
    four = block[4].lower()
    for condition in ("already listed", "absent from the order", "no file under",
                      "superseded", "not the artifact"):
        assert condition in four, f"the exit 4 row omits {condition!r}: {block[4]}"
    three = block[3].lower()
    for condition in ("not a regular file", "could not be written", "commit"):
        assert condition in three, f"the exit 3 row omits {condition!r}: {block[3]}"
    two = block[2].lower()
    for condition in ("positive integer", "--decision", "1-based", "iso-8601"):
        assert condition in two, f"the exit 2 row omits {condition!r}: {block[2]}"


def test_skill_md_documents_the_writer_within_the_line_cap():
    """The skill documents order.py: its Usage, the four verbs, the artifact's
    two fields, the exit table, and the census rows a reader repairs with it."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/order.py" in text, "SKILL.md does not document the writer"
    for verb in ("add", "move", "remove", "confirm"):
        assert f"order.py {verb}" in text or f"`{verb}`" in text, f"SKILL.md omits {verb}"
    for flag in ("--decision", "--no-commit", "--now", "--at", "--to"):
        assert flag in text, f"SKILL.md omits {flag}"
    assert "noni/direction/order.json" in text and "noni.order/1" in text
    for code in (0, 2, 3, 4):
        assert f"| `{code}` |" in text, f"SKILL.md's exit table omits order.py code {code}"
    for row in ORDERING_CHECKS:
        assert row in text, f"SKILL.md does not say how to repair a {row} row"
    assert text.count("\n") <= 400, f"SKILL.md is {text.count(chr(10))} lines; cap is 400"
    assert text.startswith("---") and "\ndescription:" in text, "SKILL.md has no frontmatter"


def test_skill_layout_includes_the_writer_and_its_executable_bit():
    """The skill's layout assertion knows about scripts/order.py, and the writer
    is executable like the other skill scripts."""
    assert (SKILL_DIR / "scripts" / "order.py").is_file()
    assert ORDER.stat().st_mode & 0o111, "order.py is not executable"
    layout = (REPO / "tests" / "test_skill_scrub.py").read_text(encoding="utf-8")
    assert "scripts/order.py" in layout, "test_skill_scrub.py does not assert order.py's presence"
    purity = (REPO / "tests" / "test_purity.py").read_text(encoding="utf-8")
    assert '"direction"' in purity, "test_purity.py does not scan the direction skill"
    assert "direction" in layout, "test_skill_scrub.py does not scan the direction skill"


def test_no_secrets_or_machine_local_paths_in_the_new_skill_and_fixture(tmp_path):
    """The scrub's own patterns, applied to the two new files by name: the gate
    that covers them is parametrised over SKILL_FILES, and a parametrisation
    that quietly stopped including a file would be invisible without this."""
    from public_safety import (  # noqa: E402  (registered by _harness)
        FIXTURE_HOME_PATH_PATTERNS,
        HOME_PATH_PATTERNS,
        SECRET_PATTERNS,
    )
    for path in (SKILL_DIR / "SKILL.md", ORDER, FIXTURE):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in (*HOME_PATH_PATTERNS, *FIXTURE_HOME_PATH_PATTERNS,
                                   *SECRET_PATTERNS):
                assert not pattern.search(line), f"{path.name}:{lineno}: {label}"


def test_the_census_skill_documents_the_three_new_classes():
    """The census's SKILL.md is the reader's only table for what a row means:
    each ordering class is documented, in the exit-code list and the --strict
    list alike, so a reader can act on a row without reading the script."""
    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    for row, code in zip(ORDERING_CHECKS, (15, 45, 46), strict=False):
        assert f"| `{row}` | {code} |" in text, f"census SKILL.md omits {row} at {code}"
        assert f"{code}  {row}" in text, f"census SKILL.md's exit table omits {row}"
    strict_line = next(row for row in text.splitlines()
                       if row.startswith("| `--strict`"))
    for row in ORDERING_CHECKS[1:]:
        assert f"`{row}`" in strict_line, f"--strict row omits {row}: {strict_line}"
    # The two new flags appear in the option table. Matched without backticks
    # because the table itself renders them bare, and a check that demanded one
    # spelling would fail on a doc that documents the flag perfectly.
    assert "--issue-state" in text and "--ordering" in text, "new flags undocumented"
    # Both defaults the table promises are the paths the census actually uses.
    assert "<repo>/noni/direction/order.json" in text, "the ordering default is undocumented"
