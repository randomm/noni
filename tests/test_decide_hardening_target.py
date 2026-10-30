"""The target of a supersede: the record decide.py agrees to replace.

Extracted from the decide writer suite (the E1-E5 hardening round): how the
target is named, found and validated before anything is written."""

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path

from _harness import (
    _decide_module,
    _git,
    _git_e2,
    git_pin_date,
)
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_DATE,
    BASELINE_ID,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _assert_both_censuses_clean,
    _baseline_repo,
    _decide,
    _head_paths,
    _identity_env,
    _pin_identity,
    _porcelain,
    _read,
    _record_path,
    _supersede,
)
from decide_hardening_fixtures import (
    _canonical_body,
    _decide_in_process,
    _non_canonical_target_repo,
)
from decide_inprocess_fixtures import _supersede_in_process


def test_hardening_non_utf8_target_refuses_with_four_and_echoes_nothing(tmp_path):
    """A committed target whose bytes are not UTF-8 is a refused supersede
    (exit 4), not a traceback, and its bytes reach neither stream.

    The clobber is a real out-of-band state (the same class the exit-5 seam
    models): a reader that lets UnicodeDecodeError escape would end the run
    with a traceback instead of the refusal, and a reader that quoted the
    bytes would put them on the operator's terminal. The junk bytes are built
    from integers, not written as escapes, so the fixture carries no invalid
    escape sequence of its own.
    """
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID}.json"
    junk = b'{"id": "x", "scope": "' + bytes([0x83, 0x92, 0xC3, 0x28, 0xA0]) + b'"}\n'
    (repo / rel).write_bytes(junk)
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", "fixture: target clobbered out of band")

    proc = _supersede(repo, BASELINE_ID)
    assert proc.returncode == 4, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "JSON object" in proc.stderr, proc.stderr
    # Neither stream carries a byte of the target, nor a stand-in for one.
    for stream in (proc.stdout, proc.stderr):
        assert "\ufffd" not in stream, stream
        assert "\\x" not in stream, stream
    # The refusal writes nothing: the clobbered target stays on disk as planted
    # and the tree is clean, so HEAD still holds the bytes just committed.
    assert (repo / rel).read_bytes() == junk
    assert _porcelain(repo) == ""
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()


def test_hardening_rollback_names_the_path_it_could_not_restore(tmp_path):
    """A path the rollback cannot put back is named, not hidden: the new
    record's path is held by a directory planted after the collision check, so
    the write fails, the rollback's unlink fails with it, and the run exits 5
    naming that leftover exactly as the commit-failure branch names one.

    Silently leaving the ledger holding a directory where a record belongs would
    be worse than the failure the rollback recovers from: the censuses read it
    and the operator is never told which path to clear by hand.

    The directory is planted by an observer of the collision check itself, which
    is the only route to a write that fails for this reason now that the check
    uses ``lexists``: a directory planted up front is a collision (exit 4) and
    never reaches the write. The race this test used to fake with that planted
    directory is still the state under test -- a name free at the check and taken
    at the replace -- and it is no longer simulated by a check that could not see
    it. ``test_hardening_a_directory_at_the_new_record_path_refuses_with_four``
    covers the directory the check can see.

    The observer is installed by an in-process run of the writer, and the planted
    directory is seen by ``os.replace`` itself: with an injected ``_write_atomic``
    the real call never happens and the branch is never reached, so the setup
    cannot be staged in front of the run the way the other write-failure tests do.
    """
    repo = _baseline_repo(tmp_path)
    # The new record's name is <date>-<slug> and a supersede carries the target's
    # date, so the record this run writes sits beside the baseline, not on NEW_DATE.
    record_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    record_path = repo / record_rel

    # The planted directory is what makes os.replace fail, so the observer
    # runs in-process around the writer's own ``main``; an injected
    # ``_write_atomic`` would swallow the real replace and the branch under test
    # would never be reached (a run that exits 0 is that symptom).
    writer = _decide_module()
    original_taken = writer._path_is_taken
    planted: list[str] = []

    def _taken_late(path: Path) -> bool:
        # A collision check that found the name free is this run's last look at it:
        # the directory appears after that answer, which is the ordering the
        # rollback branch exists for.
        taken = original_taken(path)
        if not taken and str(path) == str(record_path):
            path.mkdir(parents=True, exist_ok=True)
            planted.append(str(path))
        return taken

    writer._path_is_taken = _taken_late
    _pin_identity(repo, "Replay")
    argv = ["--repo", str(repo), "--slug", "scheduler", "--date", BASELINE_ID[:10],
            *BASE, *QUESTION, *OPTIONS, *ANSWERED, "--supersedes", BASELINE_ID]
    seam = writer.FAIL_COMMIT_ENV_VAR
    saved = os.environ.get(seam)
    os.environ.pop(seam, None)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = writer.main(argv)
    finally:
        writer._path_is_taken = original_taken
        if saved is not None:
            os.environ[seam] = saved
    # The setup has to have happened, or the run proves nothing about this branch:
    # a check that never found the name free never reached the write at all.
    assert planted == [str(record_path)], planted
    proc = subprocess.CompletedProcess(argv, returncode=code,
                                      stdout=out.getvalue(), stderr=err.getvalue())
    assert proc.returncode == 5, proc.stderr
    assert "rollback did not finish" in proc.stderr, proc.stderr
    assert record_rel in proc.stderr, proc.stderr
    assert record_path.is_dir(), (
        "the leftover is the planted directory: the rollback's unlink cannot "
        "remove what it is not a file, which is why the message must name it"
    )


def test_hardening_a_timeout_on_a_guard_probe_refuses_with_three(tmp_path, monkeypatch):
    """A guard probe (rev-parse, ls-files, status, config, show) that times out
    is a git problem (exit 3) naming the command, never a clean answer.

    The writer's timeout is injected in-process: the spy answers the call for
    the probe with GIT_TIMEOUT_RC and nothing, so the writer has no returncode
    to read as 'a work tree' and must refuse. rc 124 is not zero, and a probe
    whose timeout were read as rc 0 would have gone on to write the record,
    which the exit code and the absent file together rule out.
    """
    module = _decide_module()
    assert module.GIT_TIMEOUT_RC == 124
    repo = _baseline_repo(tmp_path)
    hung = f"git rev-parse timed out after {module.GIT_TIMEOUT}s"
    proc = _decide_in_process(repo, *ANSWERED, env=_identity_env(), monkeypatch=monkeypatch,
                              failures={"rev-parse": (module.GIT_TIMEOUT_RC, hung)})
    assert proc.returncode == 3, proc.stderr
    assert "timed out" in proc.stderr.lower(), proc.stderr
    assert "rev-parse" in proc.stderr, proc.stderr
    assert _porcelain(repo) == ""
    assert not _record_path(repo, NEW_ID).exists()


def test_hardening_a_timeout_on_commit_goes_through_rollback_with_five(tmp_path, monkeypatch):
    """A commit that times out is a failed commit: the run rolls the path back
    and exits 5 naming the command, rather than reporting success.

    The spy stands a hang in for the commit itself, so the writer sees a call
    that ran past GIT_TIMEOUT and returned nothing; the record it wrote must be
    gone and HEAD must be where it was.
    """
    module = _decide_module()
    repo = _baseline_repo(tmp_path)
    hung = f"git commit timed out after {module.GIT_TIMEOUT}s"
    proc = _decide_in_process(repo, *ANSWERED, env=_identity_env(), monkeypatch=monkeypatch,
                              failures={"commit": (module.GIT_TIMEOUT_RC, hung)})
    assert proc.returncode == 5, proc.stderr
    assert "commit" in proc.stderr.lower() and "timed out" in proc.stderr.lower(), proc.stderr
    rel = f"noni/decisions/{NEW_ID}.json"
    assert _porcelain(repo, rel) == "", _porcelain(repo)
    assert not _record_path(repo, NEW_ID).exists()
    assert _head_paths(repo) == [f"noni/decisions/{BASELINE_ID}.json"]


def test_hardening_a_failing_reset_is_reported_and_not_claimed_rolled_back(tmp_path,
                                                                            monkeypatch):
    """A reset that fails is an undo that failed, so the run must say so and
    name the paths that may still be staged.

    Only GIT_TIMEOUT_RC counted as a bad reset, so a reset that answered 128 (or
    1, or 129) was read as success: the exit-5 message then promised a tree
    rolled back to its state before the run while the index kept this run's
    paths staged. The commit failure comes from the env seam (``1``) and the
    reset failure is injected in-process with a non-124 code, which is the
    answer the old code treated as clean. The record file's absence is the
    control that says the rest of the rollback still ran.
    """
    module = _decide_module()
    repo = _baseline_repo(tmp_path)
    # 128 is git's own general failure: a real reset failure, never a timeout.
    env = {**_identity_env(), module.FAIL_COMMIT_ENV_VAR: "1"}
    proc = _decide_in_process(repo, *ANSWERED, env=env, monkeypatch=monkeypatch,
                              failures={"reset": (128,
                                                  "git reset failed: unable to lock index")})
    rel = f"noni/decisions/{NEW_ID}.json"
    assert proc.returncode == 5, proc.stderr
    low = proc.stderr.lower()
    assert "reset" in low, proc.stderr
    assert rel in proc.stderr, "the message must name the path that may still be staged"
    assert "rolled back to their state before this run" not in low, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()


def test_seam_value_that_is_not_one_is_inert_and_the_run_writes(tmp_path):
    """A NONI_DECIDE_FAIL_COMMIT value that is not ``1`` answers nothing.

    The old ``<rc>:<verb>`` form let a stray environment value fail one named git
    call, which is not a property of the writer. With each of those values the
    run is a normal run: it commits its record and prints the one 'wrote' line.
    """
    module = _decide_module()
    for index, inert in enumerate(("42:config", "7:ls-files", "", "0", "yes", "1:commit")):
        repo = _baseline_repo(tmp_path, subdir=f"repo-inert-{index}")
        env = {**_identity_env(), module.FAIL_COMMIT_ENV_VAR: inert}
        proc = _decide(repo, *ANSWERED, env=env)
        assert proc.returncode == 0, f"seam {inert!r}: {proc.stderr}"
        assert _record_path(repo, NEW_ID).is_file(), f"seam {inert!r} wrote nothing"
        assert _read(repo, NEW_ID)["id"] == NEW_ID
        assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"]



def test_hardening_a_failing_status_probe_refuses_with_three(tmp_path, monkeypatch):
    """A ``git status`` that answers a failure is a refusal (exit 3), not clean.

    Only the timeout code was read as "no answer", so a status that died with
    128 (a corrupt or unreadable index, a lock, an fsmonitor that could not be
    exec'd) handed back empty stdout and was read as ``dirty: False``: the
    supersede then judged a target it had not been told was clean to be one, and
    rewrote it. The same shape covers ``ls-files``, whose ``--error-unmatch``
    makes 0 and 1 the only honest answers: anything else says nothing about
    whether the path is tracked. The failure is injected in-process because a
    real corrupt index would take the harness's own fixture calls down with it.
    """
    repo = _baseline_repo(tmp_path)
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    before = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout

    proc = _supersede_in_process(repo, write_fails_on=None,
                                 failures={"status": (128, "fatal: bad index")},
                                 monkeypatch=monkeypatch)
    assert proc.returncode == 3, proc.stderr
    assert "status" in proc.stderr, proc.stderr
    assert "git status" in proc.stderr, "the refusal names the command that failed"
    assert _porcelain(repo) == "", "a refused run writes nothing"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()
    assert (repo / target_rel).read_text(encoding="utf-8") == before


def test_hardening_a_failing_ls_files_probe_refuses_with_three(tmp_path, monkeypatch):
    """An ``ls-files`` answer outside {0, 1} is a refusal too: 0 is tracked and 1
    is not tracked, and 128 is neither, so reading it as untracked would send the
    run down the "commit the record first" path on a tree it never inspected.
    """
    repo = _baseline_repo(tmp_path)
    proc = _supersede_in_process(repo, write_fails_on=None,
                                 failures={"ls-files": (128, "fatal: bad index")},
                                 monkeypatch=monkeypatch)
    assert proc.returncode == 3, proc.stderr
    assert "ls-files" in proc.stderr, proc.stderr
    assert _porcelain(repo) == ""


def test_hardening_an_untracked_answer_from_ls_files_still_refuses_with_four(
        tmp_path, monkeypatch):
    """The positive control for the probe above: rc 1 is a real "not tracked"
    answer, and stays the exit 4 it has always been. Without this the widened
    refusal could not be told apart from a blanket "never trust ls-files".
    """
    repo = _baseline_repo(tmp_path)
    proc = _supersede_in_process(repo, write_fails_on=None,
                                 failures={"ls-files": (1, "")},
                                 monkeypatch=monkeypatch)
    assert proc.returncode == 4, proc.stderr
    assert "not tracked" in proc.stderr, proc.stderr
    assert _porcelain(repo) == ""


def test_hardening_a_target_write_failure_leaves_nothing_behind(tmp_path):
    """When the supersede target's write fails after the new record landed, the
    rollback must undo the target too: ``git status --porcelain`` is empty and
    the target's bytes are HEAD's, exactly as for a commit failure.

    The target is staged by ``git add`` before its bytes are written, and the
    record's path is the only one in ``rels`` until the target's write has
    landed: the reset that undoes this run therefore left the target staged, so
    ``git status --porcelain`` still reported ``MM`` for a path this run was
    told to forget. The target write is failed with an injected ``OSError``,
    which no flag produces; the record's own write is left real, so the run
    reaches the branch with the record on disk as it would in a real failure.
    """
    repo = _baseline_repo(tmp_path)
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    committed = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout
    new_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"

    proc = _supersede_in_process(repo, write_fails_on=target_rel)
    assert proc.returncode == 5, proc.stderr
    assert "could not be written" in proc.stderr, proc.stderr
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), (
        "the record this run wrote must be unlinked by the rollback"
    )
    assert _porcelain(repo, new_rel, target_rel) == "", _porcelain(repo)
    assert (repo / target_rel).read_text(encoding="utf-8") == committed, (
        "the target must read as HEAD holds it, not as this run left it"
    )


def test_hardening_the_record_write_failure_leaves_nothing_behind(tmp_path):
    """The other half of the same branch: the record's own write fails, so
    nothing landed at all, and the run must still exit 5 with a clean tree.

    The target was never written and never staged here, so this is the shape
    where ``rels`` legitimately holds one path. It is pinned because the fix
    for the pair above puts the target in ``rels`` unconditionally: a rollback
    that reset a path it never staged would be a worse bug than the one it
    fixes, and this run is where that would show.
    """
    repo = _baseline_repo(tmp_path)
    new_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    committed = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout

    proc = _supersede_in_process(repo, write_fails_on=new_rel, staged_target=False)
    assert proc.returncode == 5, proc.stderr
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()
    assert _porcelain(repo, new_rel, target_rel) == "", _porcelain(repo)
    assert (repo / target_rel).read_text(encoding="utf-8") == committed


def test_hardening_a_repo_local_fsmonitor_hook_does_not_run(tmp_path):
    """A repo-local ``core.fsmonitor`` helper is not run by this writer.

    ``core.fsmonitor`` names a program git execs to ask which files changed, so
    like ``core.hooksPath`` it turns a read-only probe into arbitrary execution
    of the tree's own code. The helper here exits 0 and writes a marker, so a
    run that honoured the config would leave the marker behind and exit 0
    anyway: the marker's absence is the assertion, and the record's presence is
    the control that says the run itself happened. The index is marked dirty
    first, which is what makes git consult the helper at all: with a clean
    index no call reaches it and the assertion would pass for no reason.
    """
    repo = _baseline_repo(tmp_path)
    marker = repo / "FSMONITOR_RAN"
    helper = repo / "fsmonitor-helper.sh"
    helper.write_text(
        "#!/bin/sh\n" + "printf x > " + str(marker) + "\nexit 0\n", encoding="utf-8"
    )
    helper.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(helper))
    # A fresh mtime on the index is what asks git to query the monitor: without
    # it the stat cache answers and the helper is never reached.
    index = repo / ".git" / "index"
    stat_before = index.stat()
    os.utime(index, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 2_000_000_000))

    proc = _supersede(repo, BASELINE_ID)
    assert proc.returncode == 0, proc.stderr
    assert _read(repo, BASELINE_ID)["status"] == "superseded", (
        "the supersede itself must still happen: the run has to reach its probes"
    )
    assert not marker.exists(), "decide.py ran a core.fsmonitor helper it must not run"


def test_hardening_a_repo_local_pre_commit_hook_does_not_run(tmp_path):
    """A repo-local pre-commit hook is not run by this writer.

    The hook here exits 0 and writes a marker, so a run that honoured it would
    leave the marker behind and exit 0 anyway: the marker's absence is the
    assertion, and the record's presence is the control that says the commit
    itself happened.
    """
    repo = _baseline_repo(tmp_path)
    marker = repo / "HOOK_RAN"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n" + "printf x > " + str(marker) + "\nexit 0\n", encoding="utf-8"
    )
    hook.chmod(0o755)

    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    assert _record_path(repo, NEW_ID).is_file(), "the commit itself must still happen"
    assert not marker.exists(), "decide.py ran a hook it must not run"
    # Identity still comes from the tree's config: hardening the call must not
    # neutralise global config, whose user.name is what `by` reads.
    assert _read(repo, NEW_ID)["by"] == "Replay"
    _assert_both_censuses_clean(repo, "a commit run with hooks disabled")


def test_hardening_supersede_refuses_a_target_the_writer_would_rewrite(tmp_path):
    """A target outside the writer's canonical form is refused (exit 4) rather
    than rewritten: the supersede must change the status value and no other
    byte, which it cannot promise for bytes it would not have written.

    Two shapes are refused here: an unknown extra field, which the writer's
    FIELD_ORDER render would drop, and a different indent, which it would
    re-flow. The positive control below is the byte test that proves the
    refusal is not over-broad.
    """
    probe_id = f"{BASELINE_ID[:10]}-probe"
    canonical = json.loads(_canonical_body(probe_id))
    extra_field = json.dumps({**canonical, "operator_note": "not in the writer's field order"},
                             indent=2) + "\n"
    odd_indent = json.dumps(canonical, indent=4) + "\n"
    for label, body in (("extra-field", extra_field), ("odd-indent", odd_indent)):
        # Same bytes, committed under the name the writer is asked to supersede:
        # the id inside is probe's, so the refusal under test can only be the
        # canonical-form rule and not the id/name mismatch.
        repo, rel, target_id = _non_canonical_target_repo(tmp_path, body, label, probe_id)
        # The fixture's own bytes must differ from the canonical form they were
        # built from, or the test would assert on a target that needed no
        # refusal at all.
        assert body != _canonical_body(probe_id), label
        before = _git_e2(repo, "show", f"HEAD:{rel}").stdout
        proc = _supersede(repo, target_id)
        assert proc.returncode == 4, f"{label}: {proc.stderr}"
        assert "canonical" in proc.stderr.lower(), f"{label}: {proc.stderr}"
        assert _git_e2(repo, "show", f"HEAD:{rel}").stdout == before, label
        assert _porcelain(repo) == "", label
        assert not (repo / f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json").exists()


def test_hardening_a_canonical_target_still_supersedes_by_the_status_line_only(tmp_path):
    """The positive control: a canonical target is superseded, and the raw
    committed text differs from HEAD's in the status line and nowhere else."""
    target_id = f"{BASELINE_ID[:10]}-canonical"
    repo, rel, _id = _non_canonical_target_repo(tmp_path, _canonical_body(target_id),
                                                "canonical", target_id)
    before = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    assert json.loads(before)["status"] == "decided"
    proc = _supersede(repo, target_id)
    assert proc.returncode == 0, proc.stderr
    after = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines), (before_lines, after_lines)
    differing = [(a, b) for a, b in zip(before_lines, after_lines, strict=True) if a != b]
    assert differing == [('  "status": "decided",', '  "status": "superseded",')], differing
