"""The record's ``why`` beside the attribution fields: writer and both censuses.

``decide --why`` records one line of the operator's reason. It sits in the same family
as ``decided_by`` and ``on_behalf_of`` -- optional, appended last, refused at the flag
and reported by the arbiter -- and shares ``decided_by``'s single-line rule plus one
length bound the item store owns.

The three entry points have to agree or a record gets committed that the census then
reports at exit 10: the writer (which refuses a bad value at the flag), the Python
census's ledger-record pass, and the ``census.sh`` shim over the same ledger. Every
case here is asserted against both censuses, which is why this file drives a committed
tree rather than an in-process predicate.

What the sibling files hold: the flag's own refusals, its help text and its
byte-for-byte compatibility claim are ``tests/test_decide_why_field.py``; the name and
marker rules through every entry point are
``tests/test_ledger_name_and_marker_rules.py``; the closed key set is
``tests/test_ledger_closed_key_set.py``. This file is the ``why`` case set the
attribution cases already had, so the new field is not the one the parity suite
skipped -- and the bound it asserts is read from the product, never spelled.
"""

import json

from _harness import (
    REPO,
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
    _porcelain,
    _read,
    _record_path,
    _run,
)
from ledger_schema_fixtures import (
    FIXTURES,
    ORDINARY_WHY,
    RAW_SEPARATORS,
    WHY_FIELD,
    WHY_MAX,
    _fixture,
    why_at_bound,
    why_over_bound,
)

# The three separators json escapes and ``str.splitlines`` breaks a line on, named here
# because the attribution cases above spell them beside a name field and these cases
# spell them beside a reason: the same ten characters, two fields, one rule.
FILE_GROUP_RECORD = ("\x1c", "\x1d", "\x1e")

# The census-side shapes a hand edit can plant, as ``(name, value)``: the writer's own
# refusal list driven through the arbiter instead. Each is refused at the flag, so the
# only route to a ledger is an edit, and both entry points must answer it.
BAD_WHY_SHAPES = {
    "blank": "",
    "padded": "   ",
    "newline": "one\ntwo",
    "carriage": "one\r\ntwo",
    "over": None,           # filled by the bound helper, so no number is spelled here
    "number": 7,
    "boolean": True,
    "list": ["because"],
    "object": {},
    "null": None,
}

# The files that read the rationale rule and so may not carry a copy of its number.
# ``itemschema`` is the owner and is absent by role; ``census_ordering`` holds the one
# documented copy (it loads by path and imports nothing), which
# ``tests/test_order_writer_arbiter.py`` holds to the owner.
# The character sets and the two bound helpers live in one shared module so the
# suites that drive a rationale through the censuses cannot keep separate copies of
# either. The arbiter's own copy of the bound is asserted beside the owner by
# ``tests/test_order_writer_arbiter.py``: it loads by path and imports nothing, so it
# is the one spelling in the product a reader must check by reading it back.
BOUND_LITERATURE = (
    "tests/ledger_schema_fixtures.py",
    "tests/test_decide_attribution_fields.py",
    "tests/test_ledger_name_and_marker_rules.py",
    "tests/test_ledger_closed_key_set.py",
    "tests/test_decide_skill.py",
    "src/noni/_decide_flags.py",
    "src/noni/_why.py",
    "src/noni/census_ledger_checks.py",
    "src/noni/decide.py",
    "src/noni/ledger_schema.py",
    "src/noni/targetschema.py",
    "skills/census/scripts/census.py",
    "skills/steering-ledger/scripts/census.sh",
)


def _planted(repo, record, raw=False):
    """Commit ``record`` as a hand-written ledger file, bypassing the writer.

    The census-side cases need shapes the writer would never produce, which is what
    makes them census cases and not writer cases. ``raw`` writes with
    ``ensure_ascii=False``, the only way a separator reaches the bytes unescaped:
    json escapes the short controls and writes the three of ``RAW_SEPARATORS``
    through, which is why the single-line rule is not a check for a newline alone.
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


def _planted_with(tmp_path, subdir, *, raw=False, **extra):
    """A committed baseline tree whose ledger holds one hand-written record.

    ``raw`` is passed through to :func:`_planted`: it is what lets a separator
    reach the file's bytes unescaped, which is the premise the raw-separator
    case below asserts about itself.

    ``extra`` are the fields planted on top of the eight required ones, so a caller
    asks about one field and nothing else: the baseline is the same record every case
    here starts from, and a shape that quietly carried a second defect would be
    reported by the wrong rule.
    """
    repo = _baseline_repo(tmp_path, subdir)
    record = _baseline_record()
    record.update(extra)
    return repo, _planted(repo, record, raw=raw)


# --- the writer, beside the attribution cases --------------------------------

def test_a_run_with_a_reason_writes_the_field_after_the_attribution(tmp_path):
    """The reason joins the optional family in the order every document prints: the
    attribution first, then the reason, so one run naming both writes the field order
    the schema declares.

    A dict comparison cannot see key order, and a record whose keys are in another
    order is not canonical bytes -- the census compares a supersede target against the
    bytes the renderer produces.
    """
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--decided-by", "operator-ann",
                   "--on-behalf-of", "release team", f"--{WHY_FIELD}", ORDINARY_WHY)
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record[WHY_FIELD] == ORDINARY_WHY
    assert list(record) == ["id", "date", "asked_by", "questions", "by", "scope",
                            "status", "supersedes", "decided_by", "on_behalf_of",
                            WHY_FIELD]
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "a record naming who decided and why")


def test_a_run_without_the_flag_writes_the_bytes_it_always_wrote(tmp_path):
    """The compatibility claim the attribution cases make, for the new field: a run
    naming no reason holds exactly the eight required fields and no key for a reason.

    The mutation it survives: writing ``"why": null`` for a run that named none, which
    would restamp every pre-#122 record the next time it was written and make an
    unchanged ledger read as changed.
    """
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert WHY_FIELD not in record
    assert list(record) == ["id", "date", "asked_by", "questions", "by", "scope",
                            "status", "supersedes"]
    _assert_both_censuses_clean(repo, "a record with no reason")


def test_a_reason_is_written_beside_the_attribution_and_overrides_nothing(tmp_path):
    """A reason says nothing about who decided: ``by`` stays git's identity, the
    attribution keeps what the flags said, and the reason carries what was typed, word
    for word.

    The census reports ``by`` from git, so no flag may claim an authorship, and a
    reason silently trimmed or normalised would no longer be the operator's sentence.
    """
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--decided-by", "delegate-bot",
                   f"--{WHY_FIELD}", "it's the only train we can make")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["by"] == "Replay", "the flag must not overwrite the git identity"
    assert record["decided_by"] == "delegate-bot"
    assert record[WHY_FIELD] == "it's the only train we can make"
    _assert_both_censuses_clean(repo, "a reason beside an attribution")


# --- both censuses, on a planted bad why ------------------------------------

def test_every_bad_why_is_exit_10_from_both_censuses_naming_the_field(tmp_path):
    """Each shape the writer refuses at the flag is a ``ledger-record`` failure (10)
    from ``census.py`` and ``census.sh`` alike when it reaches the ledger by hand, and
    each row names ``why``.

    The phrase is asserted with the code: an exit 10 raised for some other fault in
    the same record would otherwise certify this rule while refusing for a reason it
    was not planted to test. A non-string must be a row and not a fault of the reader,
    which is why the ``len`` arm of the rule is never asked of a number or a null.
    """
    for index, (name, value) in enumerate(BAD_WHY_SHAPES.items()):
        if value is None:
            value = why_over_bound()
        repo, _path = _planted_with(tmp_path, f"bad-{index}",
                                    id=f"{NEW_DATE}-why-{name}", **{WHY_FIELD: value})
        for census_name, census in (("census.py", _census_py),
                                    ("census.sh", _census_sh)):
            code, err = census(repo)
            assert code == 10, f"{name} via {census_name}: {code} {err}"
            assert WHY_FIELD in err, f"{name} via {census_name}: {err}"


def test_a_raw_separator_in_a_reason_is_exit_10_from_both_censuses(tmp_path):
    """The three breaks json writes into the bytes unescaped are the ones a hand edit
    can carry while the value stays one JSON string, so they are the case the
    single-line rule exists for: a census that split on the escaped ``\\n`` alone
    would read the value as one line and report it as one line.

    The fixture asserts its own premise -- if the separator did not reach the bytes,
    the case probed nothing -- because that is how a raw-unicode suite quietly stops
    testing the thing it names.
    """
    for index, separator in enumerate(RAW_SEPARATORS):
        repo, path = _planted_with(
            tmp_path, f"raw-{index}",
            id=f"{NEW_DATE}-raw-{ord(separator):x}",
            **{WHY_FIELD: f"a{separator}b"}, raw=True)
        planted = path.read_bytes()
        assert planted.count(separator.encode("utf-8")) == 1, \
            "the fixture escaped the separator, so it probed nothing"
        for census_name, census in (("census.py", _census_py),
                                    ("census.sh", _census_sh)):
            code, err = census(repo)
            assert code == 10, (
                f"U+{ord(separator):04X} via {census_name}: {code} {err}")
            assert WHY_FIELD in err, (
                f"U+{ord(separator):04X} via {census_name}: {err}")


def test_a_file_group_separator_in_a_reason_is_exit_10_from_both(tmp_path):
    """The three separators json escapes are still refused at the record: a hand edit
    that wrote the escape by hand is two lines to the census's basis, which is
    ``str.splitlines`` read out as a set.

    Same class as the raw case, different route to the bytes: json's escaping means
    these three can only arrive deliberately, and the rule still has to answer them.
    """
    for index, separator in enumerate(FILE_GROUP_RECORD):
        repo, _path = _planted_with(
            tmp_path, f"fg-{index}",
            id=f"{NEW_DATE}-filegroup-{ord(separator):x}",
            **{WHY_FIELD: f"a{separator}b"}, raw=True)
        for census_name, census in (("census.py", _census_py),
                                    ("census.sh", _census_sh)):
            code, err = census(repo)
            assert code == 10, (
                f"U+{ord(separator):04X} via {census_name}: {code} {err}")
            assert WHY_FIELD in err, (
                f"U+{ord(separator):04X} via {census_name}: {err}")


def test_the_committed_why_fixture_is_clean_in_both_censuses(tmp_path):
    """The positive control: the committed record that carries an attribution and a
    reason is what the writer produces, and both censuses read it as clean.

    A refusal-only suite proves the two sides agree about what is wrong; this is what
    shows the rule was not tightened until the writer's own output failed.
    """
    repo, _path = _planted_with(tmp_path, "why-fixture",
                                **_fixture("decision-why.json"))
    for census_name, census in (("census.py", _census_py),
                                ("census.sh", _census_sh)):
        code, err = census(repo)
        assert code == 0, f"the why fixture via {census_name}: {code} {err}"


def test_a_reason_at_the_bound_is_clean_in_both_censuses(tmp_path):
    """The longest reason either side accepts is the bound, read from the product: a
    census one code point tighter than the writer makes every long reason an artifact
    no verb can repair, since the writer refuses to re-render it.

    The bound comes from ``ledger_schema.why_max()`` and not a number here, so this
    case moves with the product instead of pinning a copy of it.
    """
    repo, _path = _planted_with(tmp_path, "at-bound",
                                id=f"{NEW_DATE}-at-bound",
                                **{WHY_FIELD: why_at_bound()})
    for census_name, census in (("census.py", _census_py),
                                ("census.sh", _census_sh)):
        code, err = census(repo)
        assert code == 0, f"a reason at the bound via {census_name}: {code} {err}"


# --- the supersede target gate ----------------------------------------------

def record_id(path) -> str:
    """The record id a planted path stands for: the file's own stem.

    Read from the path rather than passed by every caller, so a case cannot name a
    target other than the record it planted -- which would leave the refusal above
    answering for a file that was never edited.
    """
    return path.stem

def test_a_target_carrying_a_bad_reason_is_refused_at_exit_four(tmp_path):
    """The status flip copies every byte of the target it is not the status of, so a
    target holding a malformed reason is refused at exit 4 rather than rewritten: the
    writer must not launder a hand-edited reason into a new id.

    The target's bytes are asserted afterwards because the refusal's whole point is
    that nothing was repaired -- a supersede that fixed the value would erase the
    evidence the census reports.
    """
    repo, path = _planted_with(tmp_path, "target-bad",
                               **{WHY_FIELD: "two\nlines"})
    proc = _run(repo, "--slug", "corrected", "--date", NEW_DATE, *BASE, *QUESTION,
                *OPTIONS, *ANSWERED, "--supersedes", record_id(path))
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert WHY_FIELD in proc.stderr, proc.stderr
    assert json.loads(path.read_text(encoding="utf-8"))[WHY_FIELD] == "two\nlines", \
        "a refused run must leave the target's bytes alone"
    assert not _record_path(repo, f"{NEW_DATE}-corrected").exists()


def test_a_target_carrying_a_good_reason_is_carried_through_the_flip(tmp_path):
    """The other side of the same gate: a target holding a well-formed reason is not
    refused, and the reason survives the status flip.

    Without this the exit-4 assertion above would be satisfied by a gate that refused
    every target carrying the field at all.
    """
    repo, path = _planted_with(tmp_path, "target-good",
                               **{WHY_FIELD: ORDINARY_WHY})
    proc = _run(repo, "--slug", "corrected", "--date", NEW_DATE, *BASE, *QUESTION,
                *OPTIONS, *ANSWERED, "--supersedes", record_id(path))
    assert proc.returncode == 0, proc.stderr
    target = json.loads(path.read_text(encoding="utf-8"))
    assert target["status"] == "superseded"
    assert target[WHY_FIELD] == ORDINARY_WHY
    _assert_both_censuses_clean(repo, "a supersede of a record with a reason")


# --- the bound is read from the product, never spelled -----------------------

def test_no_reader_of_the_rule_spells_the_bound_as_a_literal():
    """The acceptance criterion is mechanical: a module that names the bound with its
    digits has a second copy of the number, and the day one moves the two disagree
    about a value the writer wrote.

    Read off the shipped files rather than asserted against a constant, because the
    failure mode is a *literal*, and a legitimate read of the product's number looks
    the same as a stale copy until the number moves. The owner (``itemschema``, which
    declares it) is absent by role, as is ``census_ordering``, whose copy is documented
    and held to the owner by the shared shape table.
    """
    from noni.itemschema import WHY_MAX as owner

    assert owner == WHY_MAX, (
        f"the fixtures' bound ({WHY_MAX}) is not the product's ({owner}): the helper "
        "read a copy rather than the owner")
    for rel in BOUND_LITERATURE:
        text = (REPO / rel).read_text(encoding="utf-8")
        offenders = [f"{rel}:{number}: {line.strip()}"
                     for number, line in enumerate(text.splitlines(), 1)
                     if str(owner) in line]
        assert not offenders, (
            f"{rel} spells the rationale bound {owner} as a literal; read it from the "
            f"product: {offenders}")


def test_the_committed_why_fixture_holds_the_fields_it_claims():
    """The fixture the suite plants is on disk and holds an attribution, a reason and
    a reason shorter than the bound, so the clean-run assertion above is not a loop
    over nothing.

    A fixture deleted or renamed out of ``tests/fixtures/`` turns every plant into a
    missing-file error the census answers for the wrong reason.
    """
    record = _fixture("decision-why.json")
    assert (FIXTURES / "decision-why.json").is_file()
    assert record[WHY_FIELD] == ORDINARY_WHY
    assert len(record[WHY_FIELD]) < WHY_MAX, "the control must sit inside the bound"
    assert "decided_by" in record
    assert len(why_at_bound()) == WHY_MAX, "the bound helper is not the bound"
