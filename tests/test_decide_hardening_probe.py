"""The probes of the supersede path: what is refused, and what is left alone.

Extracted from the decide writer suite (the E1-E5 hardening round): the cases
that assert a refusal wrote nothing at all, in either tree."""

import os
from pathlib import Path

from _harness import (
    _decide_module,
    _git_e2,
)
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _decide,
    _porcelain,
    _record_json,
    _record_path,
    _run,
    _supersede,
)
from decide_hardening_fixtures import (
    _assert_wrote_nothing,
    _canonical_body,
    _refused_path_repo,
    _supersede_in_process,
)
from decide_inprocess_fixtures import _gitwrite_module


def test_hardening_a_target_read_that_fails_refuses_with_four(tmp_path, monkeypatch):
    """A target whose bytes cannot be read is refused (exit 4), not traced back.

    ``path_kind`` has already proved the path a regular file, so the read is the
    one remaining thing to do with it -- and a regular file can still refuse its
    owner: a revoked mode (000) is untestable for root and a read-only mount
    answers differently per filesystem, so the fault is injected as the
    ``PermissionError`` the kernel actually raises on an EACCES open, the same
    class of failure the write-failure tests inject. ``record_object`` never
    sees the bytes and the run refuses "not a readable JSON object" with nothing
    written.
    """
    repo = _baseline_repo(tmp_path)
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    committed = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout
    real_read_bytes = Path.read_bytes
    calls: list[str] = []

    def _refusing_read(path):
        # Only the target's own read is failed; every fixture read of another
        # path (including the assertions below) goes to the real method.
        if str(path) == str(repo / target_rel):
            calls.append(str(path))
            raise PermissionError(13, "Permission denied")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _refusing_read)
    proc = _supersede_in_process(repo, write_fails_on=None, monkeypatch=monkeypatch)
    assert calls == [str(repo / target_rel)], (
        f"the injected read failure was never reached: {calls}"
    )
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "not a readable JSON object" in proc.stderr, proc.stderr
    assert _porcelain(repo) == "", f"a refused run writes nothing: {_porcelain(repo)}"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()
    assert (repo / target_rel).read_text(encoding="utf-8") == committed


def test_hardening_an_absent_target_refuses_and_the_shape_hook_is_gone(tmp_path):
    """An absent target path is refused (exit 4) and the dead shape hook is gone.

    ``load_committed_target`` asked a caller-supplied ``shape_refusal`` callback
    why a path it had already proved non-regular was unusable -- a question the
    helper answered itself two statements earlier, through ``path_kind``, which
    refuses every non-regular path (link, directory, device) before the callback
    was reached. So the callback was unreachable code with a caller beside it, and
    the one case it existed for (a path that is absent) is refused by the helper's
    own committed-bytes answer. The helper's signature no longer carries the
    parameter and ``decide.py`` defines no ``_refuse_target_shape``.
    """
    import inspect

    gitwrite = _gitwrite_module()
    params = list(inspect.signature(gitwrite.load_committed_target).parameters)
    assert "shape_refusal" not in params, params
    assert params == ["label", "repo", "path", "target_id", "canonical", "superseded",
                      "statuses"], params
    assert not hasattr(_decide_module(), "_refuse_target_shape"), (
        "decide.py still defines the dead shape callback")

    # The refusal the callback used to be credited with is the helper's own: a
    # committed target whose file has since gone is refused with nothing written.
    # The deletion is the fixture's own state (named below), so what is asserted is
    # that this run wrote nothing, not that the tree it was handed was pristine.
    repo = _baseline_repo(tmp_path, subdir="target-absent")
    rel = f"noni/decisions/{BASELINE_ID}.json"
    (repo / rel).unlink()
    proc = _run(repo, "--slug", "scheduler", "--date", BASELINE_ID[:10],
                *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                "--supersedes", BASELINE_ID, "--no-commit")
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr, proc.stderr
    # The one path git reports is the fixture's own deletion; no record this run
    # staged, and no record this run wrote beside it.
    assert _porcelain(repo) == f"D {rel}", _porcelain(repo)
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()


def test_hardening_a_symlink_target_refuses_with_four(tmp_path):
    """A committed target that is a symlink is refused (exit 4) before any read.

    The old guards asked ``path.is_file()``, which follows the link, so a symlink
    whose target was a regular file read as a file, and the writer's atomic
    replace then wrote through the link to whatever else lived at the end of it,
    or replaced the link itself. A link is not a record whatever it points at.
    """
    def _plant(target: Path) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        # The link is committed with no body at all: a regular path must be
        # refused on its kind alone, so nothing beside the path kind can be the
        # reason this run says no (no record to parse, no id to mismatch).
        target.symlink_to("elsewhere.json")
        return f"symlink -> {os.readlink(target)}"

    repo, target_id = _refused_path_repo(tmp_path, "symlink", _plant)
    proc = _supersede(repo, target_id)
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "symlink" in proc.stderr, proc.stderr
    assert _porcelain(repo) == "", f"{_porcelain(repo)}\n{proc.stderr}"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()
    rel = f"noni/decisions/{target_id}.json"
    assert (repo / rel).is_symlink(), "the refused link must still be a link"
    assert os.readlink(repo / rel) == "elsewhere.json"


def test_hardening_a_tracked_directory_at_the_target_refuses_with_four(tmp_path):
    """A tracked directory at the target's path is refused (exit 4) with nothing written.

    ``git add`` on a directory commits the files beneath it under that path
    prefix, so the target name is tracked, ``ls-files`` answers tracked and the
    shape refusal used to answer ``None`` for a directory: the run fell through
    to HEAD's bytes for a path no blob exists at and was told its target was
    missing, while the rollback had no committed bytes to restore. ``--no-commit``
    keeps the HEAD of the fixture repo at the planted shape so the assertion that
    nothing was written is about this run.
    """
    def _plant(target: Path) -> str:
        target.mkdir(parents=True)
        (target / "inner.json").write_text(_canonical_body(BASELINE_ID), encoding="utf-8")
        return "<dir>"

    repo, target_id = _refused_path_repo(tmp_path, "directory", _plant)
    proc = _run(repo, "--slug", "scheduler", "--date", BASELINE_ID[:10],
                *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                "--supersedes", target_id, "--no-commit")
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "directory" in proc.stderr, proc.stderr
    rel = f"noni/decisions/{target_id}.json"
    assert (repo / rel).is_dir(), "the refused directory must still be a directory"
    assert (repo / rel / "inner.json").read_text(encoding="utf-8") == _canonical_body(BASELINE_ID)
    _assert_wrote_nothing(repo)
    # The directory is still tracked at HEAD with its own committed bytes: a run
    # that had staged a record under the name would show here as a dirty tree.
    assert _git_e2(repo, "show", f"HEAD:{rel}/inner.json").stdout == _canonical_body(BASELINE_ID)


def test_hardening_a_symlink_at_the_new_record_path_refuses_with_four(tmp_path):
    """A symlink already sitting at the new record's path is a collision (exit 4).

    The collision guard asked ``record_path.is_file()``, which follows the link,
    so a link that led nowhere (or to a file) answered "free", and the atomic
    replace wrote a real file over the link: the ledger then holds a record where
    an operator's hand-made link was. A link is not a name this writer may take
    over, and its bytes are not a record the census can read.

    The planted link has no target at all, which is the shape that also covers the
    link to a record: ``lstat`` sees the link either way, where ``is_file()``
    answers False for a dangling one and True for a linked one, so a check built
    on it could never refuse both.
    """
    repo = _baseline_repo(tmp_path)
    new_path = _record_path(repo, NEW_ID)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink("no-such-record-anywhere.json", new_path)

    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "already exists" in proc.stderr, proc.stderr
    assert new_path.is_symlink(), "the refused link must still be a link"
    assert os.readlink(new_path) == "no-such-record-anywhere.json"
    # The ledger still holds only the baseline: nothing was written into or beside
    # the link, and a refused run stages nothing.
    assert _porcelain(repo) == f"?? {new_path.relative_to(repo).as_posix()}", _porcelain(repo)
    assert not _record_path(repo, NEW_ID).is_file()


def test_hardening_a_directory_at_the_new_record_path_refuses_with_four(tmp_path):
    """A directory at the new record's path is a collision (exit 4), not a write.

    ``is_file()`` answered "free" for a directory too, and ``os.replace`` of a
    temp file onto an existing directory fails with ``IsADirectoryError``: the run
    reached the write stage and came back as the exit-5 write failure rather than
    the collision it is.
    """
    repo = _baseline_repo(tmp_path)
    new_path = _record_path(repo, NEW_ID)
    (new_path / "inner").mkdir(parents=True)

    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "already exists" in proc.stderr, proc.stderr
    assert new_path.is_dir(), "the refused directory must still be a directory"
    assert (new_path / "inner").is_dir()
    _assert_wrote_nothing(repo)


def test_hardening_a_failing_show_probe_refuses_with_three(tmp_path, monkeypatch):
    """A ``git show HEAD:<path>`` that answers a failure is a refusal (exit 3).

    ``probe_unanswered`` covered the timeout for every verb and the honest
    return codes for ``ls-files`` and ``status``, but nothing for ``show``, so a
    show that died with 128 handed back empty stdout and was read as "the
    committed bytes are empty": the canonical comparison then failed and the
    operator was told the target was malformed, on a repository git had just
    failed to read. The injection is ``show`` only, and the two probes beside it
    answer honestly, so the refusal can only be the show answer.
    """
    module = _decide_module()
    assert module.GIT_TIMEOUT_RC == 124
    repo = _baseline_repo(tmp_path)
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    before = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout

    proc = _supersede_in_process(repo, write_fails_on=None,
                                 failures={"show": (128, "fatal: bad object HEAD")},
                                 monkeypatch=monkeypatch)
    assert proc.returncode == 3, proc.stderr
    assert "git show" in proc.stderr, "the refusal names the command that failed"
    assert "128" in proc.stderr, f"the refusal should report the code git answered: {proc.stderr}"
    assert _porcelain(repo) == "", "a refused run writes nothing"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()
    assert (repo / target_rel).read_text(encoding="utf-8") == before


def test_hardening_a_timeout_on_the_show_probe_refuses_with_three(tmp_path, monkeypatch):
    """The same probe that hung is a git problem too: rc 124 was already refused
    by the timeout half of ``probe_unanswered`` and stays refused now that a
    failing code is refused as well. Without the positive control the widened
    rule could not be told apart from "never trust show".
    """
    module = _decide_module()
    repo = _baseline_repo(tmp_path)
    proc = _supersede_in_process(
        repo, write_fails_on=None,
        failures={"show": (module.GIT_TIMEOUT_RC,
                           f"git show timed out after {module.GIT_TIMEOUT}s")},
        monkeypatch=monkeypatch)
    assert proc.returncode == 3, proc.stderr
    assert "show" in proc.stderr, proc.stderr
    assert "timed out" in proc.stderr.lower(), proc.stderr
    assert _porcelain(repo) == ""


def test_hardening_a_show_that_reports_no_such_path_still_refuses_with_four(
        tmp_path, monkeypatch):
    """The positive control for the rule above: ``git show HEAD:<path>`` answers
    128 for a path that is simply not in HEAD, and that is a real answer, not a
    git fault. It stays the exit 4 it has always been.

    Without this the widened refusal could not be told apart from "never trust
    show", and every missing-target and untracked-target refusal would have moved
    from 4 to 3, telling the operator to wait for git instead of naming the record
    that is not committed. Both shapes are planted for real -- a file with no
    commit, a name with no file -- and answered by git itself, not by an
    injection, so the phrases the rule matches are git's own.
    """
    # A file on disk with no commit: git says it "exists on disk, but not in 'HEAD'".
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID[:10]}-draft.json"
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(
        _record_json(f"{BASELINE_ID[:10]}-draft", "decided", "yes", None), encoding="utf-8")
    proc = _run(repo, "--slug", "scheduler", "--date", BASELINE_ID[:10],
                *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                "--supersedes", f"{BASELINE_ID[:10]}-draft")
    assert proc.returncode == 4, proc.stderr
    assert "not tracked" in proc.stderr, proc.stderr
    assert "git show" not in proc.stderr, proc.stderr

    # A name with no file at all: git says it "does not exist in 'HEAD'".
    repo = _baseline_repo(tmp_path, subdir="show-absent")
    proc = _decide(repo, *ANSWERED, "--supersedes", "2026-09-09-nope")
    assert proc.returncode == 4, proc.stderr
    assert "git show" not in proc.stderr, proc.stderr
    assert _porcelain(repo) == ""


def test_hardening_a_supersede_lists_each_path_once_in_the_commit(tmp_path, monkeypatch):
    """The rollback and the exit-5 message name each path this run wrote once.

    ``rels`` was seeded with the target and the write block appended it again, so
    a supersede carried ``noni/decisions/<target>.json`` twice: harmless to git
    and wrong to everybody else, since the same list is what the rollback resets
    and what the refusal quotes back at the operator. Both halves are driven to
    the rollback by the two seams that already exist for it -- the injected write
    failure, and the forced-commit seam for the message -- and both assert that
    the target's name appears exactly once, so a duplicated list fails here.
    """
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    record_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"

    # (a) the rollback's own path list. The target's write is failed after it
    # lands and stages, so the rollback runs without ``git add`` having been
    # called: ``git reset -- <paths>`` is the call that carries this run's list.
    seen: list[list[str]] = []

    def _spy_git(verb, args):
        if verb == "reset":
            seen.append([arg for arg in args if arg.startswith("noni/")])

    repo = _baseline_repo(tmp_path)
    rolled = _supersede_in_process(repo, write_fails_on=target_rel, call_observer=_spy_git)
    assert rolled.returncode == 5, rolled.stderr
    assert seen == [[record_rel, target_rel]], (
        f"the rollback must name each path once, in this order: {seen}"
    )

    # (b) the refusal message for a commit that failed after both writes landed:
    # it names the target once, not once per entry of a duplicated list
    repo = _baseline_repo(tmp_path, subdir="listed-once")
    module = _decide_module()
    failed = _supersede_in_process(repo, write_fails_on=None, monkeypatch=monkeypatch,
                                   env={module.FAIL_COMMIT_ENV_VAR: "1"})
    assert failed.returncode == 5, failed.stderr
    assert failed.stderr.count(target_rel) == 1, (
        f"the failure message names the target more than once: {failed.stderr}"
    )
    assert failed.stderr.count(record_rel) == 1, failed.stderr


def test_hardening_written_files_are_not_owner_only(tmp_path):
    """A record written by decide.py is readable like any other project file:
    mkstemp's 0600 must be widened before os.replace, masked by the umask, and
    a superseded target keeps the mode it already had."""
    umask = os.umask(0o022)
    try:
        expected = 0o644 & ~umask
        repo = _baseline_repo(tmp_path)
        # A baseline the writer did not make, so its mode proves nothing yet.
        target_rel = f"noni/decisions/{BASELINE_ID}.json"
        (repo / target_rel).chmod(0o644)
        proc = _decide(repo, *ANSWERED, "--source-issue", "7", "--source-comment", "8")
        assert proc.returncode == 0, proc.stderr
        written = _record_path(repo, NEW_ID).stat().st_mode & 0o777
        assert written == expected, oct(written)
        assert written != 0o600, "a 0600 record is unreadable to the census's usual reader"

        proc = _supersede(repo, BASELINE_ID)
        assert proc.returncode == 0, proc.stderr
        flipped = (repo / target_rel).stat().st_mode & 0o777
        assert flipped == expected, oct(flipped)
    finally:
        os.umask(umask)


def test_hardening_source_ids_must_be_positive(tmp_path):
    """--source-issue and --source-comment are tracker ids: zero or negative is
    a usage error (exit 2), refused before anything is written."""
    repo = _baseline_repo(tmp_path)
    for flag in ("--source-issue", "--source-comment"):
        other = "--source-comment" if flag == "--source-issue" else "--source-issue"
        for bad in ("0", "-1"):
            proc = _decide(repo, *ANSWERED, flag, bad, other, "7")
            assert proc.returncode == 2, f"{flag} {bad}: {proc.stderr}"
            assert flag in proc.stderr, proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""
    assert sorted(p.name for p in (repo / "noni/decisions").glob("*.json")) == [
        f"{BASELINE_ID}.json"
    ]
