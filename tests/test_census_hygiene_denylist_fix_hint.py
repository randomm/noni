"""Which hygiene row gets which fix hint (issue #237).

Before this issue no test pinned the value of any hygiene fix hint: both renderers
read the one per-class hint out of the class table, and a tree with no deny-list
under ``--strict`` told the reader to remove a personal path and rewrite history
when nothing had been found in any file. The only problem was that no deny-list is
configured, so the remedy is a different one, and nothing in the suite could tell
the two apart.

This module is the first pin of either hint, by value read from the product and
never by a typed copy: the inactive row's remedy is
``census_report.HYGIENE_DENYLIST_INACTIVE_FIX`` and every other hygiene row's is
``CLASS_FIX["hygiene"]``. Both branches are pinned, because the two renderers used
to read the class table independently and a hint that reached only one of them
would leave ``--json`` and the human report disagreeing about the same row.

Both deny-list routes are closed through ``tests/census_denylist.py``
(``_with_no_denylist``, monkeypatch-based and self-restoring) and opened through
``_with_denylist``, so no test here bends a module attribute by hand and leaks the
bend into a later census run in the same process.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _init_repo, _secret_violation
from census_denylist import _clear_denylist, _with_denylist, _with_no_denylist
from census_fixtures import _ndjson_rows, _valid_record
from census_run import _run_census

# The hint of a row whose deny-list was configured and gave no verdict, and the
# per-class hint of every other hygiene row. Read from the product, never retyped
# here: a copy would keep passing after a reword that this file exists to notice.
_SECRET = _secret_violation()

# The two routes the note spells, which the inactive hint must name.
_ROUTE_ENV = "NONI_SCRUB_DENYLIST"
_ROUTE_FILE = ".noni-scrub-denylist"

# The words of the per-class hint that belong to a real finding only: a row that
# found nothing in any file must not tell the reader to hunt one down.
_REMOVAL_WORDS = ("remove the personal path", "rewrite history")


def _clean_repo(tmp_path, name: str):
    """A committed tree with a record and one README, so the scan has a file to read.

    The README is the control for the planted-violation case: a tree whose only
    hygiene row is the deny-list one is a tree whose scan found nothing.
    """
    repo = _init_repo(tmp_path / name)
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _commit_file(repo, "README.md", "reader\n")
    return repo


def _hygiene_rows(out: str) -> list[dict]:
    return [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]


def _human_fix_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if " fix: " in line]


def test_inactive_deny_list_json_fix_names_both_routes(tmp_path, monkeypatch):
    """``--json``: the inactive row's fix names the missing list and both routes.

    The state the pilot hit: ``--only hygiene --strict`` over a tree with no
    deny-list at all. The row says what was not covered; its fix now says what is
    missing and how to switch the check on, in the two routes the default-mode
    note already uses.
    """
    from noni import census_report

    repo = _clean_repo(tmp_path, "repo")
    _with_no_denylist(monkeypatch, tmp_path)
    rc, out, err = _run_census(repo, "--only", "hygiene", "--strict", json_out=True)
    assert rc == 50, f"an inactive deny-list still fails under --strict: {rc}\n{out}{err}"
    rows = _hygiene_rows(out)
    assert [r["subject"] for r in rows] == ["deny-list"], rows
    assert rows[0]["fix"] == census_report.HYGIENE_DENYLIST_INACTIVE_FIX, rows[0]
    for route in (_ROUTE_ENV, _ROUTE_FILE):
        assert route in rows[0]["fix"], f"the hint must name {route}: {rows[0]}"


def test_inactive_deny_list_human_fix_names_both_routes(tmp_path, monkeypatch):
    """The human branch prints the same fix line as ``--json`` for the same row.

    The two renderers read the hint through one function, so a run cannot say one
    remedy in machine mode and the other in a terminal. The machine row is asserted
    here too, and compared to the printed line, which is the half that catches an
    override applied to one branch only.
    """
    from noni import census_report

    repo = _clean_repo(tmp_path, "repo")
    _with_no_denylist(monkeypatch, tmp_path)
    rc, human, err = _run_census(repo, "--only", "hygiene", "--strict")
    assert rc == 50, f"{rc}\n{human}{err}"
    lines = _human_fix_lines(human)
    assert len(lines) == 1, f"the run has one row, so one fix line: {human}"
    assert lines[0].strip() == f"fix: {census_report.HYGIENE_DENYLIST_INACTIVE_FIX}", (
        f"{lines[0]!r}\n{human}")
    for route in (_ROUTE_ENV, _ROUTE_FILE):
        assert route in lines[0], f"the hint must name {route}: {lines[0]!r}"
    _rc, out, _err = _run_census(repo, "--only", "hygiene", "--strict", json_out=True)
    assert _hygiene_rows(out)[0]["fix"] in lines[0], (
        f"the two modes gave the same row different remedies: {lines[0]!r} vs "
        f"{_hygiene_rows(out)[0]}")


def test_inactive_hint_carries_no_removal_wording(tmp_path, monkeypatch):
    """The inactive row does not tell the reader to remove a path or rewrite history.

    Nothing was found in any file on this tree, so a hint about a personal path
    sends the reader hunting for a finding the run did not report. The per-class
    hint does carry those words, so the negative half is only worth anything next
    to the positive one: the class hint itself is read here and shown to name the
    removal, which is what stops "no removal wording" passing because a constant
    went empty.
    """
    from noni import census_report

    class_hint = census_report.CLASS_FIX["hygiene"]
    assert all(word in class_hint for word in _REMOVAL_WORDS), (
        f"the per-class hint no longer says what this test subtracts from it: "
        f"{class_hint}")

    repo = _clean_repo(tmp_path, "repo")
    _with_no_denylist(monkeypatch, tmp_path)
    _rc, human, _err = _run_census(repo, "--only", "hygiene", "--strict")
    _rc2, out, _err2 = _run_census(repo, "--only", "hygiene", "--strict", json_out=True)
    fix = _hygiene_rows(out)[0]["fix"]
    assert fix != class_hint, f"the inactive row still prints the class hint: {fix}"
    for word in _REMOVAL_WORDS:
        assert word not in fix, f"the inactive row's hint says {word!r}: {fix}"
        assert word not in human, f"the human report says {word!r}: {human}"


def test_inactive_hint_names_the_routes_the_note_uses():
    """The remedy and the note name the same two routes, spelled the same way.

    The default run says the check is off in a note; ``--strict`` says it in a row.
    One reader should meet one spelling of the switch in both, so the two are
    compared against the note the product already prints rather than against words
    typed here.
    """
    from census_hygiene import HYGIENE_DENYLIST_NOTE

    from noni import census_report

    hint = census_report.HYGIENE_DENYLIST_INACTIVE_FIX
    for route in (_ROUTE_ENV, _ROUTE_FILE):
        assert route in HYGIENE_DENYLIST_NOTE, HYGIENE_DENYLIST_NOTE
        assert route in hint, hint
    # The note's other half belongs to the note: a fix hint that restates what
    # went unchecked says nothing about what to do.
    assert "no entry was checked" not in hint, hint
    assert "were not checked" not in hint, hint


def test_every_inactive_state_gets_the_inactive_hint(tmp_path, monkeypatch):
    """All three inactive states share the remedy, not just ``absent``.

    ``corrupt`` and ``present but empty`` were configured and gave no verdict, and
    the reader's problem is the same in each: the list the check needed was not
    there in a usable form. A per-row hint keyed on one state word would leave the
    other two telling the reader to rewrite history.
    """
    from census_hygiene import DENYLIST_INACTIVE_MESSAGE
    from census_hygiene_target import _hygiene_target

    from noni import census_report

    states = {
        "absent": None,
        "corrupt": b"\xff\xfe\x00\x01not utf8",
        "present but empty": b"# only a comment\n",
    }
    public_safety = _hygiene_target()
    for state, content in states.items():
        repo = _clean_repo(tmp_path, f"repo-{state.replace(' ', '-')}")
        if content is None:
            _with_no_denylist(monkeypatch, repo.parent)
        else:
            listed = tmp_path / f"denylist-{state.replace(' ', '-')}.txt"
            listed.write_bytes(content)
            monkeypatch.delenv("NONI_SCRUB_DENYLIST", raising=False)
            monkeypatch.setattr(public_safety, "_default_denylist_file",
                                lambda repo, path=listed: path)
        rc, out, err = _run_census(repo, "--only", "hygiene", "--strict", json_out=True)
        assert rc == 50, f"{state}: expected the inactive row to fail --strict: " \
                        f"{rc}\n{out}{err}"
        rows = _hygiene_rows(out)
        assert [r["subject"] for r in rows] == ["deny-list"], f"{state}: {rows}"
        row = rows[0]
        assert DENYLIST_INACTIVE_MESSAGE.format(state=state) == row["message"], (
            f"{state}: the row text is the product's and is unchanged: {row}")
        assert row["fix"] == census_report.HYGIENE_DENYLIST_INACTIVE_FIX, (
            f"{state}: {row}")


def test_a_real_finding_keeps_the_per_class_hint(tmp_path):
    """The control: a planted secret still prints the per-class hint, byte for byte.

    The deny-list is activated so this run owes no deny-list row at all, which is
    what leaves the planted violation as the run's only hygiene row: an inactive
    class is exactly the state a reader must not mistake for a clean scan, so the
    absence of that row is asserted as part of the control. The hint the violation
    prints is the class table's, unchanged, and it names the removal the reader
    actually has to do.
    """
    from noni import census_report

    repo = _clean_repo(tmp_path, "repo")
    _commit_file(repo, "note.md", "token " + _SECRET + "\n")
    _with_denylist(tmp_path, "synthetic-project-name")
    try:
        rc, out, err = _run_census(repo, "--only", "hygiene", "--strict",
                                   json_out=True)
        assert rc == 50, f"a planted violation fails under --strict: {rc}\n{out}{err}"
        rows = _hygiene_rows(out)
        assert len(rows) == 1, f"an active deny-list owes no inactive row: {rows}"
        row = rows[0]
        assert row["subject"] != "deny-list", (
            f"a run carrying the inactive row is not a clean scan: {row}")
        assert row["fix"] == census_report.CLASS_FIX["hygiene"], row
        assert row["fix"] != census_report.HYGIENE_DENYLIST_INACTIVE_FIX, row
        _rc, human, _err = _run_census(repo, "--only", "hygiene", "--strict")
        lines = _human_fix_lines(human)
        assert lines == [f"{'':<16} fix: {census_report.CLASS_FIX['hygiene']}".rstrip()], (
            f"the human branch moved the per-class hint: {lines}")
    finally:
        _clear_denylist()


def test_a_not_run_row_keeps_the_class_hint(tmp_path, monkeypatch):
    """The ``hygiene scan`` not-run row keeps the class hint the deny-list row no longer uses.

    Both rows are the class's whole-artifact rows: one artifact, and the deny-list
    subject is the class's other subject-only discriminator, so a hint keyed on the
    class alone, the artifact alone or the subject alone would re-hint the wrong
    row. A run cannot produce both at once -- a scan that faults reports itself and
    never reaches the deny-list half -- so each row comes from its own tree, and
    only the faulted one has its scan bent.
    """
    from census_hygiene_target import _hygiene_target

    from noni import census_report

    _with_no_denylist(monkeypatch, tmp_path)
    faulted_repo = _clean_repo(tmp_path, "faulted")
    public_safety = _hygiene_target()

    def _faulted(repo, patterns, exempt):
        raise OSError(5, "input/output error")

    monkeypatch.setattr(public_safety, "_scan_tracked_files", _faulted)
    rc, out, err = _run_census(faulted_repo, "--only", "hygiene", "--strict",
                               json_out=True)
    assert rc == 50, f"a faulted scan still fails under --strict: {rc}\n{out}{err}"
    rows = _hygiene_rows(out)
    assert [r["subject"] for r in rows] == ["hygiene scan"], (
        f"a scan that faults reports itself and stops: {rows}")
    not_run = rows[0]
    assert "did not run" in not_run["message"], not_run
    assert not_run["fix"] == census_report.CLASS_FIX["hygiene"], not_run

    # The sibling row, from a tree whose scan ran: same class, same filter, same
    # artifact, and only the deny-list row changes hint.
    monkeypatch.undo()
    _with_no_denylist(monkeypatch, tmp_path)
    quiet_repo = _clean_repo(tmp_path, "quiet")
    rc, out, err = _run_census(quiet_repo, "--only", "hygiene", "--strict",
                               json_out=True)
    assert rc == 50, f"{rc}\n{out}{err}"
    inactive = _hygiene_rows(out)[0]
    assert inactive["subject"] == "deny-list", inactive
    assert inactive["artifact"] == not_run["artifact"], (
        f"both rows are whole-artifact rows, which is the trap here: {inactive}")
    assert inactive["fix"] == census_report.HYGIENE_DENYLIST_INACTIVE_FIX, inactive


def test_the_inactive_hint_names_the_state_the_row_names():
    """The hint remedies the state the row names, rather than repeating it.

    The row already says which state it is in (``absent``, ``corrupt``, ``present but
    empty``), so the hint's job is the remedy. It must stay a sentence a reader can
    act on and not turn into a second copy of the row: naming the state is the row's,
    and the hint's own words are the two routes and the fact that no entry ran.
    """
    from census_hygiene import DENYLIST_INACTIVE_MESSAGE

    from noni import census_report

    hint = census_report.HYGIENE_DENYLIST_INACTIVE_FIX
    prefix = DENYLIST_INACTIVE_MESSAGE.split("{state}", 1)[0]
    assert not hint.startswith(prefix), (
        f"the hint restates the row it sits under: {hint}")
    assert "class inactive" not in hint, hint
    assert "deny-list entry was checked" not in hint, hint


def test_an_unconfigured_tree_still_says_the_note_without_strict(tmp_path, monkeypatch):
    """The default behaviour is unchanged: no row, no exit code, one note.

    The bug was in the row ``--strict`` keeps. A run without the flag must still
    report no hygiene row for the deny-list half and still exit clean, so the new
    hint cannot have turned the note into a finding or given the note a remedy to
    carry. The note is the product's own constant, and the hint is not in it: two
    channels, two sentences, and neither borrowed from the other.
    """
    from census_hygiene import HYGIENE_DENYLIST_NOTE

    from noni import census_report

    repo = _clean_repo(tmp_path, "repo")
    _with_no_denylist(monkeypatch, tmp_path)
    rc, human, err = _run_census(repo, "--only", "hygiene")
    assert rc == 0, f"an unconfigured deny-list is still not a failure: {rc}\n{human}{err}"
    assert f"note: {HYGIENE_DENYLIST_NOTE}" in human, human
    assert _human_fix_lines(human) == [], f"a run with no row prints no fix line: {human}"
    _rc, out, _err = _run_census(repo, "--only", "hygiene", json_out=True)
    assert _hygiene_rows(out) == [], "the default run still owes no deny-list row"
    assert census_report.HYGIENE_DENYLIST_INACTIVE_FIX not in out, (
        f"the row's remedy leaked into the note's channel: {out}")


def test_the_inactive_hint_is_not_the_class_hint():
    """The two remedies are distinct constants, and the class table is untouched.

    ``CLASS_FIX["hygiene"]`` stays the hint of every other row of the class, so the
    new hint is a separate constant with one named owner rather than an edit of the
    table's hygiene entry.
    """
    from noni import census_report

    assert census_report.CLASS_FIX["hygiene"] != census_report.HYGIENE_DENYLIST_INACTIVE_FIX
    assert census_report.CHECKS["hygiene"][2] is census_report.CLASS_FIX["hygiene"]
    assert "keep the local deny-list present" in census_report.CLASS_FIX["hygiene"], (
        "the per-class hint was reworded; it is out of this issue's scope")


def test_no_hygiene_row_of_a_clean_run_prints_the_inactive_hint(tmp_path, monkeypatch):
    """The new hint belongs to the inactive row and to no other row of the run.

    A selector keyed too loosely (a class test, or a prefix read off the wrong
    constant) would hand the deny-list remedy to rows that reported something else.
    The whole run is walked here, over a tree with a planted violation and an active
    deny-list, and every hygiene row of it -- including one carrying a real finding
    -- keeps the class hint.
    """
    from noni import census_report

    repo = _clean_repo(tmp_path, "repo")
    _commit_file(repo, "note.md", "token " + _SECRET + "\n")
    _with_denylist(tmp_path, "synthetic-project-name")
    try:
        rc, out, err = _run_census(repo, "--strict", json_out=True)
        assert rc == 50, f"the planted violation decides the exit: {rc}\n{out}{err}"
        rows = _ndjson_rows(out)
        assert [r["kind"] for r in rows] == [
            r["kind"] for r in rows], "every row of a census run carries a kind"
        hygiene = [r for r in rows if r.get("check") == "hygiene"]
        assert len(hygiene) >= 1, f"the planted violation owes a hygiene row: {rows}"
        wrong = [r["subject"] for r in hygiene
                 if r["fix"] == census_report.HYGIENE_DENYLIST_INACTIVE_FIX]
        assert wrong == [], f"rows that are not the inactive deny-list row: {wrong}"
    finally:
        _clear_denylist()


def test_the_inactive_hint_hints_nothing_and_names_no_path(tmp_path, monkeypatch):
    """No host path in the new hint, in either mode.

    The census never prints a machine-local absolute path the operator did not
    type, and a hint naming a config file is the shape most likely to.
    """
    repo = _clean_repo(tmp_path, "repo")
    _with_no_denylist(monkeypatch, tmp_path)
    _rc, human, _err = _run_census(repo, "--only", "hygiene", "--strict")
    _rc2, out, _err2 = _run_census(repo, "--only", "hygiene", "--strict", json_out=True)
    for text in (human, out):
        assert str(repo) not in text, f"a host path reached the report: {text!r}"
        assert "home/" not in text, f"a home path reached the report: {text!r}"
