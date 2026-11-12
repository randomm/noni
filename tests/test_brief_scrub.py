"""The brief suite: a record whose bytes are hostile, and the reader called directly.

Split from ``test_brief_page.py`` for the 500-line source cap (the same seam that split
``src/noni/brief.py`` from ``src/noni/brief_page.py``): the page cases assert what a screen
prints, and these two ask what the page refuses to print -- the bytes a record carries that
must not reach a terminal, and the three numbers the decisions reader is defined by when a
test drives it instead of reading them off a page.

The page readers and the planters are the suite's shared ones, so a case here is about the
same planted tree every other brief case uses.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    RECORD_ID,
    ledger_dir,
    plant_brief_tree,
    record_document,
    run_brief,
    write_record,
)
from brief_support import rows

from noni import brief as brief_module
from noni import ledger_schema


def test_brief_a_record_of_control_bytes_is_scrubbed_before_it_prints(
        tmp_path: Path) -> None:
    """A hostile question and reason reach the screen scrubbed, not raw.

    The page's own scrub is what stands between a record's bytes and a terminal, so the case
    plants the two shapes that matter: an escape sequence that would move the cursor or clear the
    screen, and a machine-local absolute path that the page promises never to print. Neither
    survives, and the row still carries the words around them.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document(
        "2026-10-25-hostile", "2026-10-25T00:00:00Z",
        question="Ship\x1b[2J from /home/someone/build?", answer="yes",
        why="\x07because of /home/someone/secret"))
    out = run_brief(root, "--now", NOW)[1]
    assert "\x1b" not in out and "\x07" not in out
    assert "/home/someone" not in out
    row = rows(out, brief_module.RECENT_DECISIONS_HEADER)[0]
    assert "<path>" in row
    assert "Ship" in row and "from" in row and "yes" in row


def test_brief_the_decisions_reader_answers_its_own_three_questions(
        tmp_path: Path) -> None:
    """The reader's live filter, its cap and its order, called directly.

    The page cases above reach the reader through a launched run, which is the route the operator
    has; this drives the function itself, so the three numbers the block is defined by -- which
    statuses it prints, how many rows it keeps, what order it keeps them in -- are pinned where
    they are decided rather than inferred from a screen.
    """
    from noni import brief_page

    # The writer-shaped tree the page reads: ``write_record`` plants under ``<root>/noni/decisions``
    # because that is the path the block reaches through ``--repo``, and the reader is handed the
    # ledger directory the state root would hold.
    for record_id, (date, status) in {
            "a": ("2026-10-01T00:00:00Z", ledger_schema.STATUS_DECIDED),
            "b": ("2026-10-02T00:00:00Z", ledger_schema.STATUS_SUPERSEDED),
            "c": ("2026-10-03T00:00:00Z", ledger_schema.STATUS_OPEN),
            "d": ("2026-10-04T00:00:00Z", ledger_schema.STATUS_DECIDED)}.items():
        write_record(tmp_path / "seed", record_document(record_id, date, status=status))
    rows, withheld = brief_page.decision_rows(ledger_dir(tmp_path / "seed"), cap=1)
    assert rows == ["d: Ship the candidate?: yes"]
    # One live record fitted the cap and the other cost the block its count line; the superseded
    # and open records were never live, so they cost nothing at all.
    assert withheld == 1



