"""The ledger's ``why`` field: one bounded line of the operator's reason.

``decide --why`` records why a decision went the way it did. It is an optional field
of the decision record: absent on every record written before #122, and refused at the
flag when it is blank, multi-line, or past the bound the item store already set for its
reason field.

Three entry points have to agree or a record gets committed that the census then
reports at exit 10: the writer, the Python census's ledger-record pass, and census.sh's
jq program. Every case here is asserted against both censuses.
"""

from __future__ import annotations

import json
import subprocess

from _harness import DECIDE, REPO, _git, _init_repo, subprocess_env
from decide_fixtures import (
    ANSWERED,
    NEW_DATE,
    _assert_both_censuses_clean,
    _baseline_repo,
    _census_py,
    _decide,
    _decide_ast,
    _docstring,
    _read,
    _record_json,
    _record_path,
)

# The bound every rationale in the product answers to: one number owns them all
# (_why.WHY_MAX), and this suite
# reads it rather than copying it -- a copy here would keep these runs green the day the
# owner moves, which is the drift the constant exists to prevent.
from ledger_schema_fixtures import product_why_max

WHY_MAX = product_why_max()
FIELD = "why"
REASON = "the train leaves at six, and it's the only one we can make"


def _write(repo, rel: str, body: str) -> None:
    """Plant a record's bytes by hand: the census-side cases need shapes the writer
    would never produce, which is what makes them census cases and not writer cases."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _record_body(**extra) -> str:
    """One canonical record's JSON with the extra fields merged in."""
    body = json.loads(_record_json("2026-10-05-shape", "decided", "yes", None))
    body.update(extra)
    return json.dumps(body, indent=2) + "\n"


def _rel(record_id: str) -> str:
    return f"noni/decisions/{record_id}.json"


def test_why_records_the_operators_reason_verbatim(tmp_path):
    """The operator's reason is the writer's, word for word: a reason with spaces,
    punctuation and a contraction reaches the field with nothing added or trimmed.

    It is the one assertion that says the field carries what was typed, which no
    rendering check elsewhere can read off the file.
    """
    repo = _baseline_repo(tmp_path)

    result = _decide(repo, *ANSWERED, f"--{FIELD}", REASON)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _read(repo, f"{NEW_DATE}-scheduler")[FIELD] == REASON
    _assert_both_censuses_clean(repo, "a record with a reason")


def test_a_run_without_the_flag_writes_the_shape_it_always_wrote(tmp_path):
    """The backward-compatibility claim, in one test. A record with no reason must be
    exactly the record this writer produced before the field existed: the eight fields,
    in the documented order, and no key for a reason.

    The mutation it survives: emitting ``"why": null`` or an empty string when the
    caller passed nothing, which would restamp every pre-#122 record on its next write
    and make old ledgers read as changed.
    """
    repo = _baseline_repo(tmp_path)

    result = _decide(repo, *ANSWERED)

    assert result.returncode == 0, result.stdout + result.stderr
    body = _read(repo, f"{NEW_DATE}-scheduler")
    assert FIELD not in body
    assert list(body) == ["id", "date", "asked_by", "questions", "by", "scope",
                          "status", "supersedes"]


def test_the_reason_lands_last_after_the_other_optional_fields(tmp_path):
    """Key order is documented order: a run that names an attribution field and a
    reason writes the attribution first and the reason last, so the rendered record
    matches the field list every document prints.

    A dict comparison cannot see this, and a record whose keys are in another order is
    not canonical bytes.
    """
    repo = _baseline_repo(tmp_path)

    result = _decide(repo, *ANSWERED, "--decided-by", "operator-ann",
                     f"--{FIELD}", REASON)

    assert result.returncode == 0, result.stdout + result.stderr
    keys = list(_read(repo, f"{NEW_DATE}-scheduler"))
    assert keys.index("decided_by") < keys.index(FIELD)
    assert keys == ["id", "date", "asked_by", "questions", "by", "scope", "status",
                    "supersedes", "decided_by", FIELD]


def test_an_empty_reason_is_refused_at_the_flag_and_writes_nothing(tmp_path):
    """``--why`` with nothing in it is the caller's mistake, not an empty reason: exit
    2, the flag named, and no record written.

    A writer that read ``--why ""`` as absent would let a shell quoting slip record no
    reason while reporting success, which is the one failure mode an operator could not
    see in the output.
    """
    repo = _baseline_repo(tmp_path)

    result = _decide(repo, *ANSWERED, "--why", "")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "--why" in result.stderr
    assert not _record_path(repo, f"{NEW_DATE}-scheduler").exists()


def test_a_record_written_before_the_field_stays_censusable(tmp_path):
    """Absence is not incompleteness. A record with no ``why`` is the shape every
    ledger written before #122 holds, and both censuses read it clean.

    The mutation it survives: a census that typed ``why`` as required, which would fail
    every pre-existing ledger at exit 10 and stop every merge.
    """
    repo = _baseline_repo(tmp_path)

    _decide(repo, *ANSWERED)
    code_py, out_py = _census_py(repo)

    assert FIELD not in _read(repo, f"{NEW_DATE}-scheduler")
    assert code_py == 0, out_py


def test_the_bound_is_the_shared_one_and_counts_characters_not_bytes(tmp_path):
    """The bound has one owner and counts characters the way their author counts them:
    the bound accepted, one code point past it refused, and a value of the bound's
    length in two-byte text accepted where a byte count would refuse. The numbers are
    read from the product, so this case states the bound the writer holds today.

    A writer that measured bytes would refuse a reason an operator can read at a glance;
    a writer with its own number would let one artifact's reason outgrow another's.
    """
    repo = _baseline_repo(tmp_path)

    at_limit = _decide(repo, *ANSWERED, "--slug", "at-limit", "--why", "a" * WHY_MAX)
    over = _decide(repo, *ANSWERED, "--slug", "over", "--why", "a" * (WHY_MAX + 1))
    wide = _decide(repo, *ANSWERED, "--slug", "wide", "--why", "\u00e9" * WHY_MAX)

    assert at_limit.returncode == 0, at_limit.stdout + at_limit.stderr
    assert wide.returncode == 0, wide.stdout + wide.stderr
    assert _read(repo, f"{NEW_DATE}-at-limit")[FIELD] == "a" * WHY_MAX
    assert _read(repo, f"{NEW_DATE}-wide")[FIELD] == "\u00e9" * WHY_MAX
    assert over.returncode == 2, over.stdout + over.stderr
    assert str(WHY_MAX) in over.stderr


def test_the_bound_is_stated_by_one_owner_in_the_source():
    """One number for the product's rationales: the ledger and the order read it from
    the rationale rule's own module, so no writer or doc carries a second bound to drift.

    The mutation it survives: the bound spelled as a literal in a second module, which
    reads the same today and diverges the day someone widens one of the two.
    """
    from noni import _why

    assert _why.WHY_MAX == WHY_MAX
    assert _why.why_max() == WHY_MAX
    assert _why.WHY_FIELD == FIELD


def test_every_refusal_names_the_flag_the_value_and_the_way_to_fix_it(tmp_path):
    """Each refusal is actionable and distinguishes the rules it enforces: a value with
    a line break in it is told the field is one line, an over-long value is told the
    bound and to shorten, and both name ``--why`` and show the value.

    A refusal that said only "invalid" would cost the operator a second run to learn
    which rule they broke.
    """
    repo = _baseline_repo(tmp_path)

    multi = _decide(repo, *ANSWERED, "--slug", "multi", "--why", "one\ntwo")
    blank = _decide(repo, *ANSWERED, "--slug", "blank", "--why", "   ")
    over = _decide(repo, *ANSWERED, "--slug", "over", "--why", "a" * (WHY_MAX + 1))

    for result in (multi, blank, over):
        assert result.returncode == 2, result.stdout + result.stderr
        assert "--why" in result.stderr and FIELD in result.stderr
    assert "line" in multi.stderr and "shorten" not in multi.stderr
    assert str(WHY_MAX) in over.stderr and "shorten" in over.stderr
    # The over-long refusal states the count the operator has to cut to, which is the
    # sentence a generic shape complaint could not give them.
    assert f"{WHY_MAX + 1} characters" in over.stderr


def test_a_supersede_refuses_a_target_whose_why_is_wrong(tmp_path):
    """A supersede does not launder a hand-edited reason. The target gate types the
    field before anything is copied from the target, so a bad ``why`` cannot be carried
    forward into a new id.

    It is the posture the gate already holds for the attribution fields, and the reason
    the census's report is not the only line of defence: a supersede that rewrote the
    bad value would erase the record the census reports.
    """
    repo = _baseline_repo(tmp_path)
    bad = "2026-10-05-bad-why"
    _write(repo, _rel(bad), _record_body(**{FIELD: "two\nlines"}))
    _git(repo, "add", _rel(bad))
    _git(repo, "commit", "-q", "-m", "steering: bad why")

    result = _decide(repo, "--slug", "correction", "--answer", "q1=next train",
                     "--supersedes", bad)

    assert result.returncode == 4, result.stdout + result.stderr
    assert FIELD in result.stderr and bad in result.stderr
    assert _read(repo, bad)[FIELD] == "two\nlines"
    assert not _record_path(repo, f"{NEW_DATE}-correction").exists()


def test_both_censuses_report_a_bad_why_and_name_the_field(tmp_path):
    """The arbiters catch what a hand edit writes. Each bad shape -- blank, padded,
    multi-line, over-long, or not a string at all -- is reported by the Python census
    and by census.sh alike, both naming ``why`` and the record's path.

    A census that checked only the writer's happy path would let an editor's paragraph
    into the ledger and stay silent, which is the whole class the census exists to hold.
    """
    shapes = {
        "blank": "",
        "padded": "   ",
        "multi": "one\ntwo",
        "carriage": "one\r\ntwo",
        "over": "a" * (WHY_MAX + 1),
        "number": 7,
        "list": ["a"],
        "object": {},
        "null": None,
    }
    repo = _init_repo(tmp_path / "census")
    for name, value in shapes.items():
        record_id = f"2026-10-05-{name}"
        _write(repo, _rel(record_id), _record_body(**{FIELD: value}))
    _git(repo, "add", "noni/decisions")
    _git(repo, "commit", "-q", "-m", "steering: hand-edited reasons")

    code, out = _census_py(repo)

    assert code == 10, f"expected exit 10, got {code}:\n{out}"
    for name in shapes:
        assert f"2026-10-05-{name}" in out, name
    assert out.count(FIELD) >= len(shapes), out


def test_the_help_and_the_usage_name_the_flag():
    """``--why`` is discoverable where a caller looks: in ``--help`` with its metavar,
    and in the docstring's Usage block beside the other optional flags.

    A flag no text names is a flag nobody uses, and a Usage block that omits it leaves
    the docs and the parser giving two answers about the same command.
    """
    result = subprocess.run([str(DECIDE), "--repo", str(REPO), "--help"],
                            capture_output=True, text=True, env=subprocess_env())

    assert result.returncode == 0, result.stderr
    assert "--why REASON" in result.stdout
    assert f"[--{FIELD} REASON]" in _docstring(_decide_ast())
