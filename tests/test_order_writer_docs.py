"""The order skill's documents against the writer that produced them.

Extracted from the order writer suite: SKILL.md, the reference, and the fixture
the census and the writer both read.

The two ``Usage:`` texts are part of that contract: the docstring block and the
four command lines of ``skills/direction/SKILL.md`` are what ``order --help``
must agree with (issue #77, AC1), so the positional reading of both lives in
``tests/order_usage_support.py`` and is asserted here next to the flag-set
parity this module already pinned. The rendered help itself is run by
``tests/test_order_writer_usage.py``, which compares it against these lines."""

from _harness import (
    ORDER,
    REPO,
)
from order_doc_readers import (
    SKILL_DIR,
    _doc_block,
    _doc_usage_flags,
    _docstring,
    _module_exit_codes,
    _order_ast,
    _parser_flags,
    _skill_section,
)
from order_fixtures import (
    FIXTURE,
    ORDERING_CHECKS,
)
from order_usage_support import (
    VERBS,
    assert_verb_precedes_flags,
    docstring_verb_lines,
    skill_md_verb_lines,
)

from noni import order_probe as _order_probe


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


def test_both_usage_texts_put_the_verb_before_the_flags():
    """The two documents spell the verb first, so the help has a form to match.

    ``test_docstring_usage_flags_match_the_parser`` compares flag *sets* and is
    indifferent to order, which is how the help drifted behind the flags while
    both pages stayed correct (issue #77). Each line of the docstring block and
    each command line of SKILL.md is read
    through the one reader the help is compared with, so the two halves of AC1
    cannot be checked against two different readings of a line. That reader also
    holds the count: one line per verb plus the second ``add`` line spelling the
    ``--item`` form, so a page that dropped or duplicated a verb fails here.
    """
    doc = docstring_verb_lines()
    assert len(doc) == 5, f"the docstring prints {len(doc)} verb lines: {doc}"
    pages = skill_md_verb_lines()
    assert len(pages) == 5, f"SKILL.md prints {len(pages)} verb lines: {pages}"

    for line in doc:
        assert_verb_precedes_flags(line, f"order.py docstring {line!r}")
    for line in pages:
        assert_verb_precedes_flags(line, f"skills/direction/SKILL.md {line!r}")

    # The two documents agree with each other on the verbs and on the flags
    # each verb takes, so a reader copying either line gets the same command.
    # The verb is the word each page prints straight after the ``--repo`` value,
    # which is the position AC1 puts it in on the help line too.
    def verbs(lines: list[str]) -> list[str]:
        out: list[str] = []
        for line in lines:
            words = line.split()
            out.append(words[words.index("REPO") + 1])
        return out

    # One verb per line, in document order, with ``add`` twice: the issue form and
    # the ``--item`` form of the same verb, which is why the two pages print five.
    assert verbs(doc) == [*VERBS[:1], *VERBS], verbs(doc)
    assert verbs(pages) == [*VERBS[:1], *VERBS], verbs(pages)
    for doc_line, page_line, verb in zip(doc, pages, (*VERBS[:1], *VERBS),
                                         strict=True):
        assert _doc_usage_flags(f"Usage:\n    {doc_line}") == \
            _doc_usage_flags(f"Usage:\n    {page_line}"), (
            f"the {verb} line differs between the docstring and SKILL.md: "
            f"{doc_line!r} vs {page_line!r}")


def test_docstring_names_the_refusals_the_code_performs():
    """The table is what a caller predicts a run's exit code from, so each
    refusal the code actually performs is named in it."""
    block = _doc_block(_docstring(_order_ast()), "Exit codes:")
    four = block[4].lower()
    for condition in ("already listed", "absent from the order", "no file under",
                      "superseded", "not the artifact", REFUSAL, FILE_REFUSAL):
        assert condition in four, f"the exit 4 row omits {condition!r}: {block[4]}"
    three = block[3].lower()
    for condition in ("not a regular file", "could not be written", "commit"):
        assert condition in three, f"the exit 3 row omits {condition!r}: {block[3]}"
    two = block[2].lower()
    for condition in ("positive integer", "--decision", "1-based", "iso-8601"):
        assert condition in two, f"the exit 2 row omits {condition!r}: {block[2]}"


# The refusal wording, spelled once: the product owns it in
# ``order_probe.CHANGED`` and this module checks the two documents against it.
REFUSAL = "the order changed since it was read; re-run"

# The second constant is asked of the product rather than copied: a doc that drifted
# to a near-miss of the wording the run actually prints would otherwise stay green.
assert _order_probe.CHANGED == REFUSAL, _order_probe.CHANGED
FILE_REFUSAL = _order_probe.FILE_CHANGED

# The guard's second cause, which the docs have to distinguish too: a moved HEAD is
# fixed by a re-run, a changed working file is not, and a page that named only the
# first would send the operator re-running a command that refuses forever.
FILE_REFUSAL = "the file changed since it was read; restore it or discard the change"


def _flat(text: str) -> str:
    """``text`` with every run of whitespace down to one space.

    The page wraps prose at its own width, so a pinned sentence arrives split across
    lines. Collapsing before the comparison keeps the check about the wording and
    not about where the author broke the line.
    """
    return " ".join(text.split())


def test_docstring_and_skill_md_name_the_concurrency_refusal_in_one_voice():
    """The exit-4 refusal a concurrent writer gets is pinned in all three places
    the caller reads it from: the wording the run prints, the docstring's exit 4
    row, and the SKILL.md table row.

    The phrase lives in the source constant ``order_probe.CHANGED``, so the product
    is asked rather than this module's copy of the string: a doc that drifted to a
    near-miss ("changed since read") would otherwise stay green while every ``in``
    check on a literal also passed. Each row is read from its own section rather
    than the whole file, so the sentence has to sit where a caller looking up exit 4
    finds it.
    """
    from noni import order_probe

    assert order_probe.CHANGED == REFUSAL, order_probe.CHANGED

    block = _doc_block(_docstring(_order_ast()), "Exit codes:")
    four = block[4]
    assert REFUSAL in four, f"the docstring's exit 4 row omits the refusal: {four}"
    for remedy in ("re-run", "committed"):
        assert remedy in four.lower(), f"the docstring's exit 4 row omits {remedy!r}: {four}"

    assert "freshness probe" in block[3].lower(), f"the exit 3 row omits the probe: {block[3]}"

    row = next(line for line in _skill_section("The exit codes").splitlines()
               if line.startswith("| `4` |"))
    for phrase in (REFUSAL, "re-run the same command", "committed"):
        assert phrase in row, f"SKILL.md's exit 4 row omits {phrase!r}: {row}"


def test_skill_md_states_the_refusal_where_its_writer_is_documented():
    """The prose a reader reaches for the concurrency question.

    The writing section has to carry the refusal, the exit code, and the re-run as
    the remedy; the edge cases carry what the guard is *not* (no lock, no merge) and
    the probe fault's exit 3. Reading per section is the point: a mention anywhere
    else on the page cannot stand in for the paragraph that documents the writer.

    The ``--no-commit`` exemption is the contract the two ``--no-commit`` tests pin
    (``test_no_commit_writes_the_file_and_moves_no_head`` and
    ``test_order_names_the_same_path_committed_and_uncommitted``): a reader who only
    read the exit-4 row would expect a concurrent writer to refuse that route too,
    and the flag paragraph is what tells them it runs no git at all.

    Each phrase is checked in the sentence that carries it rather than anywhere in
    the section, so a page that kept the six words and inverted the claim around
    them could not pass: the refusal wording, the code and the remedy have to sit in
    one sentence about the committed route, and the exemption's reason in the
    sentence about ``--no-commit``.
    """
    writing = _flat(_skill_section("Writing the order"))
    for phrase in (REFUSAL, "exit 4", "re-run", "exempt", "no git", "HEAD"):
        assert phrase in writing, f"the Writing the order section omits {phrase!r}"

    # The sentence a caller acts on: the refusal, its code, and the re-run as the
    # remedy, in one sentence rather than three unconnected mentions.
    remedy = [sentence for sentence in writing.split(". ")
              if REFUSAL in sentence and "re-run" in sentence]
    assert remedy, f"no single sentence names the refusal and its remedy: {writing}"
    assert "exit 4" in remedy[0], f"the remedy sentence omits the code: {remedy[0]}"
    exempt = [sentence for sentence in writing.split(". ") if "exempt" in sentence]
    assert exempt and "no git" in exempt[0], (
        f"the exemption is not explained by the route running no git: {exempt}")

    edge = _flat(_skill_section("The order edge cases that matter"))
    for phrase in (REFUSAL, "no lock", "re-run", "exit 3"):
        assert phrase in edge, f"the order edge cases omit {phrase!r}"


def test_skill_md_documents_the_writer_within_the_line_cap():
    """The skill documents order.py: its Usage, the four verbs, the artifact's
    two fields, the exit table, and the census rows a reader repairs with it."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/order.py" in text, "SKILL.md does not document the writer"
    for verb in ("add", "move", "remove", "confirm"):
        assert f"order.py {verb}" in text or f"`{verb}`" in text, f"SKILL.md omits {verb}"
    for flag in ("--decision", "--no-commit", "--now", "--at", "--to", "--why"):
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
    from public_safety import (
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
