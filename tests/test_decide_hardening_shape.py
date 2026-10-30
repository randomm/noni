"""The shape and the chain: canonical bytes, an exact diff, and the target's record.

Extracted from the decide writer suite (the E1-E5 hardening round): the
decisions about *what* is written and *which record* it points at, including the
path-shaped refusals and the guard probes."""

import json

from _harness import (
    _decide_module,
    _git_e2,
)
from decide_fixtures import (
    ANSWERED,
    BASELINE_ID,
    _baseline_repo,
    _decide,
    _decide_ast,
    _docstring,
    _identity_env,
    _no_identity_env,
    _porcelain,
    _record_path,
)
from decide_hardening_fixtures import (
    _canonical_body,
    _decide_in_process,
    _gitwrite_module,
    _planted_body,
    _refuse_raw_target,
    _refused_target_repo,
    _supersede_in_process,
)


def test_hardening_a_target_with_a_non_string_date_refuses_with_four(tmp_path):
    """A target whose ``date`` is not a string is refused (exit 4), never sliced.

    The chain check took ``target_record.get("date", "")[:10]``, so an integer
    date raised TypeError inside the writer and a null one sliced to ``''`` and
    was reported as "dated another day", sending the operator to retype a --date
    the record does not carry in the form the census requires.
    """
    for label, value in (("int", "20261001"), ("null", "null")):
        target_id = f"{BASELINE_ID[:10]}-date-{label}"
        stderr, _repo, _rel = _refuse_raw_target(
            tmp_path, f"date-{label}", _planted_body(target_id, date=json.loads(value)))
        assert "date" in stderr, f"{label}: {stderr}"
        assert "string" in stderr, f"{label}: {stderr}"


def test_hardening_a_target_with_malformed_questions_refuses_with_four(tmp_path):
    """A target whose ``questions`` are not a non-empty list of objects with a
    string ``id`` and a string-or-null ``answer`` is refused (exit 4) before any
    write: the writer copies this record to flip its status, so bytes it cannot
    describe are bytes it cannot promise to leave alone.

    Five shapes: a bare string instead of a list, a list of strings, an entry
    with no ``id``, an ``id`` that is a number, and the numeric answer the
    reviewer named. All are census violations (census.py: "question answer must
    be a string or null", "question entry is not an object"), so the ledger
    could never have been clean with any of them committed, and a writer that
    rewrote one would be repairing the ledger by accident.
    """
    shapes = {
        # questions is a string, not a list: the census's "array of 1-4 entries"
        "questions-string": {"questions": "which release"},
        # a list, but its entries are not objects
        "questions-strings": {"questions": ["which release", "which train"]},
        # an object entry that does not name its question
        "questions-no-id": {"questions": [{"text": "Which release?",
                                          "options": ["next", "later"],
                                          "answer": "next"}]},
        # an entry that names its question with a number
        "questions-numeric-id": {"questions": [{"id": 1, "text": "Which release?",
                                                "options": ["next", "later"],
                                                "answer": "next"}]},
        # the answer the reviewer named: a number where the schema says string or null
        "questions-numeric-answer": {"questions": [{"id": "q1", "text": "Which release?",
                                                    "options": ["next", "later"],
                                                    "answer": 3}]},
    }
    for label, patch in shapes.items():
        target_id = f"{BASELINE_ID[:10]}-{label}"
        stderr, _repo, _rel = _refuse_raw_target(
            tmp_path, label, _planted_body(target_id, **patch))
        assert "questions" in stderr, f"{label}: {stderr}"


def test_hardening_a_target_with_a_non_finite_answer_refuses_with_four(tmp_path, monkeypatch):
    """A target carrying a bare ``NaN`` or ``Infinity`` is refused (exit 4), not
    rewritten: the writer's render would replace it with ``null`` and call that
    a status-only change, which rewrites a byte of the record's answer.

    ``NaN`` is not JSON, but Python's ``json.loads`` accepted the bare token by
    default and ``json.dumps`` writes it back, so a ledger file holding one
    round-tripped through the writer as ``null``. The fixture plants the token
    verbatim and pins the character on disk first: if json ever stopped reading
    it, this test would be asserting nothing about the render. The refusal is
    made by the reader (``record_object``'s ``parse_constant``), so the record is
    never turned into an object at all and the renderer is never asked for it --
    which is what the render observer below pins.
    """
    for label, token in (("nan", "NaN"), ("inf", "Infinity")):
        target_id = f"{BASELINE_ID[:10]}-{label}"
        record = json.loads(_canonical_body(target_id))
        raw = json.dumps(record, indent=2).replace('"answer": "yes"',
                                                   f'"answer": {token}') + "\n"
        assert token in raw, f"{label}: the fixture planted no {token}"
        repo, target_id = _refused_target_repo(tmp_path, label, raw)
        rel = f"noni/decisions/{target_id}.json"
        committed = _git_e2(repo, "show", f"HEAD:{rel}").stdout
        renders: list[str] = []
        proc = _supersede_in_process(repo, write_fails_on=None, monkeypatch=monkeypatch,
                                     target_id=target_id, render_observer=renders.append)
        assert proc.returncode == 4, f"{label}: {proc.returncode}: {proc.stderr}"
        # The refusal names the target as unreadable rather than rewriting it: the
        # reader refuses the token, so no field check or canonical comparison is
        # reached and no bytes of this target are ever handed to the renderer.
        assert "not a readable JSON object" in proc.stderr, f"{label}: {proc.stderr}"
        assert _porcelain(repo) == "", f"{label}: a refused run writes nothing"
        assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), label
        assert (repo / rel).read_text(encoding="utf-8") == committed, label
        # No render of the planted record happened at all: a render that had
        # emitted the token (or quietly turned it into null) would have been written.
        assert all(token not in text and '"answer": null' not in text
                   for text in renders), (
            f"{label}: a render would have rewritten {token}: {renders}"
        )
        assert not any(target_id in text for text in renders), (
            f"{label}: the planted target reached the render: {renders}"
        )


def test_hardening_the_render_raises_on_a_non_finite_number(tmp_path, monkeypatch):
    """``_render`` raises ``ValueError`` for a non-finite float and hands back no bytes.

    The old renderer printed an exit-4 refusal through ``_fail`` and returned ``""``,
    which stopped nothing: the caller still received a string to write, and the exit
    code came from inside a renderer rather than from the run. The assertions of both
    former near-identical render tests are here and none is weakened: ``== ""``
    became "raised ``ValueError`` and returned nothing", and "one ``_fail`` call at
    exit 4" became "no ``_fail`` call at all" -- the stronger claim, because a refusal
    worded elsewhere cannot be mistaken for a rendered record. The finite positive
    control is kept unchanged.

    The render is the writer's last word, not its only guard: ``record_object``
    refuses a bare token or an overflowing literal when it reads a target, and the
    two callers of ``_render`` catch what still gets through (the canonical
    comparison in ``gitwrite.load_committed_target``, the write block in ``main``).
    What this test pins is that the renderer itself neither swallows the fault into
    an empty body nor publishes an exit code while doing it.
    """
    module = _decide_module()
    calls: list[tuple[int, str]] = []

    def _spy_fail(code, message, hint=None):
        # A named function rather than a lambda: the loop below rebinds ``calls``
        # per case, and a lambda would close over the name and not the value.
        calls.append((code, message))
        return 4

    monkeypatch.setattr(module, "_fail", _spy_fail)
    for bad in (float("nan"), float("inf"), float("-inf")):
        record = json.loads(_canonical_body(f"{BASELINE_ID[:10]}-render-{bad}"))
        record["questions"][0]["answer"] = bad
        calls.clear()
        rendered = "<not raised>"
        try:
            rendered = module._render(record)
        except ValueError:
            rendered = None
        assert rendered is None, f"{bad}: a non-finite record rendered to {rendered!r}"
        # Nothing is printed and no exit code is published: the render is not the
        # place a refusal is worded, and it does not swallow the fault into "".
        assert calls == [], f"{bad}: the render worded a refusal of its own: {calls}"
    # The positive control: a finite record still renders, unchanged in form.
    finite = json.loads(_canonical_body(f"{BASELINE_ID[:10]}-finite"))
    assert module._render(finite) == json.dumps(
        {key: finite[key] for key in module.FIELD_ORDER if key in finite},
        indent=2, ensure_ascii=False) + "\n"


def test_hardening_a_non_finite_number_in_any_field_refuses_with_four(tmp_path):
    """A target holding ``NaN``/``Infinity``/``-Infinity`` anywhere is refused (exit 4).

    The refusal is about the bytes, not the field: a target whose ``options``
    carried the token was read as a record, passed every field rule (a list of
    strings is a valid ``options`` value to the census) and reached the render,
    where a float json had read from a bare token would be refused or, under the
    default ``allow_nan``, written back as a token that is not JSON. The reader is
    what refuses now, so such a target "is not a readable JSON object" whatever
    field holds it, and no path is opened.
    """
    for label, token in (("nan", "NaN"), ("inf", "Infinity"), ("ninf", "-Infinity")):
        target_id = f"{BASELINE_ID[:10]}-options-{label}"
        # The token sits in an option, never an answer: the answer's float was
        # already refused by a field rule, and this is the field nothing checked.
        patched = _canonical_body(target_id).replace('"later"', f"{token}")
        assert token in patched, f"{label}: the fixture planted no {token}"
        stderr, repo, rel = _refuse_raw_target(tmp_path, f"options-{label}", patched)
        assert "not a readable JSON object" in stderr, f"{label}: {stderr}"
        assert _porcelain(repo) == "", f"{label}: a refused run must leave the tree alone"
        assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), label
        assert (repo / rel).read_text(encoding="utf-8") == patched, label


def test_hardening_a_target_with_an_overflowing_number_refuses_with_four(tmp_path):
    """A committed target whose JSON number overflows to infinity is refused
    (exit 4) with nothing written -- and it is refused, not crashed.

    ``1e400`` is legal JSON syntax, so ``parse_constant`` never sees it: the
    reader hands back an ``inf`` float and the writer crashed in the canonical
    comparison with a traceback at exit 1 (``ValueError: Out of range float
    values are not JSON compliant``). A number the writer cannot name is the
    same fact as the bare ``Infinity`` token that the reader already refused --
    the ledger holds a value no writer can emit -- and a target holding it must
    answer "not a readable JSON object". Both signs are planted (``1e400`` in
    ``by``, ``-1e999`` in ``scope``) because the token's sign decides which
    infinity json produces and only one arm was ever exercised before.
    """
    for label, token, field in (("overflow", "1e400", "by"),
                                ("negative-overflow", "-1e999", "scope")):
        needle = ('"by": "Replay",' if field == "by"
                  else '"scope": "release ordering",')
        patched = _canonical_body(f"{BASELINE_ID[:10]}-{label}").replace(
            needle, f'"{field}": {token},')
        assert token in patched, f"{label}: the fixture planted no {token}"
        stderr, repo, rel = _refuse_raw_target(tmp_path, label, patched)
        assert "Traceback" not in stderr, f"{label}: {stderr}"
        assert "not a readable JSON object" in stderr, f"{label}: {stderr}"
        assert _porcelain(repo) == "", f"{label}: a refused run must leave the tree alone"
        assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), label
        assert (repo / rel).read_text(encoding="utf-8") == patched, label


def test_hardening_record_object_refuses_a_non_finite_float_at_any_depth():
    """``record_object`` refuses a non-finite float wherever json put it.

    ``parse_constant`` refuses only the three bare tokens; a number literal that
    overflows (``1e999``) or underflows to a signed zero keeps no trace of the
    token it came from, so the walk of the parsed structure is what refuses it.
    Depth matters: a field check sees the top level, and an ``inf`` nested in a
    question's option (or any object in a list) reaches the render untouched
    otherwise. The finite control proves the walk is not a blanket refusal of
    every number -- a record with an integer and a finite float still parses.
    """
    gitwrite = _gitwrite_module()
    for body in (
        '{"by": 1e400}',
        '{"scope": -1e999}',
        '{"questions": [{"options": ["a", 1e999]}]}',
        '{"source": {"nested": {"deep": [1e999]}}}',
        '{"a": {"b": [null, 1e400]}}',
    ):
        assert gitwrite.record_object(body.encode("utf-8")) is None, body
    finite = '{"by": "Replay", "n": 42, "f": 1.5, "big": 1e3}'
    parsed = gitwrite.record_object(finite.encode("utf-8"))
    assert isinstance(parsed, dict), parsed
    assert parsed["big"] == 1000.0
    assert gitwrite.record_object(b'{"a": [1, 2]}') == {"a": [1, 2]}
    assert gitwrite.record_object(b'{"a": NaN}') is None


def test_hardening_an_unparseable_number_in_a_nested_field_refuses_with_four(tmp_path):
    """A number json read as infinity is refused (exit 4) in a *nested* field too.

    A top-level field check cannot see it: the value sits inside an option string's
    neighbour, in a list the census's own rules do not type. Before the reader walked
    the parsed structure such a target parsed to a dict, passed every field rule, and
    reached the canonical comparison, where ``allow_nan=False`` raised and the run
    died with a traceback at exit 1 -- the crash this round was written against, in
    the position the bare-token refusal never covered.

    The bytes are planted verbatim and pinned on disk first: if json ever stopped
    reading ``1e999`` as ``inf`` this fixture would plant a string and assert nothing.
    """
    for label, token in (("nested", "1e999"), ("negative", "-1e999")):
        target_id = f"{BASELINE_ID[:10]}-{label}"
        patched = _canonical_body(target_id).replace('"later"', f"{token}")
        assert f"{token}\n" in patched, f"{label}: the fixture planted no {token}"
        stderr, repo, rel = _refuse_raw_target(tmp_path, label, patched)
        assert "Traceback" not in stderr, f"{label}: {stderr}"
        assert "not a readable JSON object" in stderr, f"{label}: {stderr}"
        assert _porcelain(repo) == "", f"{label}: a refused run writes nothing"
        assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), label
        assert (repo / rel).read_text(encoding="utf-8") == patched, label


def test_hardening_a_target_field_of_the_wrong_type_refuses_with_four(tmp_path):
    """Every field the census types is checked on the target: ``id``,
    ``asked_by``, ``by``, ``scope``, ``date`` non-empty strings, ``status`` one of
    the three words the census allows, ``supersedes`` a string or null, and
    ``questions`` as before.

    The census refuses all of these ("id must be a non-empty string", etc.), so
    a ledger holding one was never clean, and the writer copies every one of
    these bytes when it flips a status. ``bool`` is the case an ``isinstance``
    test alone misses: Python calls ``True`` an ``int``, so without the explicit
    bool check a target with ``"by": true`` would pass as a number-shaped value
    -- and the census refuses it (``isinstance(value, str)`` is False for
    ``true``, and the string fields demand a string). ``"supersedes": 7`` is the
    census's "supersedes must be null or a non-empty string". ``status`` is the
    one field the census narrows past its type, to the three words it names, so
    ``""`` and ``"pending"`` join the shapes: both are census violations ("status
    not one of decided|open|superseded"), and only a membership test refuses them.
    """
    shapes = {
        "by-true": {"by": True},
        "by-false": {"by": False},
        "by-null": {"by": None},
        "by-int": {"by": 7},
        "by-empty": {"by": ""},
        "asked-by-true": {"asked_by": True},
        "asked-by-int": {"asked_by": 1},
        "asked-by-null": {"asked_by": None},
        "asked-by-empty": {"asked_by": ""},
        "id-true": {"id": True},
        "id-int": {"id": 1},
        "id-empty": {"id": ""},
        "scope-true": {"scope": True},
        "scope-int": {"scope": 1},
        "scope-null": {"scope": None},
        "scope-empty": {"scope": ""},
        "status-true": {"status": True},
        "status-null": {"status": None},
        "status-empty": {"status": ""},
        "status-pending": {"status": "pending"},
        "supersedes-int": {"supersedes": 7},
        "supersedes-true": {"supersedes": True},
        "supersedes-empty": {"supersedes": ""},
    }
    for label, patch in shapes.items():
        target_id = f"{BASELINE_ID[:10]}-{label}"
        stderr, _repo, _rel = _refuse_raw_target(
            tmp_path, label, _planted_body(target_id, **patch))
        if label.startswith("status-"):
            # The status rule is membership of a closed set, so "status" alone in
            # stderr would pass on any wording that merely named the field.
            assert "status not one of decided|open|superseded" in stderr, (
                f"{label}: {stderr}")
            continue
        field = label.split("-")[0].replace("asked", "asked_by")
        assert field in stderr, f"{label}: {stderr}"


def test_hardening_a_target_with_an_unknown_status_refuses_with_four(tmp_path):
    """The status words a target may hold come from the writer's own constants.

    ``targetschema`` typed ``status`` only as a string, so ``"pending"`` -- the word
    a hand-edited record would carry -- passed the target's own check and reached the
    flip. The allowed set now arrives from ``decide.py``'s ``STATUS_*`` constants (the
    way ``superseded`` arrives at ``refuse_live_record``), so a helper cannot keep its
    own list and quietly accept a status nothing writes: the refusal quotes that same
    tuple, and every status the writer itself produces is in it. The launches prove
    the set is the one the run applies, not a constant nobody reads: a target holding
    the writer's own ``superseded`` reaches the terminal-status refusal (the census
    accepts it, so it is not "unknown"), and one holding a word no constant names
    exits 4 quoting the set.
    """
    decide = _decide_module()
    assert decide.STATUSES == (decide.STATUS_DECIDED, decide.STATUS_OPEN,
                               decide.STATUS_SUPERSEDED), decide.STATUSES
    assert decide.STATUSES == ("decided", "open", "superseded"), decide.STATUSES
    for label, value in (("pending", "pending"), ("archived", "archived")):
        target_id = f"{BASELINE_ID[:10]}-status-{label}"
        stderr, _repo, _rel = _refuse_raw_target(
            tmp_path, f"status-{label}", _planted_body(target_id, status=value))
        assert "status not one of decided|open|superseded" in stderr, f"{label}: {stderr}"
    accepted = f"{BASELINE_ID[:10]}-status-writer"
    stderr, _repo, _rel = _refuse_raw_target(
        tmp_path, "status-writer",
        _planted_body(accepted, status=decide.STATUS_SUPERSEDED))
    assert "is already superseded" in stderr, stderr
    assert "status not one of" not in stderr, stderr
def test_hardening_docs_state_the_refusals_the_code_performs(tmp_path):
    """The docstring's exit 4 table and exit 3's hint are what the code does.

    The old wording claimed a target "belongs to another chain" (nothing
    refuses that) and omitted the two refusals the hardening round added, so a
    reader of the table could not predict a run's exit code. The hint text is
    checked against the runtime hint for the same reason: a doc that names a
    different command than the one stderr names is two contracts, one stale.
    """
    doc = _docstring(_decide_ast())
    lines = doc.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "Exit codes:")
    block: dict[int, str] = {}
    current: int | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif current is not None:
            block[current] += " " + line.strip()
    four = block[4].lower()
    for condition in ("missing", "already superseded", "untracked", "locally modified",
                      "canonical", "another day", "outside decided, open or superseded"):
        assert condition in four, f"docstring's exit 4 omits {condition!r}: {block[4]}"
    three = block[3].lower()
    assert "is not a git work tree" in three
    assert "git config user.name is not set" in three
    # The runtime hint for the identity refusal is the same wording, not a
    # different command: doc and stderr say one thing.
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, env=_no_identity_env(tmp_path), identity=None)
    assert proc.returncode == 3, proc.stderr
    assert "git config user.name is not set" in proc.stderr, proc.stderr
    # Same for the timeout hint: the table promises a git probe that timed out is
    # a git problem, and the runtime message says so and names the command.
    module = _decide_module()
    hung = f"git rev-parse timed out after {module.GIT_TIMEOUT}s"
    timed = _decide_in_process(repo, *ANSWERED, env=_identity_env(),
                               failures={"rev-parse": (module.GIT_TIMEOUT_RC, hung)})
    assert timed.returncode == 3, timed.stderr
    assert "timed out" in timed.stderr and "rev-parse" in timed.stderr, timed.stderr
