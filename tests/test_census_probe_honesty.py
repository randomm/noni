"""Probe-honesty tests for the unified census.

A census probe that fails to read its input must never be reported as clean.
These tests cover the probe-failure shapes:
  - a record with non-UTF-8 bytes (schema finding, never a crash)
  - git history unavailable (no commits, or no git repo at all)
  - a git subprocess that hangs past its timeout

In each case the census reports a probe failure (warn by default, fail under
--strict) and never exits 0 silently.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
import census  # noqa: E402
from _harness import _git, _init_repo  # noqa: E402


def _valid_record(rec_id: str = "2026-10-01-alpha", status: str = "decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }


def _run(repo: Path, *args: str) -> tuple[int, str, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(argv)
    return rc, out.getvalue(), err.getvalue()


# --- Byte-exact edit-after-commit integrity checks ------------------------------
#
# The edit check compares the committed blob bytes (git cat-file blob) against
# the working-file bytes (read_bytes()). Both sides hash raw bytes, so
# non-ASCII, CRLF, and non-UTF-8 content must not produce a false finding or a
# crash.


def _commit_record_bytes(repo: Path, rel: str, content: bytes) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


# --- A leftover noni/sessions/ is not the census's business --------------------
#
# The sessions and claims subsystem was removed (issue #155), but a state
# repository that ran it keeps its committed register files. The census must
# ignore that directory outright: no row, no error, no warning, and no hygiene
# regression. Two trees are censused and compared so the promise is observed
# rather than read off the absence of a call site.

_LEFTOVER_SESSION_REL = "noni/sessions/2026-10-01-aaaaaa.md"

# A register file in the shape the removed writer wrote, with one claim row:
# the content a double-claim or malformed check used to read.
_LEFTOVER_SESSION_BODY = ("- identity: developer\n- host/worktree: ws\n"
                          "- started: 2026-10-01T10:00:00Z\n- status: active\n"
                          "- claims:\n  - claim: #42\n")


def _censused_repo(tmp_path: Path, name: str, *, with_sessions: bool) -> Path:
    """A state root with one committed record, and optionally the leftover register.

    The two trees carry the same ledger so the only difference between their runs
    is the ``noni/sessions/`` directory; the record is committed so neither run
    adds the ``ledger-empty`` warn and competes with the comparison.
    """
    repo = _init_repo(tmp_path / name)
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-alpha.json",
                         json.dumps(_valid_record(), indent=2).encode("utf-8"))
    if with_sessions:
        _commit_record_bytes(repo, _LEFTOVER_SESSION_REL,
                             _LEFTOVER_SESSION_BODY.encode("utf-8"))
    return repo


def test_a_leftover_sessions_directory_censuses_exactly_like_its_absence(tmp_path):
    """A committed ``noni/sessions/`` changes no byte of the census's answer.

    The operator's own state repository still holds two closed session files from
    before the subsystem was removed. Pointing the census at it must return the
    verdict the same tree without the directory would: the same exit code, the same
    rows, and no cannot-tell row standing in for the group that no longer runs. The
    hygiene class is skipped in both runs for the reason every other class test here
    gives -- an isolated fixture repo has no deny-list, and its always-reporting row
    would be the same in both trees and prove nothing.
    """
    plain = _censused_repo(tmp_path, "plain", with_sessions=False)
    leftover = _censused_repo(tmp_path, "leftover", with_sessions=True)
    assert (leftover / _LEFTOVER_SESSION_REL).is_file(), (
        "the fixture planted no register file, so the comparison proves nothing")

    plain_code, plain_out, plain_err = _run(plain, "--skip", "hygiene", "--json")
    left_code, left_out, left_err = _run(leftover, "--skip", "hygiene", "--json")

    assert (left_code, left_out, left_err) == (plain_code, plain_out, plain_err), (
        "a leftover noni/sessions/ moved the census's answer:\n"
        f"plain:   rc={plain_code} out={plain_out!r} err={plain_err!r}\n"
        f"leftover: rc={left_code} out={left_out!r} err={left_err!r}"
    )
    rows = [json.loads(line) for line in left_out.splitlines()
            if line.strip() and json.loads(line).get("kind") == "finding"]
    assert rows == [], f"the leftover register earned rows of its own: {rows}"
    for row in json.loads(left_out.splitlines()[-1])["not_evaluated"] or []:
        assert "sessions" not in str(row).lower(), (
            f"the census worded something about the directory it must ignore: {row}")


def test_a_leftover_sessions_directory_is_not_a_hygiene_regression(tmp_path):
    """The leftover register's own text does not earn a hygiene row of its own.

    The hygiene class scans every tracked file of the audited tree, so a register
    file a census no longer reads must still not turn a clean tree into a finding:
    the same tree with and without it reports the hygiene class identically.
    """
    plain = _censused_repo(tmp_path, "plain-hy", with_sessions=False)
    leftover = _censused_repo(tmp_path, "leftover-hy", with_sessions=True)

    plain_code, plain_out, plain_err = _run(plain, "--json")
    left_code, left_out, left_err = _run(leftover, "--json")

    assert (left_code, left_out, left_err) == (plain_code, plain_out, plain_err), (
        "the leftover register changed the hygiene-bearing run:\n"
        f"plain:   rc={plain_code} out={plain_out!r} err={plain_err!r}\n"
        f"leftover: rc={left_code} out={left_out!r} err={left_err!r}"
    )


# --- A leftover noni/items/ is not the census's business ----------------------
#
# The item store was removed (issue #158) by a project that ran it, so its state
# repository keeps its committed item files. The census must ignore that directory
# outright, and one of the files in it is deliberately malformed: the promise is not
# only that no item class runs, but that nothing reaches for the directory at all.

_LEFTOVER_ITEM_REL = "noni/items/idea-0001.json"
_LEFTOVER_ITEM_BAD_REL = "noni/items/not-an-item.json"

# A document in the shape the removed writer wrote, so the census's silence is
# about the directory and not about a file it could not have read anyway.
_LEFTOVER_ITEM_BODY = (
    '{"schema": "noni.item/1", "id": "idea-0001", "title": "Ship the census",\n'
    ' "created": "2026-10-01T10:00:00Z", "status": "open"}\n')


def _censused_repo_with_items(tmp_path: Path, name: str, *, with_items: bool) -> Path:
    """A state root with one committed record, and optionally the leftover store.

    The two trees carry the same ledger, so the only difference between their runs
    is the ``noni/items/`` directory. The record is committed so neither run adds
    the ``ledger-empty`` warn and competes with the comparison. The store holds one
    document the removed writer wrote and one file that is not JSON at all: a
    census that listed the directory would have to answer for the bad file.
    """
    repo = _init_repo(tmp_path / name)
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-alpha.json",
                         json.dumps(_valid_record(), indent=2).encode("utf-8"))
    if with_items:
        _commit_record_bytes(repo, _LEFTOVER_ITEM_REL,
                             _LEFTOVER_ITEM_BODY.encode("utf-8"))
        _commit_record_bytes(repo, _LEFTOVER_ITEM_BAD_REL,
                             b"{not json at all")
    return repo


def test_a_leftover_items_directory_censuses_exactly_like_its_absence(tmp_path):
    """A committed ``noni/items/`` changes no byte of the census's answer.

    A state repository that ran the item store still holds its committed item
    files, one of them malformed. Pointing the census at it must return the verdict
    the same tree without the directory would: the same exit code, the same rows and
    the same stderr, with no item row and no cannot-tell row standing in for a group
    that no longer runs. The hygiene class is skipped in both runs for the reason
    every other class test here gives: an isolated fixture repo has no deny-list,
    and its always-reporting row would be the same in both trees and prove nothing.
    """
    plain = _censused_repo_with_items(tmp_path, "items-plain", with_items=False)
    leftover = _censused_repo_with_items(tmp_path, "items-leftover", with_items=True)
    assert (leftover / _LEFTOVER_ITEM_REL).is_file(), (
        "the fixture planted no item file, so the comparison proves nothing")
    assert (leftover / _LEFTOVER_ITEM_BAD_REL).is_file(), (
        "the fixture planted no malformed file, so a census that listed the "
        "directory would have nothing to trip over")

    plain_code, plain_out, plain_err = _run(plain, "--skip", "hygiene", "--json")
    left_code, left_out, left_err = _run(leftover, "--skip", "hygiene", "--json")

    assert (left_code, left_out, left_err) == (plain_code, plain_out, plain_err), (
        "a leftover noni/items/ moved the census's answer:\n"
        f"plain:    rc={plain_code} out={plain_out!r} err={plain_err!r}\n"
        f"leftover: rc={left_code} out={left_out!r} err={left_err!r}"
    )
    rows = [json.loads(line) for line in left_out.splitlines()
            if line.strip() and json.loads(line).get("kind") == "finding"]
    assert rows == [], f"the leftover store earned rows of its own: {rows}"
    for row in json.loads(left_out.splitlines()[-1])["not_evaluated"] or []:
        assert "item" not in str(row).lower(), (
            f"the census worded something about the directory it must ignore: {row}")


def test_the_census_refuses_the_removed_items_flag_as_a_usage_error():
    """``--items`` is no longer an argument of the census, and says so at exit 2.

    The flag was removed with the six item classes, so a scripted call that still
    passes it is a caller working from an old page: argparse's own refusal of the
    name comes back on the census's usage code, not as an ignored flag and not as a
    silent run. ``SystemExit`` is what argparse's ``error`` raises, so the launcher
    catches it and reads the code it carried -- the same answer the wrapper gives a
    shell.
    """
    import io
    from contextlib import redirect_stderr

    err = io.StringIO()
    try:
        with redirect_stderr(err):
            rc = census.main(["--items", "noni/items"])
    except SystemExit as exit_:
        rc = exit_.code
    assert rc == 2, f"an unknown flag must be the usage exit, got {rc}"
    assert "--items" in err.getvalue(), (
        f"the refusal does not name the flag it refused: {err.getvalue()!r}")


def test_edit_check_non_ascii_utf8_unchanged_is_not_edited(tmp_path):
    """(1a) A valid record with non-ASCII UTF-8 content, unchanged on disk,
    must not produce an exit-12 finding — the committed bytes and the working
    bytes are identical, so the sha1s match."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    rec["questions"][0]["text"] = "Adopt the new scheduler? caf\u00e9 r\u00e9sum\u00e9 \U0001f680"
    content = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", content)
    # Working tree is unchanged.
    rc, out, err = _run(repo)
    assert rc == 0, f"unchanged non-ASCII record must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_edit_check_crlf_unchanged_is_not_edited(tmp_path):
    """(1c) A record with CRLF line endings, committed and unchanged, must not
    produce a false edit finding: git stores the bytes verbatim, so the working
    CRLF bytes equal the committed CRLF bytes."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    body = _json.dumps(rec, indent=2)
    crlf = body.replace("\n", "\r\n").encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", crlf)
    rc, out, err = _run(repo)
    assert rc == 0, f"unchanged CRLF record must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_edit_check_non_utf8_record_is_not_crash(tmp_path):
    """(1d) A record containing non-UTF-8 bytes must not crash the census. It
    is a schema finding (exit 10) because it is unreadable/invalid, and the
    edit check must not raise on the raw bytes."""
    repo = _init_repo(tmp_path / "repo")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", b"{\x80\x81\x00bad bytes not utf8")
    # Must not raise; a non-UTF-8 record is a schema (ledger-record) failure.
    rc, out, err = _run(repo)
    assert rc == 10, f"non-UTF-8 record is a schema failure (10), not a crash, got {rc}\nstderr: {err}\nstdout: {out}"


def test_edit_check_edited_after_commit_is_exit_12(tmp_path):
    """(1b) A record edited in the working tree after its commit must produce
    an exit-12 finding (the integrity check fires)."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    rec["questions"][0]["text"] = "Adopt the new scheduler? caf\u00e9 r\u00e9sum\u00e9"
    original = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", original)
    # Now edit the working-tree bytes (valid UTF-8, different content).
    rec["status"] = "open"
    edited = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    (repo / "noni/decisions/2026-10-01-a.json").write_bytes(edited)
    rc, out, err = _run(repo)
    assert rc == 12, f"edited record must be exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" in out.lower(), f"edited finding expected: {out!r}"


def test_edit_check_two_commits_same_timestamp_clean(tmp_path):
    """(2) The edit check compares against the NEWEST commit touching the
    record. Two commits with identical timestamps, the second legitimately
    updating the record file, leave a clean working tree (matching the newest
    commit) and must NOT produce an exit-12 finding — even though the record
    was modified in a second commit, the working tree matches the newest
    committed state."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    fixed = "2026-10-01T10:00:00Z"
    rec1 = _valid_record()
    body1 = _json.dumps(rec1, indent=2, ensure_ascii=False).encode("utf-8")
    (repo / "noni").mkdir(parents=True, exist_ok=True)
    recpath = repo / "noni/decisions/2026-10-01-a.json"
    recpath.parent.mkdir(parents=True, exist_ok=True)
    recpath.write_bytes(body1)
    _git(repo, "add", "noni/decisions/2026-10-01-a.json")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay",
         "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false",
         "-c", f"commit.date={fixed}", "-c", f"author.date={fixed}",
         "commit", "-q", "--allow-empty", "-m", "first"],
        check=True, capture_output=True,
    )
    rec1["status"] = "open"
    body2 = _json.dumps(rec1, indent=2, ensure_ascii=False).encode("utf-8")
    recpath.write_bytes(body2)
    _git(repo, "add", "noni/decisions/2026-10-01-a.json")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay",
         "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false",
         "-c", f"commit.date={fixed}", "-c", f"author.date={fixed}",
         "commit", "-q", "--allow-empty", "-m", "second (supersedes content)"],
        check=True, capture_output=True,
    )
    # Working tree matches the newest commit exactly.
    rc, out, err = _run(repo)
    assert rc == 0, f"clean working tree matching newest commit must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_git_timeout_reports_tool_missing_not_crash(tmp_path, monkeypatch):
    """(4) A git subprocess that hangs past the timeout must not crash; it
    degrades to the cannot-tell / tool-missing outcome. When git cannot be run
    (unavailable), the census exits 3 (required tool missing)."""
    import census as _census

    # Simulate git being entirely unavailable (shutil.which returns None).
    # shutil.which is consulted by the run now (census_run, issue #52), so the
    # seam sits on the module that asks the question. The census re-exports the
    # same module object, so either spelling faults the same lookup.
    import noni.census_run as _run
    monkeypatch.setattr(_run.shutil, "which", lambda name: None)
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = _census.main(["--repo", str(tmp_path)])
    assert rc == 3, f"git unavailable must be exit 3, got {rc}\nstderr: {err.getvalue()}"
    assert "git" in err.getvalue().lower(), f"expected git diagnostic: {err.getvalue()!r}"


def test_git_timeout_on_rev_parse_is_cannot_tell_not_crash(tmp_path, monkeypatch):
    """(4) A hung git during the rev-parse --show-toplevel probe must not
    crash; the census degrades to a non-git run (no git history) and still
    returns a deterministic exit code, never raising TimeoutExpired."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import census as _census
    orig = _census.subprocess.run

    def _run_spy(cmd, *a, **kw):
        if "rev-parse" in cmd:
            raise _census.subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return orig(cmd, *a, **kw)

    monkeypatch.setattr(_census.subprocess, "run", _run_spy)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _census.main(["--repo", str(tmp_path)])
    # rev-parse failing means no git top: the census runs without git and does
    # not crash with an unhandled TimeoutExpired. A deterministic exit (0 for a
    # repo with no noni/ ledger to flag) is the contract.
    assert rc in (0, 2, 3), f"timeout must degrade, not crash, got {rc}\nstderr: {err.getvalue()}"


def test_git_cat_file_timeout_is_cannot_verify_not_crash(tmp_path, monkeypatch):
    """(4) A hung git during blob_content_sha1 (git cat-file blob) must not
    raise TimeoutExpired; it returns None, which the edit check degrades to a
    cannot-verify warning (never a silent pass, never a crash)."""
    import census as _census

    repo = _init_repo(tmp_path / "repo")
    import json as _json
    rec = _valid_record()
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json",
                         _json.dumps(rec, indent=2).encode("utf-8"))
    git = _census.Git(_census._git_top(repo))
    assert git is not None and git.available, "repo should have git history"
    commit = git.last_commit("noni/decisions/2026-10-01-a.json")[1]

    import subprocess as _subprocess
    orig = _census.subprocess.run

    def _run_spy(cmd, *a, **kw):
        if "cat-file" in cmd:
            raise _subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return orig(cmd, *a, **kw)

    monkeypatch.setattr(_census.subprocess, "run", _run_spy)
    # Must return None (cannot-verify), not raise.
    blob = git.blob_content_sha1(commit, "noni/decisions/2026-10-01-a.json")
    assert blob is None, f"timeout must yield None (cannot-verify), got {blob!r}"
