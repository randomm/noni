"""The name rules and the single-option marker, through all three entry points.

Both are rules the four readers of the ledger schema must answer alike, which is
the only reason they are worth a test apiece: ``decide.py`` refuses at the flag,
``census.py``'s record pass reports, ``census.sh``'s jq program reports, and
``targetschema`` refuses a supersede target carrying either. A rule one of them
drops is a record the writer committed and an arbiter then refused -- or, the
worse direction, a record every arbiter calls clean that the rule was written to
stop.

The names. ``is_single_line`` is the one predicate, and it carries both rules:
a value made of nothing but whitespace names nobody, and a value carrying any of
``LINE_BREAKS`` is not one line. The set is ``str.splitlines`` read out as a set,
so the rule named after that basis is the rule it means -- including U+001C,
U+001D and U+001E, which json escapes (so a record cannot carry one by accident)
but which the documented basis breaks a line on.

The marker. ``single_option`` is a per-record marker over a per-question bound:
with it set any question may hold one option, and at least one question of the
record must, so a marker no question carries a one option for says something the
record does not show.

The closed key set, and the parity of the two programs' field lists, are in
``tests/test_ledger_closed_key_set.py``; the launchers are shared from
``tests/ledger_schema_fixtures.py``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from _harness import REPO, subprocess_env
from ledger_schema_fixtures import (
    CENSUS_SH,
    SCHEMA_JQ,
    _assert_both_clean,
    _assert_both_refuse,
    _baseline,
    _ledger,
)

# Each of the three separators json escapes and str.splitlines breaks a line on.
FILE_GROUP_RECORD = ("\x1c", "\x1d", "\x1e")
# Each of the three json writes into the bytes unescaped, which is why the rule
# cannot be a check for a newline alone: the value is one JSON string and two lines.
RAW_SEPARATORS = ("\x85", "\u2028", "\u2029")
# A name made of nothing but characters str.strip() removes.
BLANKS = ("", "   ", "\t", " \t ", "\x0b\x0c")
# A name an operator would actually type: spaces, a dot, a digit.
ORDINARY = "Dr. A. Reyes"


def _fail_recorder() -> tuple[list[tuple[int, str]], callable]:
    """A printer that records, and returns the (calls, fail) pair the flag rules take."""
    calls: list[tuple[int, str]] = []

    def fail(code: int, message: str, hint: str | None = None) -> int:
        calls.append((code, message))
        return code

    return calls, fail


# --- the line-break basis ----------------------------------------------------

def test_the_line_break_set_is_the_documented_splitlines_basis():
    """``LINE_BREAKS`` is exactly what ``str.splitlines`` breaks on, so the rule
    named after that basis is the rule it means.

    ``\x1c``/``\x1d``/``\x1e`` are the three the set gained on this issue: json
    escapes them, so a record cannot carry one by accident, but a hand edit can,
    and the writer's own basis calls the value two lines.
    """
    from noni.ledger_schema import LINE_BREAKS

    for char in FILE_GROUP_RECORD + RAW_SEPARATORS + ("\n", "\r", "\x0b", "\x0c"):
        assert char in LINE_BREAKS, (
            f"U+{ord(char):04X} is a splitlines break but absent from the set")
    # And the set holds nothing the basis does not break on.
    for char in LINE_BREAKS:
        assert f"a{char}b".splitlines() == ["a", "b"], (
            f"U+{ord(char):04X} is in the set but is not a splitlines break")


def test_the_jq_line_class_names_every_break_the_python_set_names():
    """The jq program's line class is the same ten characters, so the two censuses
    cannot disagree about a name the way the key-count rule once let them.

    The class is parsed out of the shipped ``line_free`` rather than retyped: the
    assertion is about the shipped bytes, and a copy here would drift with them.
    """
    from noni.ledger_schema import LINE_BREAKS

    text = SCHEMA_JQ.read_text(encoding="utf-8")
    definition = re.search(r"def line_free:.*?\)\);", text, re.S)
    assert definition, "line_free no longer holds the two test() forms to parse"
    # The SECOND test() is the line-break class; the first is the blank test.
    classes = re.findall(r"test\(\"(\[.*?\])\"\)", definition.group(0), re.S)
    assert len(classes) == 1, f"expected one bracketed class to parse, got {classes}"
    named = set()
    for code in re.findall(r"\\u([0-9a-fA-F]{4})", classes[0]):
        named.add(chr(int(code, 16)))
    # The two characters the class spells with a backslash letter rather than \u.
    for spelled, char in (("\\n", "\n"), ("\\r", "\r")):
        if spelled in classes[0]:
            named.add(char)
    assert named == set(LINE_BREAKS), (
        f"the jq line class and LINE_BREAKS differ: jq {sorted(ord(c) for c in named)} "
        f"vs python {sorted(ord(c) for c in LINE_BREAKS)}")


# --- the name rules, three entry points -------------------------------------

def test_all_three_entry_points_agree_on_every_break_and_blank(tmp_path):
    """One table, three entry points: the writer's flag, census.py's record pass
    and census.sh's jq program refuse the same values, and name the field they
    refused.

    The three separators json escapes, the three it writes raw and the blanks each
    go through all three, and ``ORDINARY`` is the positive control that keeps the
    rule from being tightened into a refusal of everything.

    ``refuse_name`` is driven with the census's own predicate -- which is what
    decide.py hands it -- because asserting it through the predicate under test
    would only prove the two agree with each other. The blank and the break are
    reported apart, so a refusal cannot be mistaken for the other rule.
    """
    from noni._decide_flags import refuse_name
    from noni._writer import flag_refusals
    from noni.ledger_schema import is_single_line

    checked = 0
    table = FILE_GROUP_RECORD + RAW_SEPARATORS + BLANKS
    for index, value in enumerate(table):
        name = f"a{value}b" if value not in BLANKS else value
        label = f"{name!r} (entry {index})"

        # 1. The writer's flag, through the census's own predicate...
        calls, fail = _fail_recorder()
        refused = refuse_name("--decided-by", name, fail=fail, exit_usage=2,
                              line_free=is_single_line)
        assert refused == 2, f"{label}: the flag accepted a value the census refuses"
        assert calls and ("is empty" in calls[0][1]) == (value in BLANKS), (
            f"{label}: refused for the wrong reason: {calls}")
        # ...and reached through the writer's own seam, not only the helper: a flag
        # path that dropped the predicate would still pass the check above.
        calls, fail = _fail_recorder()
        assert flag_refusals(fail, 2, refuse_name, re.compile(r"[a-z0-9-]+"),
                             "slug", "scope", "asked-by", name, None,
                             is_single_line) == 2, f"{label}: flag_refusals accepted it"

        # 2. Both censuses. The row must name the field either way, which is the
        # agreement that matters; census.py's in-process message is asserted
        # verbatim in test_the_record_pass_names_the_field_and_the_reason.
        record = _baseline()
        record["id"] = f"2026-10-04-name-{index}"
        record["decided_by"] = name
        _assert_both_refuse(tmp_path, record, "decided_by", f"{label} refused by",
                            subdir=f"name-{index}")
        checked += 1

    assert checked == len(table), checked

    # The positive control, through the same three entry points.
    assert is_single_line(ORDINARY)
    calls, fail = _fail_recorder()
    assert refuse_name("--decided-by", ORDINARY, fail=fail, exit_usage=2,
                       line_free=is_single_line) is None
    assert flag_refusals(fail, 2, refuse_name, re.compile(r"[a-z0-9-]+"), "slug",
                         "scope", "asked-by", ORDINARY, None,
                         is_single_line) is None
    ok_record = _baseline()
    ok_record["id"] = "2026-10-04-name-ok"
    ok_record["decided_by"] = ORDINARY
    ok_record["on_behalf_of"] = "the platform team"
    _assert_both_clean(tmp_path, ok_record, "a name with spaces and punctuation")


def test_the_writer_refuses_a_break_the_census_predicate_names():
    """The seam is the rule: decide.py hands ``refuse_name`` the census's own
    ``is_single_line``, so a value the census calls two lines cannot be committed.

    Read off the shipped source, because a seam that quietly kept a predicate of
    the writer's own would keep every behavioural test green while letting a
    reportable name into the ledger. And the helper owns no second copy of the set
    it refuses with: two lists of ten characters is how the two sides drifted apart
    in the first place.
    """
    source = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    seam = re.search(r"_writer\.flag_refusals\(([^)]*)\)", source, re.S)
    assert seam, "decide.py no longer reaches the flag rules through _writer"
    assert "is_single_line" in seam.group(1), (
        f"the seam stopped handing in the census's predicate: {seam.group(1)}")
    assert "_decide_flags.refuse_name" in seam.group(1)
    helper = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    assert "LINE_BREAKS" not in helper and "\\u2028" not in helper, (
        "the helper kept its own copy of the line-break set instead of the argument")


# --- the marker, three entry points -----------------------------------------

def test_the_record_pass_names_the_field_and_the_reason():
    """census.py's own record pass reports a blank or broken name as one row that
    names the field, in the wording its other name rules use.

    Asserted in process rather than through the report, because the report is where
    the two censuses' wordings legitimately differ (census.sh reports the questions
    and name groups with one fixed message each): the predicate's own output is the
    thing the three entry points have to agree on.
    """
    from noni.census_ledger_checks import _validate_record

    for value in FILE_GROUP_RECORD + RAW_SEPARATORS + BLANKS:
        name = f"a{value}b" if value not in BLANKS else value
        record = _baseline()
        record["decided_by"] = name
        assert _validate_record(record) == [
            "decided_by must be a non-empty single-line string"], (
            f"{value!r}: census.py's record pass reported something else: "
            f"{_validate_record(record)}")
    # The ordinary name reports nothing, so the rule above is a refusal and not a
    # predicate that fails every value.
    assert _validate_record({**_baseline(), "decided_by": ORDINARY}) == []


def test_a_marker_no_question_earns_is_refused_by_both_censuses(tmp_path):
    """``single_option: true`` over an all-2-4-option record is a malformed record
    to both censuses, naming the marker.

    The marker says a question was asked with one option; a record that shows none
    does not say it. The writer refuses the flag combination at exit 2, so the
    census is asked about a hand edit -- and answers alike.
    """
    record = _baseline()
    record["id"] = "2026-10-04-unearned-marker"
    record["single_option"] = True
    verdicts = _assert_both_refuse(tmp_path, record, "single_option",
                                   "unearned marker")
    assert all("no question has exactly one option" in out
               for _code, out in verdicts.values()), verdicts


def test_a_one_option_question_without_the_marker_is_refused_by_both(tmp_path):
    """The other half of the same bound: the content does not relax it, only the
    marker does.

    census.py names the marker in its row; census.sh reports the whole questions
    group with one fixed message, so the code is what settles the refusal there and
    the specific wording is asserted where it exists.
    """
    record = _baseline()
    record["id"] = "2026-10-04-one-option-unmarked"
    record["questions"] = [
        {"id": "q1", "text": "Ship now?", "options": ["only-one"], "answer": "only-one"}]
    verdicts = _assert_both_refuse(tmp_path, record, "option",
                                   "unmarked one-option question")
    assert "single_option" in verdicts["census.py"][1], verdicts["census.py"][1]


def test_an_earned_marker_over_mixed_questions_is_clean_in_both(tmp_path):
    """The per-record marker over the per-question bound: a marked record mixing a
    one-option question with a 2-4-option one is valid in both censuses.

    This is what makes the rule per record rather than per question -- judged
    question by question, the 2-4 question of this record would have to be refused
    for not being the one the marker speaks for.
    """
    record = _baseline()
    record["id"] = "2026-10-04-mixed-marker"
    record["single_option"] = True
    record["questions"] = [
        {"id": "q1", "text": "Ship now?", "options": ["ship it"], "answer": "ship it"},
        {"id": "q2", "text": "Who reviews?",
         "options": ["the operator", "nobody"], "answer": "the operator"},
    ]
    _assert_both_clean(tmp_path, record, "a marker earned by one of two questions")


def test_a_malformed_marker_value_is_refused_by_both(tmp_path):
    """``single_option: false`` (or a string) is a malformed marker, not a relaxed
    bound: both censuses refuse it and name it, so a record cannot buy the
    relaxation with a truthy value of the wrong type.
    """
    for value in (False, "true", 1):
        record = _baseline()
        record["id"] = f"2026-10-04-marker-{type(value).__name__}-{value}"
        record["single_option"] = value
        _assert_both_refuse(tmp_path, record, "single_option",
                            f"marker set to {value!r}", subdir=f"marker-{value!r}")


def test_the_writer_refuses_a_marker_no_question_earns(tmp_path):
    """``--single-option`` over an all-2-4-option record is exit 2 and writes nothing.

    The mirror of the census rule asserted on the writer's side: the same two facts
    (the flag, and whether a question holds one option), refused earlier, with a
    message naming the flag. No record, no staged path -- and the same run with the
    marker earned by a one-option question is accepted, which is what shows the
    refusal is about the marker being unearned and not about the flag existing.
    """
    from decide_fixtures import (
        BASE,
        NEW_DATE,
        NEW_ID,
        _baseline_repo,
        _decide,
        _porcelain,
        _record_path,
        _run,
    )

    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, "--answer", "q1=next train", "--single-option")
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "--single-option" in proc.stderr, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()
    assert _porcelain(repo) == ""
    earned = _run(repo, "--slug", "earned", "--date", NEW_DATE, *BASE,
                  "--question", "q1=Ship now?", "--option", "q1=ship it",
                  "--answer", "q1=ship it", "--single-option")
    assert earned.returncode == 0, earned.stderr


# --- census.sh's exit-3 sub-class -------------------------------------------

def _run_sh_from(script: Path, ledger: Path) -> tuple[int, str]:
    """census.sh at an arbitrary path over ``ledger``: the orphan-sibling case."""
    proc = subprocess.run(["bash", str(script), str(ledger)],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def test_census_sh_exits_three_when_the_schema_program_is_missing(tmp_path):
    """census.sh copied WITHOUT its sibling census-schema.jq exits 3 carrying the
    ``3:schema-program-missing`` marker, on a ledger that would otherwise read clean.

    The sub-class is documented in four places (the script's own header, the
    package's ``shim_help.CENSUS_SH_HELP``, ``references/census.md`` and the usage
    fixture), and this is the run those documents describe: without the program
    there is no schema to apply, and a census that read the directory and printed
    only a header row would be reporting a clean it never established.
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    ledger = _ledger(tmp_path / "orphan-ledger", _baseline())
    (scripts / "census.sh").write_text(CENSUS_SH.read_text(encoding="utf-8"),
                                       encoding="utf-8")
    assert not (scripts / "census-schema.jq").exists(), (
        "the fixture copied the schema program, so it proves nothing")
    code, out = _run_sh_from(scripts / "census.sh", ledger)
    assert code == 3, f"expected exit 3 for a missing schema program, got {code}:\n{out}"
    assert "3:schema-program-missing" in out, out
    assert "id\tdate\tby\tstatus\tlive\tsupersedes" not in out, (
        f"a census that could not apply a schema printed a report: {out}")


def _run_sh_from(script, ledger) -> tuple[int, str]:
    """census.sh at an arbitrary path over ``ledger``: the orphan-sibling case."""
    import subprocess
    import sys

    proc = subprocess.run([sys.executable and "bash", str(script), str(ledger)],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr
