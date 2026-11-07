"""The census's account of a --repo that holds no noni/, and the page that owes it.

Split from tests/test_state_root_refusal.py, which holds the entry points' exit codes.
This half is what the arbiter and the docs say about the same state the writers refuse:
the census reports a no-noni/ tree in words and moves no exit code (a no-noni/ tree is
warn-tier today), and docs/PRODUCT.md §7 is the prose both sides are transcribed from.
The three are pinned together here because the ticket's failure mode is exactly one of
the three drifting: a census that stayed silent read as "a project that has not
steered yet", and a §7 that dropped a creator reads as "your first decide is broken".
"""

from __future__ import annotations

import subprocess
import sys

from _harness import CENSUS, REPO, subprocess_env
from test_state_root_refusal import DOCUMENTED, NOT_A_STATE_ROOT_WORDS, _code_repo


def test_the_census_notes_a_repo_that_holds_no_noni_directory(tmp_path):
    """The census says plainly that --repo holds no noni/, ahead of its rows.

    The census changes no exit code here (ledger-empty is a warn and hygiene is a
    warn, so a no-noni/ tree exits 0 today), which is exactly why the state needs
    its own sentence: two warn rows about absent artifacts read as a project that
    has not steered yet, not as a caller who named the wrong tree. The note is the
    first line of stdout, so it is met before any row could be mistaken.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "census-no-noni")
    proc = subprocess.run([sys.executable, str(CENSUS), "--repo", str(repo)],
                          capture_output=True, text=True, env=subprocess_env(),
                          cwd=str(cwd), timeout=120)
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert lines, "the census printed no report at all"
    assert lines[0].startswith("note: "), (
        f"the no-noni/ note must be the first line, ahead of every row: {lines[:3]}")
    assert "no noni/ directory was found under --repo" in lines[0], lines[0]
    assert str(repo) in lines[0], f"the note must name the path: {lines[0]}"
    assert lines[-1].startswith("summary: ") and lines[-1].endswith("verdict ok"), (
        f"the verdict line must stay the last line of stdout: {lines[-1:]!r}")
    # The rows it does not replace: ledger-empty still reports its own state word.
    assert any("ledger-empty" in line and "absent" in line for line in lines), lines


def test_the_census_note_rides_the_json_summary_row_and_moves_no_exit_code(tmp_path):
    """--json carries the same sentence and stays a closed two-kind stream.

    The NDJSON contract is the reason this is a note and not a row: a third row kind
    or a new check class would widen the stream every consumer parses, and a row of a
    new class would change the exit code of a tree that today exits 0 (and 42 under
    --strict for a run naming ledger-empty). Both halves are asserted here.
    """
    import json

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "census-no-noni-json")
    proc = subprocess.run([sys.executable, str(CENSUS), "--repo", str(repo), "--json"],
                          capture_output=True, text=True, env=subprocess_env(),
                          cwd=str(cwd), timeout=120)
    assert proc.returncode == 0, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    kinds = {row.get("kind") for row in rows}
    assert kinds <= {"finding", "summary"}, f"an illegal row kind appeared: {kinds}"
    summaries = [row for row in rows if row.get("kind") == "summary"]
    assert len(summaries) == 1, summaries
    carried = summaries[0].get("not_evaluated")
    assert isinstance(carried, list) and carried, (
        f"--json must carry the note the human report prints: {summaries[0]}")
    assert any("no noni/ directory was found under --repo" in str(line)
               for line in carried), carried


def test_the_census_note_is_silent_when_a_path_override_names_the_state(tmp_path):
    """No note when --ledger (or sessions/ordering/intent) points at the real state.

    The four overrides replace the path under the state root rather than selecting it,
    so a caller who keeps the ledger beside an unrelated --repo is not wrong, and
    telling them their --repo holds no noni/ would be a true sentence answering the
    wrong question.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "census-override")
    outside = tmp_path / "state" / "noni" / "decisions"
    outside.mkdir(parents=True)
    proc = subprocess.run([sys.executable, str(CENSUS), "--repo", str(repo),
                           "--ledger", str(outside)],
                          capture_output=True, text=True, env=subprocess_env(),
                          cwd=str(cwd), timeout=120)
    assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stdout.replace(
        "no noni/ directory was found", NOT_A_STATE_ROOT_WORDS[0]), (
        f"an --ledger override means the state need not live under --repo: "
        f"{proc.stdout}")
    assert "no noni/ directory was found under --repo" not in proc.stdout, proc.stdout


def test_product_md_names_the_code_each_tool_owes():
    """The prose itself carries the codes, so the table above has a source.

    Read from docs/PRODUCT.md rather than restated here: a §7 that dropped a tool
    or changed a number fails this test instead of quietly disagreeing with the
    runs above.
    """
    text = (REPO / "docs" / "PRODUCT.md").read_text(encoding="utf-8")
    for code, names in DOCUMENTED.items():
        for name in names:
            assert name in text, f"docs/PRODUCT.md no longer names {name}"
        assert f"{code} for" in text, (
            f"docs/PRODUCT.md §7 must name the tools that answer exit {code} for a "
            "--repo that is not a directory"
        )


def test_product_md_states_the_no_noni_refusal_with_the_creators_excepted():
    """§7 owes the second wrong-path state its own paragraph, with its exceptions.

    The ticket's own risk is a page that documents the refusal and quietly drops which
    verbs may still create the tree: an operator who reads only the refusal stops
    running their first `decide`. So the paragraph is located by the phrase only it
    carries and checked for the state, the note the census owes instead of a row, and
    each creator by name.
    """
    text = (REPO / "docs" / "PRODUCT.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    paragraphs = [p.strip() for p in text.split("\n\n")
                  if "not a noni state root" in " ".join(p.split())]
    assert len(paragraphs) == 1, (
        f"docs/PRODUCT.md §7 should carry the no-noni/ refusal in exactly one "
        f"paragraph, found {len(paragraphs)}")
    paragraph = " ".join(paragraphs[0].split())
    for phrase in ("no `noni/`", "`order`", "`intent`", "`add`", "`intent set`",
                   "`decide`", "--repo"):
        assert phrase in paragraph, f"§7's no-noni/ paragraph omits {phrase!r}: {paragraph}"
    assert "noni state root" in flat
    assert "no noni/ directory was found under --repo" in flat or \
        "no `noni/` directory" in flat, (
        "§7 must also state the census's note for this state: "
        "the census reports it and no page may claim it is silent")




def test_the_state_root_note_is_said_once_and_never_duplicated(capsys):
    """One note, printed once, and every other note still printed below the rows.

    The renderer recognises the note by its opening words and suppresses that one from
    the trailing ``note:`` block. The two halves must be the same decision, not two
    relations that happen to agree: a note found by one rule and suppressed by another
    would print the sentence twice in one report, or drop it entirely. This drives the
    renderer directly, with the two notes a real no-``noni/`` run can carry at once, and
    holds the ends of the report as well: the note opens it, the verdict closes it.
    """
    import io
    import sys as _sys

    from noni.census_render import (
        ORDERING_CLOSED_NOT_EVALUATED,
        _render,
        no_state_root_note,
    )

    note = no_state_root_note("state/repo")
    buf = io.StringIO()
    saved = _sys.stdout
    _sys.stdout = buf
    try:
        _render([], {}, True, 0, False, (note, ORDERING_CLOSED_NOT_EVALUATED))
    finally:
        _sys.stdout = saved
    lines = buf.getvalue().splitlines()
    assert lines[0] == f"note: {note}", lines[:3]
    assert lines[-1].startswith("summary: "), lines[-1]
    stated = [line for line in lines if line == f"note: {note}"]
    assert len(stated) == 1, f"the note printed {len(stated)} times: {lines}"
    # The other note is untouched by the suppression and still sits below the rows.
    assert f"note: {ORDERING_CLOSED_NOT_EVALUATED}" in lines, lines
    # A note that merely repeats the state-root sentence is one note, not two rows of
    # it: duplication at the producer is not a licence to print the sentence twice.
    buf = io.StringIO()
    _sys.stdout = buf
    try:
        _render([], {}, True, 0, False, (note, note))
    finally:
        _sys.stdout = saved
    lines = buf.getvalue().splitlines()
    assert sum(1 for line in lines if line == f"note: {note}") == 1, lines
    del capsys


def test_an_uninspectable_noni_is_never_reported_as_having_no_noni(tmp_path):
    """A declined ``lstat`` on ``noni/`` is a fault, not the note's ``absent`` state.

    The note keys on the ledger probe's ``absent``, which is answered only when
    ``noni/`` is genuinely missing -- and "genuinely" is the whole point: a tree the
    operator cannot traverse made ``Path.exists`` answer False, so a census run there
    opened with "no noni/ directory was found" and exited 0 beside an inactive
    deny-list, which is the all-clear this ticket exists to remove. The fault must
    reach the report as the cannot-tell it is, with no note claiming an absence nobody
    observed. Skipped where the reading user can lstat through a 000-mode directory
    (running as root), exactly as the session guard's inspection suite does.
    """
    import os

    import pytest

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "census-uninspectable")
    (repo / "noni" / "decisions").mkdir(parents=True)
    os.chmod(repo / "noni", 0o000)
    try:
        try:
            os.lstat(repo / "noni" / "decisions")
        except PermissionError:
            proc = subprocess.run(
                [sys.executable, str(CENSUS), "--repo", str(repo)],
                capture_output=True, text=True, env=subprocess_env(),
                cwd=str(cwd), timeout=120)
        else:
            pytest.skip("the reading user can lstat through a 000-mode directory")
    finally:
        os.chmod(repo / "noni", 0o755)
    assert "no noni/ directory was found under --repo" not in proc.stdout, proc.stdout
    assert "Permission denied" in proc.stdout or "could not" in proc.stdout, proc.stdout
    assert proc.returncode != 0, (
        f"a census that could not inspect the state root must not read as clean: "
        f"{proc.returncode}\n{proc.stdout}")
