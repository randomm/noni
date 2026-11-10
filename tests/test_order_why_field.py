"""The order entry's ``why`` field: one bounded line of reason for a position.

``order add --why REASON`` records why the operator wants the position. The field is
optional, so an entry written without it renders the bytes the artifact held before it
existed, and it obeys the same rule a decision record's rationale obeys: one non-blank
line within the bound ``_why.WHY_MAX`` states.

Checked here: the flag (exit 2, nothing written), the artifact (the ``/1`` shape and the
key order), the two verbs that rebuild an entry (a move and a confirm keep the reason),
and both censuses (which report a hand-edited ``why`` naming the field). The shared
shape table (``tests/ordering_shapes.py``) holds the writer/arbiter agreement.
"""

import pytest
from ledger_schema_fixtures import product_why_max
from order_fixtures import (
    BASELINE_ID,
    NOW,
    SKILL_DIR,
    _assert_census_clean,
    _docstring,
    _entry,
    _order,
    _order_ast,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
)
from ordering_shapes import CLEAN_SHAPES, MALFORMED_SHAPES

# Read from the product (``_why.WHY_MAX``) and not spelled here: a copy taken at
# import time is a second owner of the number, and the suite would stay green the day
# the owner moved.
WHY_MAX = product_why_max()
FIELD = "why"
REASON = "the train leaves at six and nothing else is ready"


def _entries(repo) -> list[dict]:
    return _read(repo)["entries"]


def _add(repo, issue: int, *extra: str):
    """One ``add`` of ``issue`` with the flags given, at the pinned clock."""
    return _order(repo, "add", str(issue), "--decision", BASELINE_ID, "--now", NOW,
                  *extra)


def test_the_reason_lands_last_and_the_version_stays_one(tmp_path):
    """The reason is the entry's last key and it does not restamp the artifact's
    version: a reason is a field of an entry, not a new shape of the document, so an
    order of issues that carries one stays ``noni.order/1``.

    The mutation it survives: a writer that treated ``why`` as a ``/2`` marker, which
    would restamp every order that ever recorded a reason and make the census's
    staleness window read a plain queue as a rewritten one.
    """
    repo = _repo(tmp_path)

    proc = _add(repo, 42, f"--{FIELD}", REASON)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    body = _read(repo)
    assert body["schema"] == "noni.order/1"
    assert list(body["entries"][0]) == ["issue", "decision", "confirmed", FIELD]
    assert body["entries"][0][FIELD] == REASON
    _assert_census_clean(repo, "an entry with a reason")


def test_an_add_without_the_flag_writes_the_entry_it_always_wrote(tmp_path):
    """The byte-for-byte claim. An entry with no reason holds the three fields it held
    before #122, and the file's bytes are what the writer rendered before the field
    existed.

    The mutation it survives: writing ``"why": null`` for a run that named no reason,
    which would restamp every order on its next write and make an unchanged queue read
    as changed. The renderer check is what makes it the canonical form rather than one
    code path's habit.
    """
    repo = _repo(tmp_path)

    first = _add(repo, 42)
    assert first.returncode == 0, first.stderr
    second = _add(repo, 43)
    assert second.returncode == 0, second.stderr

    assert [list(entry) for entry in _entries(repo)] == [
        ["issue", "decision", "confirmed"],
        ["issue", "decision", "confirmed"],
    ]
    from order_fixtures import _schema_module

    rendered = _schema_module().order_bytes(_read(repo))
    assert rendered.decode().encode() == _order_path(repo).read_bytes()


def test_the_bound_is_the_shared_one_and_counts_characters(tmp_path):
    """The bound's length is a reason and one code point past it is not, measured in the
    characters the operator counts rather than bytes: a bound's length of accented
    characters is accepted where a byte count would refuse them.

    The bound has one owner (``_why.WHY_MAX``); these runs are what say this
    artifact reads that owner rather than a copy of the number.
    """
    repo = _repo(tmp_path)

    at_limit = _add(repo, 42, f"--{FIELD}", "a" * WHY_MAX)
    over = _add(repo, 43, f"--{FIELD}", "a" * (WHY_MAX + 1))
    wide = _add(repo, 44, f"--{FIELD}", "\u00e9" * WHY_MAX)

    assert at_limit.returncode == 0, at_limit.stdout + at_limit.stderr
    assert wide.returncode == 0, wide.stdout + wide.stderr
    assert _entries(repo)[0][FIELD] == "a" * WHY_MAX
    assert _entries(repo)[1][FIELD] == "\u00e9" * WHY_MAX
    assert over.returncode == 2, over.stdout + over.stderr
    assert str(WHY_MAX) in over.stderr


@pytest.mark.parametrize("reason", ["", "   ", "one\ntwo", "one\r\ntwo", "\ntail"])
def test_a_reason_that_is_not_one_bounded_line_is_refused_at_the_flag(
        tmp_path, reason):
    """Blank, whitespace-only, or carrying any line break: exit 2, the flag named, and
    the order untouched -- no entry, no commit, nothing staged.

    A reason is one sentence about one position; anything else is the caller's mistake.
    The break spellings are separate cases because a value that reached the file with a
    break inside would break the report that prints one field per line.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7))
    before = _order_path(repo).read_bytes()

    proc = _add(repo, 42, f"--{FIELD}", reason)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--why" in proc.stderr and FIELD in proc.stderr
    assert _order_path(repo).read_bytes() == before
    assert _porcelain(repo) == ""


def test_the_over_long_refusal_states_the_number_to_cut_to(tmp_path):
    """The over-long refusal is actionable: it states the length the operator wrote, the
    number they have to cut to, and the flag to cut it from.

    The number is the one thing the operator cannot see in their own shell, and a
    refusal that said only "invalid" would cost them a second run to learn which rule
    broke.
    """
    repo = _repo(tmp_path)

    proc = _add(repo, 42, f"--{FIELD}", "a" * (WHY_MAX + 1))

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--why" in proc.stderr
    assert str(WHY_MAX) in proc.stderr and str(WHY_MAX + 1) in proc.stderr
    assert "shorten" in proc.stderr


def test_the_flag_belongs_to_add_alone(tmp_path):
    """A reason answers the taking of a position, so only ``add`` accepts one. Every
    other verb handed a reason is refused at exit 2 rather than dropping what the
    operator typed.

    The silent alternative is the bug: ``move 7 --to 1 --why ...`` that quietly ignored
    the reason would leave the operator believing a reason had been recorded.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7), _entry(8))

    for verb, args in (("move", ("move", "7", "--to", "1")),
                       ("remove", ("remove", "7")),
                       ("confirm", ("confirm", "7"))):
        proc = _order(repo, *args, "--now", NOW, f"--{FIELD}", REASON)
        assert proc.returncode == 2, f"{verb}: {proc.stdout}{proc.stderr}"
        assert "--why" in proc.stderr and verb in proc.stderr
    assert _porcelain(repo) == ""


def test_a_move_keeps_the_reason_and_restamps_only_the_time(tmp_path):
    """A reorder restamps when the position was confirmed, never why it was wanted: the
    moved entry keeps its ``why`` byte for byte and gains only a fresh ``confirmed``, so
    reordering cannot delete an operator's record as a side effect.

    The mutation it survives: rebuilding the moved entry from the three fields the
    writer knew before #122, which would silently drop the reason on every move.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7), _entry(8, confirmed="2026-10-01T00:00:00Z"))
    _add(repo, 9, f"--{FIELD}", REASON)
    before = _entries(repo)[2]

    proc = _order(repo, "move", "9", "--to", "1", "--now", NOW)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    moved = _entries(repo)[0]
    assert moved["issue"] == 9
    assert moved[FIELD] == before[FIELD] == REASON
    assert moved["confirmed"] == NOW
    assert list(moved) == ["issue", "decision", "confirmed", FIELD]
    _assert_census_clean(repo, "a move of an entry carrying a reason")


def test_a_confirm_keeps_the_reason_of_every_entry_it_restamps(tmp_path):
    """Confirming the queue restamps every entry and drops nothing: a reason recorded at
    the moment a position was taken survives every later confirmation.

    Same class as the move test, different code path -- confirm rebuilds all the entries
    rather than one, so it is the one that would lose a reason from the whole file.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7), _entry(8, confirmed="2026-10-01T00:00:00Z"))
    _add(repo, 9, f"--{FIELD}", REASON)

    proc = _order(repo, "confirm", "--now", NOW)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _entries(repo)[2][FIELD] == REASON
    assert all(entry["confirmed"] == NOW for entry in _entries(repo))
    _assert_census_clean(repo, "a confirm over an entry carrying a reason")


def test_the_help_usage_and_the_skill_all_name_the_flag(tmp_path):
    """``--why`` is discoverable where a caller looks: the parser's help, the
    ``Usage:`` block of the writer's docstring, and the direction skill's command
    block all spell it, and the skill states the rule the value answers to.

    A flag no text names is a flag nobody finds, and two documents that disagree with
    the parser are the bug these assertions exist to prevent.
    """
    repo = _repo(tmp_path)
    help_run = _order(repo, "--help")

    assert "--why REASON" in help_run.stdout

    doc = _docstring(_order_ast())
    assert f"[--{FIELD} REASON]" in doc
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert f"[--{FIELD} REASON]" in skill
    assert "`--why` belongs to `add` alone" in skill


def test_the_shape_table_holds_the_rationale_on_both_sides():
    """The shared table carries the rationale for the writer and the arbiter together:
    every bad ``why`` is a row the census must report and the writer must refuse, and a
    well-formed one is a clean shape neither side may reject.

    A writer-emitted entry the arbiter called malformed would be an order no verb can
    rewrite, so the two halves of this assertion fail together or not at all.
    """
    why_bad = {label: (body, needle) for label, (body, needle)
               in MALFORMED_SHAPES.items() if f'"{FIELD}"' in body}
    assert len(why_bad) >= 5, sorted(why_bad)
    assert all(needle == FIELD for needle, in ((n,) for _b, n in why_bad.values()))

    why_clean = {label: body for label, body in CLEAN_SHAPES.items()
                 if f'"{FIELD}"' in body}
    assert len(why_clean) >= 2, sorted(why_clean)
