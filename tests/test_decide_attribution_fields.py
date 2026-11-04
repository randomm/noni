"""The three optional attribution/marker fields, as the writer and censuses agree.

``decided_by`` and ``on_behalf_of`` say who made a decision and who it was made
for; ``single_option`` is the marker that lets a question carry exactly one
option. Each is optional, so a run that passes none of the three writes
byte-for-byte the eight-field record every other test in the suite assumes --
that is the backward-compatibility claim these tests exist for.

The three entry points have to agree or a record gets committed that the census
then reports at exit 10: the writer (which refuses a bad name at the flag), the
Python census's ledger-record pass, and census.sh's jq program. Every case
here is asserted against both censuses.
"""

import json

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
    _census_py,
    _census_sh,
    _decide,
    _head_paths,
    _porcelain,
    _read,
    _record_path,
    _run,
)

DECIDED_BY = "--decided-by"
BEHALF = "--on-behalf-of"
SINGLE = "--single-option"


def _one_option_run(repo, slug, *extra):
    """A run whose single question carries exactly one option."""
    return _run(
        repo, "--slug", slug, "--date", NEW_DATE, *BASE,
        "--question", "q1=Ship the release now?",
        "--option", "q1=ship it", "--answer", "q1=ship it", *extra)


def test_no_optional_flag_writes_the_eight_field_record(tmp_path):
    """The compatibility claim: with none of the three flags the record holds
    exactly the eight required fields, in the order the supersede canonical-form
    rule compares a target's committed bytes against."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert list(record) == ["id", "date", "asked_by", "questions", "by",
                            "scope", "status", "supersedes"]
    for name in ("decided_by", "on_behalf_of", "single_option"):
        assert name not in record, f"{name} was written without its flag"


def test_decided_by_is_written_beside_by_and_never_overrides_it(tmp_path):
    """``by`` stays git's identity and ``decided_by`` records who the flags said:
    the census reports ``by`` from git, so a flag cannot claim an authorship."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, DECIDED_BY, "operator-ann")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["decided_by"] == "operator-ann"
    assert record["by"] == "Replay", "the flag must not overwrite the git identity"
    assert list(record)[-1] == "decided_by", "optional fields are appended last"
    assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"]
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "a record naming who decided")


def test_on_behalf_of_is_written_with_its_decided_by(tmp_path):
    """The pair is written together, appended after ``decided_by`` in that order,
    so the record reads: this person decided, for this party."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, DECIDED_BY, "delegate-bot", BEHALF, "operator-ann")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["decided_by"] == "delegate-bot"
    assert record["on_behalf_of"] == "operator-ann"
    assert list(record)[-2:] == ["decided_by", "on_behalf_of"]
    _assert_both_censuses_clean(repo, "a record naming who it was decided for")


def test_on_behalf_of_without_decided_by_is_a_usage_error(tmp_path):
    """The pairing is the writer's rule: a record naming the party a decision was
    made for must also name who made it, and nothing is written for the refusal."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, BEHALF, "operator-ann")
    assert proc.returncode == 2, proc.stderr
    assert "--decided-by" in proc.stderr, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()
    assert _porcelain(repo) == ""


def test_an_empty_or_blank_name_is_a_usage_error(tmp_path):
    """A name that is empty or only whitespace names nobody, so it is refused at
    the flag rather than committed as a record the census reports at exit 10."""
    repo = _baseline_repo(tmp_path)
    for value in ("", "   "):
        proc = _decide(repo, *ANSWERED, DECIDED_BY, value)
        assert proc.returncode == 2, f"{value!r}: {proc.returncode} {proc.stderr}"
        assert "--decided-by" in proc.stderr, proc.stderr
        assert not _record_path(repo, NEW_ID).exists()


def test_a_name_carrying_a_line_break_is_a_usage_error(tmp_path):
    """The single-line rule is the census's own, so a name cannot smuggle a second
    line into a report: every break json can put in a string is refused, including
    the three json writes raw rather than escaping."""
    repo = _baseline_repo(tmp_path)
    for flag, value in ((DECIDED_BY, "ops\nlead"),
                        (DECIDED_BY, "ops\rlead"),
                        (DECIDED_BY, "ops\x85lead"),
                        (DECIDED_BY, "ops\u2028lead"),
                        (DECIDED_BY, "ops\u2029lead"),
                        (BEHALF, "ops\nlead")):
        proc = _decide(repo, *ANSWERED, DECIDED_BY, "who", flag, value)
        assert proc.returncode == 2, f"{value!r}: {proc.returncode} {proc.stderr}"
        assert "single line" in proc.stderr, proc.stderr
        assert not _record_path(repo, NEW_ID).exists()


def test_a_name_may_carry_spaces_and_punctuation(tmp_path):
    """Only a break or emptiness is refused: a real name with a space, a dot or a
    dash is what the flag is for, and the census reads it back unchanged."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, DECIDED_BY, "Dr. A. Reyes", BEHALF, "release team")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["decided_by"] == "Dr. A. Reyes"
    assert record["on_behalf_of"] == "release team"
    _assert_both_censuses_clean(repo, "a name with spaces and punctuation")


def test_single_option_allows_one_option_and_writes_the_marker(tmp_path):
    """With the flag a question may carry exactly one option, and the marker is
    written as the JSON true literal so both censuses relax the lower bound."""
    repo = _baseline_repo(tmp_path)
    proc = _one_option_run(repo, "one-way", SINGLE)
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, f"{NEW_DATE}-one-way")
    assert record["single_option"] is True, record
    assert record["questions"][0]["options"] == ["ship it"]
    _assert_both_censuses_clean(repo, "a single-option record")


def test_one_option_without_the_marker_is_a_usage_error(tmp_path):
    """The discriminator is the marker, not the content: a one-option question
    without the flag is refused rather than guessed to be intentional."""
    repo = _baseline_repo(tmp_path)
    proc = _one_option_run(repo, "one-way")
    assert proc.returncode == 2, proc.stderr
    assert "--single-option" in proc.stderr, proc.stderr
    assert not _record_path(repo, f"{NEW_DATE}-one-way").exists()


def test_single_option_may_still_carry_two_to_four_options(tmp_path):
    """The flag relaxes the lower bound only, and a marked record still needs a
    question the marker speaks for: an ordinary multiple-choice record written with
    the flag is refused, because nothing in it was asked with one option."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, SINGLE)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "--single-option" in proc.stderr, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()
    assert _porcelain(repo) == ""
    # The same record without the flag is what it always was: a clean 2-4 form.
    assert _decide(repo, *ANSWERED).returncode == 0
    _assert_both_censuses_clean(repo, "a two-option record with no marker")


def test_a_marker_no_question_earns_is_malformed_to_both_censuses(tmp_path):
    """The record-side of the same rule, planted rather than flagged: a record
    carrying the marker whose questions all hold 2-4 options is a malformed record
    (exit 10) in both censuses, naming the marker.

    The writer refuses the shape at the flag, so the only way it reaches a ledger
    is a hand edit. Both entry points must answer it: the marker claims a
    one-option question and the record does not show one.
    """
    repo = _baseline_repo(tmp_path)
    record = _baseline_record()
    record["id"] = f"{NEW_DATE}-unearned-marker"
    record["single_option"] = True
    _planted(repo, record)
    for name, census in (("census.py", _census_py), ("census.sh", _census_sh)):
        _code, err = census(repo)
        assert _code == 10, f"unearned marker via {name}: {_code} {err}"
        assert "single_option" in err, f"unearned marker via {name}: {err}"


def test_single_option_mixes_one_option_and_multi_option_questions(tmp_path):
    """The bound is judged per question, so one record may ask a decided
    one-option question and an open multiple-choice one."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "mixed", "--date", NEW_DATE, *BASE,
        "--question", "q1=Ship now?", "--option", "q1=ship it", "--answer", "q1=ship it",
        "--question", "q2=Who reviews?", "--option", "q2=the operator",
        "--option", "q2=nobody", SINGLE)
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, f"{NEW_DATE}-mixed")
    by_id = {q["id"]: q for q in record["questions"]}
    assert by_id["q1"]["options"] == ["ship it"]
    assert by_id["q2"]["options"] == ["the operator", "nobody"]
    assert record["status"] == "open"
    _assert_both_censuses_clean(repo, "a record mixing a one-option question")


def test_a_raw_unicode_separator_in_a_name_is_refused_by_both_censuses(tmp_path):
    """The three breaks json writes into the bytes unescaped (U+0085, U+2028,
    U+2029) are the ones a hand-edited record can carry while still being one JSON
    string, so they are the case the single-line rule exists for: the census that
    only splits on the escaped \\n would read the value as one line and report it as
    one line, which is the smuggle the rule refuses."""
    repo = _baseline_repo(tmp_path)
    for separator in ("\x85", "\u2028", "\u2029"):
        record = _baseline_record()
        record["id"] = f"{NEW_DATE}-raw-{ord(separator):x}"
        record["decided_by"] = f"a{separator}b"
        path = _planted(repo, record, raw=True)
        assert path.read_bytes().count(separator.encode("utf-8")) == 1, \
            "the fixture escaped the separator, so it probed nothing"
        for name, census in (("census.py", _census_py), ("census.sh", _census_sh)):
            _code, err = census(repo)
            assert _code == 10, f"U+{ord(separator):04X} via {name}: {_code} {err}"
            assert "decided_by" in err, f"U+{ord(separator):04X} via {name}: {err}"


def _planted(repo, record, raw=False):
    """Commit ``record`` as a hand-written ledger file, bypassing the writer, so
    the census is asked about a shape the writer would never produce.

    ``raw`` writes with ``ensure_ascii=False``, which is how a separator lands in
    the bytes unescaped: json escapes the short controls (so ``\\n`` never appears
    raw) and writes these three through, which is the whole reason the single-line
    rule is not just a check for a newline.
    """
    path = repo / "noni" / "decisions" / f"{record['id']}.json"
    text = json.dumps(record, indent=2, ensure_ascii=not raw) + "\n"
    path.write_text(text, encoding="utf-8")
    _git_e2(repo, "add", "--", str(path.relative_to(repo)))
    _git_e2(repo, "commit", "-q", "-m", "planted")
    return path


def _baseline_record():
    return {
        "id": f"{NEW_DATE}-planted",
        "date": f"{NEW_DATE}T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Ship?", "options": ["yes", "no"],
                       "answer": "yes"}],
        "by": "Replay",
        "scope": "release",
        "status": "decided",
        "supersedes": None,
    }


def test_a_malformed_new_field_reports_the_ledger_record_class(tmp_path):
    """A hand-edited record carrying a bad value at one of the new keys is a
    ledger-record failure (10) in both censuses, naming the field. No new census
    code was added for these fields, so both entry points answer 10."""
    repo = _baseline_repo(tmp_path)
    for field, value, phrase in (("decided_by", 7, "decided_by"),
                                 ("on_behalf_of", "", "on_behalf_of"),
                                 ("single_option", False, "single_option")):
        record = _baseline_record()
        record["id"] = f"{NEW_DATE}-planted-{field}-{type(value).__name__}"
        record[field] = value
        _planted(repo, record)
        for name, census in (("census.py", _census_py), ("census.sh", _census_sh)):
            _code, err = census(repo)
            assert _code == 10, f"{field}={value!r} via {name}: {_code} {err}"
            assert phrase in err, f"{field}={value!r} via {name}: {err}"


def test_the_censuses_do_not_enforce_the_pairing(tmp_path):
    """The pairing is the writer's rule only: a hand-edited record naming the
    party without naming who decided is well formed to both censuses, so an
    operator's own edit is not refused by the arbiter."""
    repo = _baseline_repo(tmp_path)
    record = _baseline_record()
    record["on_behalf_of"] = "operator-ann"
    _planted(repo, record)
    for name, census in (("census.py", _census_py), ("census.sh", _census_sh)):
        _code, err = census(repo)
        assert _code == 0, f"via {name}: {_code} {err}"


def test_the_censuses_accept_a_record_with_all_three_fields(tmp_path):
    """The shape the writer produces is accepted verbatim by both censuses: the
    three fields are in the closed set, not reported as unknown. The one-option
    question is what earns the marker, so the fixture carries one."""
    repo = _baseline_repo(tmp_path)
    record = _baseline_record()
    record["decided_by"] = "delegate-bot"
    record["on_behalf_of"] = "operator-ann"
    record["single_option"] = True
    record["questions"] = [{"id": "q1", "text": "Ship?", "options": ["ship it"],
                            "answer": "ship it"}]
    _planted(repo, record)
    for name, census in (("census.py", _census_py), ("census.sh", _census_sh)):
        _code, err = census(repo)
        assert _code == 0, f"via {name}: {_code} {err}"


def test_a_supersede_carries_the_new_fields_through_the_status_flip(tmp_path):
    """A supersede copies its target verbatim and changes one value, so a target
    carrying the new fields keeps them and the census stays clean on both paths.

    The first record asks its question with one option (which is what earns the
    ``single_option`` marker it carries); the successor repeats that question and
    its options, so the marker stays earned on both paths."""
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
                *QUESTION, "--option", "q1=next train", *ANSWERED,
                DECIDED_BY, "operator-ann", BEHALF, "release team", SINGLE)
    assert proc.returncode == 0, proc.stderr
    # _decide already passes the question, its two options and --slug/--date: the
    # successor adds only the answers a supersede requires plus the target, and
    # repeating --question here would be a second q1 the writer refuses (exit 2).
    successor = _decide(repo, "--slug", "corrected", *ANSWERED, "--supersedes", NEW_ID,
                        DECIDED_BY, "operator-ann")
    assert successor.returncode == 0, successor.stderr
    target = _read(repo, NEW_ID)
    assert target["status"] == "superseded"
    assert target["decided_by"] == "operator-ann"
    assert target["on_behalf_of"] == "release team"
    assert target["single_option"] is True
    _assert_both_censuses_clean(repo, "a supersede of a record with the new fields")


def test_a_target_carrying_a_malformed_new_field_is_refused(tmp_path):
    """The status flip copies every byte of the target it is not the status of, so
    a target holding a malformed name is refused at exit 4 rather than rewritten:
    the writer must not repair the ledger by accident."""
    repo = _baseline_repo(tmp_path)
    record = _baseline_record()
    record["decided_by"] = 7
    path = _planted(repo, record)
    proc = _run(repo, "--slug", "corrected", "--date", NEW_DATE, *BASE, *QUESTION,
                *OPTIONS, *ANSWERED, "--supersedes", record["id"])
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "decided_by" in proc.stderr, proc.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["decided_by"] == 7, \
        "a refused run must leave the target's bytes alone"
