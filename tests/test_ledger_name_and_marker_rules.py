"""The name rules and the single-option marker, through every entry point.

Both are rules the readers of the ledger schema must answer alike, which is
the only reason they are worth a test apiece: ``decide.py`` refuses at the flag,
``census.py``'s record pass reports, and
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

The parity assertions here used to run against a second arbiter -- the jq program
beside ``census.sh``, which declared the same rules in a second language. That
program is deleted (issue #99) and the wrapper runs the census instead, so the
tests that parsed its class literals and its key list went with it, and what is
left is behavioural: every entry point refuses the same values and names the
field it refused. The closed key set is in
``tests/test_ledger_closed_key_set.py``; the launchers are shared from
``tests/ledger_schema_fixtures.py``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from _harness import REPO, subprocess_env
from ledger_class_support import _comment_above, _names_strip_as_basis
from ledger_schema_fixtures import (
    CENSUS_SH,
    _assert_both_clean,
    _assert_both_refuse,
    _baseline,
    _ledger,
    no_package_env,
)

# Each of the three separators json escapes and str.splitlines breaks a line on.
FILE_GROUP_RECORD = ("\x1c", "\x1d", "\x1e")
# Each of the three json writes into the bytes unescaped, which is why the rule
# cannot be a check for a newline alone: the value is one JSON string and two lines.
RAW_SEPARATORS = ("\x85", "\u2028", "\u2029")
# A name made of nothing but a character the blank rule refuses: the four of
# ``ledger_schema.BLANKS`` (space, tab, U+000B, U+000C), each alone and each
# doubled, plus the empty string. The comment test below reads BLANKS's own
# wording, so these five spellings exercise the rule and do not restate the set.
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


def test_the_blank_rule_names_the_four_characters_and_not_str_strip():
    """The place that documents the blank rule states the four characters, not
    ``str.strip()``.

    The set is four characters -- space, tab, U+000B, U+000C -- while
    ``str.strip()`` also removes U+001C-U+001F, U+0085, U+00A0, U+1680, the
    U+2000-U+200A run, U+202F, U+205F and U+3000. Naming the wider basis was the
    bug: it described a rule the census does not enforce (a name of nothing but
    U+00A0 is accepted), and a parity test over the code alone could not catch it
    because the *code* was right and only the prose was wrong. So the prose is
    asserted the way the set is: read off the shipped bytes, in the one place it
    is written -- the ``BLANKS`` comment in ``noni/ledger_schema.py``. The second
    place that carried it was the jq program's ``line_free``, which no longer
    exists.
    """
    comment = _comment_above((REPO / "src" / "noni" / "ledger_schema.py"
                              ).read_text(encoding="utf-8"), "BLANKS = (")
    assert "U+000B" in comment and "U+000C" in comment, (
        "ledger_schema.BLANKS: the comment must name the four characters it "
        f"refuses, not the wider str.strip() basis: {comment}")
    stated = [line for line in comment.splitlines()
              if "str.strip" in line and not line.lstrip().startswith("# not")]
    assert not any(_names_strip_as_basis(line) for line in stated), (
        "ledger_schema.BLANKS: the comment still names str.strip() as the basis "
        f"of the blank set, which is wider than the four characters: {comment}")


# --- the name rules, every entry point -------------------------------------

def test_every_entry_point_agrees_on_every_break_and_blank(tmp_path):
    """One table, every entry point: the writer's flag and the census's record
    pass refuse the same values, and name the field they refused.

    The three separators json escapes, the three it writes raw and the blanks each
    go through all of them, and ``ORDINARY`` is the positive control that keeps the
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
                             is_single_line, {}, False) == 2, (
            f"{label}: flag_refusals accepted it")

        # 2. The census, through both routes to it: the shim in a subprocess and
        # the unified census directly. The row must name the field either way,
        # which is the agreement that matters; census.py's in-process message is
        # asserted verbatim in test_the_record_pass_names_the_field_and_the_reason.
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
                         is_single_line, {}, False) is None
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


# --- the marker, every entry point -----------------------------------------

def test_the_record_pass_names_the_field_and_the_reason():
    """census.py's own record pass reports a blank or broken name as one row that
    names the field, in the wording its other name rules use.

    Asserted in process rather than through the report: the predicate's own output
    is the thing every entry point has to agree on, and the report is where a row
    adds the fix hint and the artifact around it.
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
    to both entry points, naming the marker.

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

    census.py names the marker in its row, so the specific wording is asserted
    where it exists and the shared assertion settles the refusal on both routes.
    """
    record = _baseline()
    record["id"] = "2026-10-04-one-option-unmarked"
    record["questions"] = [
        {"id": "q1", "text": "Ship now?", "options": ["only-one"], "answer": "only-one"}]
    verdicts = _assert_both_refuse(tmp_path, record, "option",
                                   "unmarked one-option question")
    assert "single_option" in verdicts["census.py"][1], verdicts["census.py"][1]


def test_a_scalar_question_entry_is_refused_by_both_and_named(tmp_path):
    """A ``questions`` array holding a bare value -- ``5``, ``"a"``, ``true`` -- is
    refused by both entry points at exit 10, each naming the shape.

    The regression is the blank diagnostic. The deleted jq program faulted on a
    number, a string or a boolean (every ``has()`` in it reads a key of a
    non-object, jq exits 5) and the shim, which discarded jq's stderr, printed
    ``schema violation:  (10:schema)`` -- the exit code right and the reason named
    by nothing. census.py has always called it "question entry is not an object",
    the wording the AC names, so both routes are now pinned to that one wording.

    The marker is planted on two of the three cases: the marker's own count reads
    ``options`` of every item, so a guard sitting only in the questions rule left
    the fault live on the marked record.
    """
    for index, scalar in enumerate((5, "a", True)):
        record = _baseline()
        record["id"] = f"2026-10-04-scalar-{index}"
        record["questions"] = [scalar]
        if index:
            # The marked form reaches the item through the marker's own count.
            record["single_option"] = True
        label = f"a questions array holding {scalar!r}"
        _assert_both_refuse(tmp_path, record, "question entry is not an object",
                            label, subdir=f"scalar-{index}")


def test_an_earned_marker_over_mixed_questions_is_clean_in_both(tmp_path):
    """The per-record marker over the per-question bound: a marked record mixing a
    one-option question with a 2-4-option one is valid in both entry points.

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
    bound: both entry points refuse it and name it, so a record cannot buy the
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


# --- the wrapper's own exit-3 -----------------------------------------------

def _run_sh_from(script: Path, ledger: Path,
                 env: dict | None = None) -> tuple[int, str]:
    """census.sh at an arbitrary path over ``ledger``, in a chosen environment."""
    proc = subprocess.run(["bash", str(script), str(ledger)],
                          capture_output=True, text=True,
                          env=env if env is not None else subprocess_env(),
                          timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def test_census_sh_exits_three_when_the_package_is_not_importable(tmp_path):
    """The wrapper's one refusal of its own: no importable package is exit 3.

    The wrapper carries no rules, so the only fault it can raise on its own is the
    one about its interpreter and its package: a missing interpreter or an
    unimportable ``noni`` is named on one plain line and exits 3, the census's own
    code for a tool the reading machine does not have. The sub-class this test used
    to pin was ``3:schema-program-missing``, the sibling ``census-schema.jq``
    having gone with the second arbiter; what the wrapper still cannot do is run,
    and this is the run that says so rather than printing a traceback or reporting
    a clean it never established.
    """
    ledger = _ledger(tmp_path / "no-import-ledger", _baseline())
    # A ``python3`` that cannot import the package. Overwriting PYTHONPATH alone
    # is not enough: an installed ``noni`` is reached by a ``.pth`` in the venv's
    # ``site-packages``, which PYTHONPATH cannot hide (that is what CI does, and
    # what made this test pass for the wrong reason until issue #99). So the
    # interpreter the wrapper names is a stub starting the real one ``-S -I``,
    # with the empty PYTHONPATH as the second route closed. The wrapper still
    # resolves a real interpreter, so this is the package half of the refusal and
    # not the interpreter half (which tests/test_sessions_census_exits.py pins).
    env = no_package_env(tmp_path, "no-import")
    code, out = _run_sh_from(CENSUS_SH, ledger, env)
    assert code == 3, f"expected 3 with no importable package, got {code}:\n{out}"
    assert "not importable" in out, out
    assert "Traceback" not in out, f"a traceback is not a diagnostic: {out}"
    assert "summary:" not in out, (
        f"a census that could not load printed a report: {out}")
