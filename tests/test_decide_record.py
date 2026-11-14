"""A record written by decide.py is valid where the census reads it.

Extracted from the decide writer suite: the smallest case, and the one every
other file in the suite assumes."""

from _harness import (
    _git_e2,
)
from decide_fixtures import (
    ANSWERED,
    BASE,
    NEW_DATE,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _assert_both_censuses_clean,
    _baseline_repo,
    _decide,
    _head_paths,
    _porcelain,
    _read,
    _record_path,
    _run,
)


def test_writes_a_decided_record_and_commits_only_that_path(tmp_path):
    """A fully answered run writes one valid record, commits exactly that path
    with 'steering: <id>', and both censuses are clean afterwards."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    assert str(_record_path(repo, NEW_ID)) in proc.stdout, proc.stdout

    record = _read(repo, NEW_ID)
    assert record["id"] == NEW_ID
    # The run passed --date, so the field is that day at UTC midnight and the id
    # stays date-only: the day is the whole of what the flag asserted.
    assert record["date"] == f"{NEW_DATE}T00:00:00Z"
    assert record["status"] == "decided"
    assert record["questions"][0]["answer"] == "next train"
    assert record["supersedes"] is None
    assert set(record) == {
        "id", "date", "asked_by", "questions", "by", "scope", "status", "supersedes"
    }
    # by is git's configured identity, not a value the caller supplied.
    assert record["by"] == "Replay"
    assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"]
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == f"steering: {NEW_ID}", subject
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "writing a decided record")


def test_unanswered_question_is_open_with_a_null_answer(tmp_path):
    """No --answer gives status open and writes the answer as null, not an
    absent key: the null form is the documented answer-absent shape."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo)
    assert proc.returncode == 0, proc.stderr

    record = _read(repo, NEW_ID)
    assert record["status"] == "open"
    question = record["questions"][0]
    assert "answer" in question, "the open form writes answer: null, it does not omit the key"
    assert question["answer"] is None
    # A partly answered record is open too, and the answered question keeps
    # its answer: status is derived from the set, never supplied.
    _assert_both_censuses_clean(repo, "writing an open record")


def test_partially_answered_record_is_open(tmp_path):
    """One answered and one unanswered question give open, with the answered
    question keeping its answer and the other carrying null."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo,
        "--slug", "two-questions",
        "--date", NEW_DATE,
        *BASE,
        *QUESTION, *OPTIONS, *ANSWERED,
        "--question", "q2=Who reviews it?",
        "--option", "q2=the operator", "--option", "q2=nobody",
    )
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, f"{NEW_DATE}-two-questions")
    assert record["status"] == "open"
    by_id = {q["id"]: q for q in record["questions"]}
    assert by_id["q1"]["answer"] == "next train"
    assert by_id["q2"]["answer"] is None
    _assert_both_censuses_clean(repo, "writing a partly answered record")


def test_source_provenance_is_written_when_both_flags_are_given(tmp_path):
    """The optional source field carries the tracker's issue and comment ids
    when both flags name them, and stays absent when neither does."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--source-issue", "42", "--source-comment", "9102")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["source"] == {"issue_number": 42, "comment_id": 9102}
    _assert_both_censuses_clean(repo, "writing a record with source provenance")


def test_source_with_only_one_flag_is_a_usage_error(tmp_path):
    """Half a provenance is refused before anything is written: a source with
    one of its two integers would fail the census."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--source-issue", "42")
    assert proc.returncode == 2, proc.stderr
    assert "both" in proc.stderr.lower()
    assert not _record_path(repo, NEW_ID).exists()
