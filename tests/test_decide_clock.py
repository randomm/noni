"""The instant a no-``--date`` decide run stamps its ``date`` field with.

Split from ``test_decide_record.py`` for the 500-line source cap, at the same seam
that split ``src/noni/decide.py`` from ``src/noni/_decide_flags.py``. Every other
decide file in the suite passes ``--date``; the runs here carry none, so the instant
the writer reads from its clock is the only thing deciding both the id's day and the
field's stamp.

The bug this pins: with no ``--date`` every record was stamped ``T00:00:00Z``, so
records filed on one day were indistinguishable and the brief's newest-first block had
no order between them to read.

Two routes, because the two halves of the promise differ. A launched run has no clock
a test may move -- the instant comes from the system clock, which the writer reads and
cannot refuse -- so the launched case asserts the SHAPE of what landed and nothing about
the second it fell on. Moving the clock is an in-process matter:
:func:`noni._decide_flags.run_instant` is the one function the writer reads, so
``noni.decide.main`` is driven twice with it patched, which writes two records through
the real writer at two instants, and the order that stamp buys is read where the product
publishes it: the brief's ``recent decisions`` block.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

from _harness import _git, git_pin_date
from brief_fixtures import NOW, run_brief
from brief_support import rows
from decide_fixtures import (
    ANSWERED,
    BASE,
    NEW_DATE,
    OPTIONS,
    QUESTION,
    _assert_both_censuses_clean,
    _baseline_repo,
    _pin_identity,
    _read,
    _run,
)

from noni import _decide_flags
from noni import brief as brief_module
from noni import decide as writer

# The shape a stamped ``date`` must have, and nothing more. A shape rather than a value
# the test chose: the launched writer reads the wall clock, and an assertion against a
# wall-clock value is a test that fails at midnight UTC.
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# The instants of the two in-process runs, one second apart on the suite's pinned day.
# The census and the brief call beside them is pinned to ``brief_fixtures.NOW``, a later
# stamp on that same day, so neither reads either record as future-dated.
EARLIER = f"{NEW_DATE}T09:00:00Z"
LATER = f"{NEW_DATE}T09:00:01Z"

# The id slugs of the records the two in-process runs write.
FIRST_SLUG = "first"
SECOND_SLUG = "second"


def _written_at(repo, slug: str, monkeypatch, instant: str) -> dict:
    """Write one record through the real writer with its clock at ``instant``.

    The clock is patched where the writer looks the name up -- the helper module's own
    globals -- because :func:`noni._decide_flags.run_instant` is the single seam that
    decides both the id's day and the field's stamp, and ruling 2 allows no other.

    ``decide.main`` is driven here rather than launched because a launched process reads
    this process's patched function only if the patch is in its environment, and ruling 2
    rules that out: no variable sets a record's date. No ``--date`` is passed at all, so
    the clock is the only answer either half of the record can have. Both runs of a
    pair are made with ``--no-commit`` so the pair can be landed by one commit (see
    :func:`_commit_written`).
    """
    monkeypatch.setattr(_decide_flags, "run_instant", lambda: instant)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = writer.main(["--repo", str(repo), "--slug", slug, "--no-commit",
                            *BASE, *QUESTION, *OPTIONS, *ANSWERED])
    assert code == 0, err.getvalue()
    return _read(repo, f"{instant[:10]}-{slug}")


def _printed_decision_ids(out: str) -> list[str]:
    """The ids the ``recent decisions`` block printed, in the order it printed them."""
    return [line.split(":", 1)[0]
            for line in rows(out, brief_module.RECENT_DECISIONS_HEADER)]


def test_a_run_with_no_date_stamps_the_instant_it_ran_at(tmp_path):
    """The field is a full UTC second, and the name it sits in stays date-only.

    One clock reading answers both halves of the record, so the launched case asserts
    the SHAPE of the answer and the relation between the two halves: the field matches
    the second-resolution form, and the id is that field's day plus the slug. Both
    censuses are clean afterwards -- a stamped second is a date the schema accepts."""
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    # The record's name is the instant's day, which no test may assume. The file on
    # disk is the answer, read by the name the writer printed: both halves of one
    # record -- its name and its field -- come from the same clock reading, and that
    # relation, not the host's wall clock, is what is asserted.
    wrote = [line for line in proc.stdout.splitlines() if "wrote " in line]
    assert len(wrote) == 1, proc.stdout
    record_path = Path(wrote[0].split("wrote ", 1)[1].split(",")[0])
    assert record_path.is_file(), proc.stdout
    new_id = record_path.name[: -len(".json")]
    record = _read(repo, new_id)
    assert INSTANT_RE.match(record["date"]), record["date"]
    # ``--date`` was absent, so nothing pinned the day: the id is the instant's day and
    # its slug, with no time in it. The field is a full second, not a day.
    assert new_id == f"{record['date'][:10]}-scheduler"
    assert record["status"] == "decided"
    _assert_both_censuses_clean(repo, "a no-date record stamped to the second")


def _commit_written(repo) -> None:
    """Commit what the in-process runs left staged, under the day their records name.

    A run that committed its own record would leave the second one standing to the
    census as an edit made after a commit, so the pair is landed once, here. ``git
    commit --only`` is the form the writer itself uses, so the commit carries these
    paths and nothing else. The pinned stamp is the records' own day, so no census call
    can be told a file was touched on a day that file does not claim.
    """
    _git(repo, "add", "--", "noni/decisions")
    git_pin_date(repo, f"{NEW_DATE}T00:00:00Z", "commit", "-q", "-m",
                 "steering: clock", "--only", "--", "noni/decisions")


def test_two_runs_of_one_instant_keep_the_id_tiebreak(tmp_path, monkeypatch):
    """A clock read at the same second does not make one record of two runs.

    The companion to the ordering fix: stamping to the second only orders records that
    were written apart. Two runs the clock cannot tell apart must still land as two
    records with one order between them, and the page has to print that order: of two
    equal instants the higher id prints first -- the tiebreak the block documents, and
    the one every record dated by ``--date`` still relies on."""
    repo = _baseline_repo(tmp_path)
    _pin_identity(repo, "Replay")
    one = _written_at(repo, FIRST_SLUG, monkeypatch, LATER)
    two = _written_at(repo, SECOND_SLUG, monkeypatch, LATER)
    _commit_written(repo)
    # One instant, two records: the field is shared, the names are not.
    assert one["date"] == two["date"] == LATER
    assert one["id"] != two["id"]
    _assert_both_censuses_clean(repo, "two records stamped at one instant")
    printed = [record_id for record_id in _printed_decision_ids(
        run_brief(repo, "--now", NOW)[1]) if record_id.startswith(NEW_DATE)]
    assert printed == [two["id"], one["id"]]


def test_the_record_written_later_prints_first(tmp_path, monkeypatch):
    """The ordering the instant buys, asserted where the instant is published.

    Two real writes by the real writer, the clock moved between them by the one function
    the writer reads. The earlier record is given the HIGHER id, so a reader that ordered
    by name -- or a writer that stamped both records at midnight, which is the bug --
    puts the wrong one on top. The brief is the consumer of the stamp, so the brief is
    what says which order the writer's instant produced."""
    repo = _baseline_repo(tmp_path)
    _pin_identity(repo, "Replay")
    earlier = _written_at(repo, SECOND_SLUG, monkeypatch, EARLIER)
    later = _written_at(repo, FIRST_SLUG, monkeypatch, LATER)
    _commit_written(repo)
    # Write order and name order disagree on purpose, so the assertion below cannot pass
    # by the id happening to sort the same way the instant does.
    assert earlier["id"] > later["id"]
    assert earlier["date"] == EARLIER and later["date"] == LATER
    _assert_both_censuses_clean(repo, "two records written at two instants")
    printed = [record_id for record_id in _printed_decision_ids(
        run_brief(repo, "--now", NOW)[1]) if record_id.startswith(NEW_DATE)]
    assert printed == [later["id"], earlier["id"]]
