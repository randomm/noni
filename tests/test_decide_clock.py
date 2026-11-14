"""The instant a no-``--date`` decide run stamps its ``date`` field with.

Split from ``test_decide_record.py`` for the 500-line source cap, at the same seam
that split ``src/noni/decide.py`` from ``src/noni/_decide_flags.py``. Every other
decide file in the suite passes ``--date``; the runs here carry none, so the
instant the writer reads from its clock seam is the only thing that decides both
the id's day and the field's stamp.

The bug this pins: with no ``--date`` every record was stamped ``T00:00:00Z``, so
records filed on one day were indistinguishable and the brief's newest-first block
had no order between them to read.

The clock comes from the writer's own seam (``noni._decide_flags.CLOCK_ENV_VAR``)
rather than the host wall clock, so the day and the second asserted here are values
the test chose -- the same reason every census call in the suite is pinned.
"""

from decide_fixtures import (
    ANSWERED,
    BASE,
    NEW_DATE,
    NEW_ID,
    OPTIONS,
    QUESTION,
    RUN_INSTANT,
    _assert_both_censuses_clean,
    _baseline_repo,
    _clock_env,
    _read,
    _run,
)


def test_a_run_with_no_date_stamps_the_instant_it_ran_at(tmp_path):
    """The field is a full UTC second, and the name it sits in stays date-only.

    One clock reading answers both halves of the record: the seam's instant goes in
    ``date`` and its first ten characters are the day the id and the filename carry,
    so a record cannot be named for one day and dated another. Both censuses are
    clean afterwards -- a stamped second is a date the schema accepts."""
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                env=_clock_env())
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["date"] == RUN_INSTANT
    # ``--date`` was absent, so nothing pinned the day: the id is the instant's day
    # and its slug, with no time in it. The field is a full second, not a day.
    assert record["id"] == NEW_ID == f"{RUN_INSTANT[:10]}-scheduler"
    assert len(record["date"]) == len(RUN_INSTANT) and record["date"].endswith("Z")
    assert record["status"] == "decided"
    _assert_both_censuses_clean(repo, "a no-date record stamped to the second")


def test_two_runs_of_one_instant_keep_the_id_tiebreak(tmp_path):
    """A clock read at the same second does not make one record of two runs.

    The companion to the ordering fix: stamping to the second only orders records
    that were written apart. Two runs the clock cannot tell apart must still land as
    two records with one order between them, which is what the id's slug is for."""
    repo = _baseline_repo(tmp_path)
    first = _run(repo, "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                 env=_clock_env())
    assert first.returncode == 0, first.stderr
    second = _run(repo, "--slug", "follow-up", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                  env=_clock_env())
    assert second.returncode == 0, second.stderr
    one = _read(repo, NEW_ID)
    two = _read(repo, f"{RUN_INSTANT[:10]}-follow-up")
    # One instant, two records: the field is shared, the names are not.
    assert one["date"] == two["date"] == RUN_INSTANT
    assert one["id"] != two["id"]
    _assert_both_censuses_clean(repo, "two records stamped at one instant")


def test_an_unreadable_clock_refuses_the_run(tmp_path):
    """A clock the seam cannot read stops the write instead of dating it midnight.

    The fail-closed rule: a record stamped ``T00:00:00Z`` after a clock nobody read
    claims a time the run never observed. So the refusal is a usage error, printed
    before the git probes, and the ledger is left exactly as it was found."""
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                env=_clock_env(None))
    assert proc.returncode == 2, proc.stderr
    assert "clock" in proc.stderr.lower()
    assert not (repo / "noni" / "decisions" / f"{NEW_DATE}-scheduler.json").exists()
    _assert_both_censuses_clean(repo, "a run refused at an unreadable clock")
