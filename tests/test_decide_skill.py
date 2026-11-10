"""The decide skill's documents against the writer they describe.

Extracted from the decide writer suite: SKILL.md and the reference the writer is
held to.

The ``why`` rows of the two documents are pinned here against the number the product
states, and not against a number copied into this file: a page stating a bound the
owner no longer states tells an operator to write a value the writer refuses, and a
test holding its own copy of the figure cannot see that happen.
"""

import re

from _harness import (
    DECIDE,
    REPO,
)
from ledger_schema_fixtures import WHY_FIELD, WHY_MAX, product_why_max

# The two steering-ledger documents that carry the rationale's field row.
SKILL = REPO / "skills" / "steering-ledger" / "SKILL.md"
REFERENCES = REPO / "skills" / "steering-ledger" / "references" / "decisions.md"


def _field_rows(text: str, field: str) -> list[str]:
    """The table rows documenting ``field``, as the pages print them.

    Matched on the backticked name in the row's first cell rather than on any line
    mentioning the field, so prose about a rationale elsewhere on the page cannot
    stand in for the row a reader looks up.
    """
    return [line for line in text.splitlines()
            if line.lstrip().startswith(f"| `{field}` |")]


def test_skill_md_documents_the_writer_within_the_line_cap():
    """SKILL.md documents decide.py (Usage, supersede, the declined/open null
    form, the exit table) and stays inside the 400-line cap."""
    text = (REPO / "skills" / "steering-ledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/decide.py" in text, "SKILL.md does not document the writer"
    assert "--supersedes" in text and "--no-commit" in text
    assert "declin" in text.lower(), "SKILL.md must say a declined steer is an open record"
    assert text.count("\n") <= 400, f"SKILL.md is {text.count(chr(10))} lines; the cap is 400"
    for code in (0, 2, 3, 4, 5):
        assert f"| `{code}` |" in text, f"SKILL.md's exit table omits decide.py code {code}"


def test_skill_layout_includes_the_writer_and_its_executable_bit():
    """The skill's layout assertion knows about scripts/decide.py, and the
    writer is executable like census.sh and the other skill scripts."""
    assert (REPO / "skills" / "steering-ledger" / "scripts" / "decide.py").is_file()
    assert (DECIDE).stat().st_mode & 0o111, "decide.py is not executable"
    layout = (REPO / "tests" / "test_skill_scrub.py").read_text(encoding="utf-8")
    assert "scripts/decide.py" in layout, "test_skill_scrub.py does not assert decide.py's presence"


def test_no_doc_still_states_the_answer_absent_form():
    """Every doc that stated the answer-absent form now states the null form.

    The stale wording is a claim about the record ("`answer` absent", "the
    answer absent"), not any sentence containing the words: a ValueError that
    says a verdict "must carry no answer" is about the verdict, not the ledger
    shape. The negative control below pins that the probe is not vacuous — if
    the pattern ever stops matching the wording it exists to catch, this test
    fails too.
    """
    checked = [
        REPO / "skills" / "steering-ledger" / "SKILL.md",
        REPO / "skills" / "steering-ledger" / "references" / "decisions.md",
        REPO / "skills" / "steering-ledger" / "references" / "modes.md",
        REPO / "integrations" / "README.md",
        REPO / "integrations" / "github-issues" / "README.md",
        REPO / "integrations" / "adapter_protocol.py",
    ]
    stale = re.compile(
        r"`answer` (?:is )?absent|\banswer absent\b|the answer absent|"
        r"with (?:no|absent) answer",
        re.IGNORECASE,
    )
    for path in checked:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            assert not stale.search(line), f"{path.relative_to(REPO)}:{lineno}: {line.strip()}"
        if path.suffix == ".md":
            assert "null" in text, f"{path.relative_to(REPO)} never states the null form"
    # The probe bites the wording it was written for.
    for wording in (
        "every question's `answer` absent",
        "persisted with answer absent and status open",
        "persisted as status: open with the answer absent",
        "persisted as status: open with no answer",
    ):
        assert stale.search(wording), f"the probe no longer catches {wording!r}"


def test_the_skill_pages_state_the_rationale_bound_the_product_states():
    """Every doc claim about the ``why`` bound reads the number from the product.

    Each page must state ``str(WHY_MAX)`` next to the field's own row, and none of
    them may hold a *different* three-figure bound: the check is that the number on
    the page is the number ``_why`` owns, so widening the bound reddens the
    pages that pin their claim to it instead of leaving them to be discovered.
    """
    bound = str(WHY_MAX)
    for path in (SKILL, REFERENCES):
        text = path.read_text(encoding="utf-8")
        rows = _field_rows(text, WHY_FIELD)
        assert rows, f"{path.relative_to(REPO)} prints no `{WHY_FIELD}` field row"
        joined = "\n".join(rows)
        assert bound in joined, (
            f"{path.relative_to(REPO)}: the `{WHY_FIELD}` row must state the bound "
            f"{bound} the product states: {joined}")
        # No page carries a second bound for the same field: a stale number beside the
        # live one is the shape of this assertion, and it reads as a typo until a run
        # refuses a reason the doc told somebody to write.
        stale = [found for found in re.findall(r"\b\d{3}\b", joined)
                 if found != bound]
        assert not stale, (
            f"{path.relative_to(REPO)}: the `{WHY_FIELD}` row states {stale} beside "
            f"the product's bound {bound}")
    # The bound is the product's, read here rather than compared to a literal: this
    # assertion is what reddens when the owner moves and a page keeps the old number.
    from noni._why import WHY_MAX as owner

    assert owner == WHY_MAX == int(bound)


def test_no_page_outside_the_docs_that_pin_the_bound_states_it(tmp_path):
    """A rationale bound belongs on the pages that name its owner and nowhere else.

    The two steering-ledger pages and the direction skill state the number because
    their field rows and their ``add --why`` paragraph claim it; every other page that
    mentioned it would be a fourth copy no test reads back. The tree is walked rather
    than a list of pages, so a doc added later is caught by the rule and not by
    whoever remembered to add it here.
    """
    owner = str(product_why_max())
    allowed = {SKILL.relative_to(REPO).as_posix(),
               REFERENCES.relative_to(REPO).as_posix(),
               (REPO / "skills" / "direction" / "SKILL.md").relative_to(REPO).as_posix()}
    offenders = []
    for path in sorted(REPO.rglob("*.md")):
        rel = path.relative_to(REPO).as_posix()
        if rel in allowed or any(part in {".git", ".venv", "node_modules"}
                                 for part in path.parts):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if f"{owner}-character" in line or f"of at most {owner} characters" in line:
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, (
        f"the rationale bound {owner} is stated by pages that pin nothing to it: "
        f"{offenders}")


def test_the_skill_documents_the_why_flag_and_its_exit_two_refusal():
    """``--why`` is documented where the writer's contract is read: the Usage block,
    the exit-2 clause that names it, and the paragraph that states the rule.

    The exit table is what an operator consults when a run answers 2, so a flag the
    table omits leaves them with a code and no cause. The clause is matched on the
    flag inside the row for code 2 and not on the word anywhere in the file.
    """
    text = SKILL.read_text(encoding="utf-8")
    assert f"[--{WHY_FIELD} REASON]" in text, "SKILL.md's Usage omits --why"
    exit_two = [line for line in text.splitlines() if line.lstrip().startswith("| `2` |")]
    assert len(exit_two) == 1, exit_two
    assert f"--{WHY_FIELD}" in exit_two[0], (
        f"SKILL.md's exit-2 row does not name --{WHY_FIELD}: {exit_two[0]}")
    for phrase in ("non-empty single line", "code points"):
        assert phrase in "\n".join(_field_rows(text, WHY_FIELD)), (
            f"SKILL.md's `{WHY_FIELD}` row must state the rule ({phrase})")


def test_the_reference_documents_the_rationale_and_the_target_refusal():
    """The field reference says what the field is, what refuses it and at which code,
    including the exit-4 posture a ``--supersedes`` target carrying a bad ``why``
    takes -- the refusal no page but this one states.

    Asserted as phrases and not as a paragraph, so the wording may be improved
    without reddening the pin, while a dropped rule cannot go unnoticed.
    """
    text = REFERENCES.read_text(encoding="utf-8")
    row = "\n".join(_field_rows(text, WHY_FIELD))
    for phrase in ("single-line", "code points", "exit 2", "exit 10", "exit 4",
                   f"`{WHY_FIELD}", "`_why.WHY_MAX`"):
        assert phrase in row, (
            f"references/decisions.md: the `{WHY_FIELD}` row omits {phrase!r}: {row}")


def test_the_decline_rule_matches_the_writers_open_chain_root():
    """references/modes.md's decline rule says what the writer does: a declined
    steer that is recorded at all is an open chain-root record, and a supersede
    needs every answer."""
    text = (
        REPO / "skills" / "steering-ledger" / "references" / "modes.md"
    ).read_text(encoding="utf-8")
    assert "chain-root record" in text, "modes.md must name the open chain-root form"
    assert "null" in text, "modes.md must state the null answer form"
