"""The decide skill's documents against the writer they describe.

Extracted from the decide writer suite: SKILL.md and the reference the writer is
held to."""

import re

from _harness import (
    DECIDE,
    REPO,
)


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


def test_the_decline_rule_matches_the_writers_open_chain_root():
    """references/modes.md's decline rule says what the writer does: a declined
    steer that is recorded at all is an open chain-root record, and a supersede
    needs every answer."""
    text = (
        REPO / "skills" / "steering-ledger" / "references" / "modes.md"
    ).read_text(encoding="utf-8")
    assert "chain-root record" in text, "modes.md must name the open chain-root form"
    assert "null" in text, "modes.md must state the null answer form"
