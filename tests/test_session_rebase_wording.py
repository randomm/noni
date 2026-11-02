"""One rebase wording table, pinned to the verdicts the classifier can return.

``_session_push`` holds the reading of the rebase state and no prose; ``claim.py``
holds the only shipped wording, and ``close.py``/``release.py``/``register.py``
pass that same table. That is a two-file contract with nothing but git history to
keep it honest, which is why the reviewer's two tables (one per module, drifted in
their second lines) were invisible to the suite. These checks pin three things: the
table's keys are exactly the verdict names the classifier indexes, a verdict with
no key still prints instead of raising, and no second table has grown.

The classifier is driven through its ``run_git`` seam, so the state probes and the
abort are answered without a real rebase: what is under test is which line the
verdict prints and whether it prints at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from noni import _session_push
from noni import claim as claim_mod
from noni import close as close_mod
from noni import register as register_mod
from noni import release as release_mod

# The verdict names the classifier indexes ``messages`` with, read out of the
# module that uses them rather than restated here.
VERDICTS: tuple[str, ...] = _session_push.REBASE_VERDICTS


def _result(returncode: int = 1, stderr: str = "fatal: conflict") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git", "rebase"], returncode, "", stderr)


def _git_answering(states: dict[str, bool]):
    """A seam whose ``--git-path`` probe reports stopped / absent per directory.

    ``states`` maps a probed name to whether that directory holds positive
    evidence of a stopped rebase: True prints ``<repo>/.git/<name>``, which is
    where :func:`_seed_stopped_state` put the two evidence files, and False
    prints a path under ``<repo>`` that exists nowhere, which the reader answers
    ``absent``. Both answers are the ones a real ``rev-parse --git-path`` would
    print for those trees.
    """
    def run_git(repo, *args):
        argv = list(args)
        if argv[:2] == ["rev-parse", "--git-path"]:
            name = argv[2]
            target = (Path(repo) / ".git" / name if states.get(name)
                      else Path(repo) / "no-such-state")
            return subprocess.CompletedProcess(argv, 0, str(target) + "/", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run_git


def _probe_that_cannot_run():
    """A seam whose ``--git-path`` probe itself fails: the 'cannot know' state.

    This is the one way to reach ``state_unreadable`` honestly -- the classifier
    reports it when a probe could not answer, never when a probe answered
    'nothing here', which is the difference between a refusal the operator can act
    on and a claim of ignorance they cannot.
    """
    def run_git(repo, *args):
        argv = list(args)
        if argv[:2] == ["rev-parse", "--git-path"]:
            return subprocess.CompletedProcess(argv, 128, "", "not a git repo")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run_git


def _stopped_git(abort_returncode: int = 0):
    """A seam reporting a rebase that entered and stopped, with a given abort.

    ``rebase-merge`` prints the tree's own state directory (the caller seeds it)
    and the other name prints nothing, so exactly one verdict of 'stopped' is
    reached. The abort answers ``abort_returncode``.
    """
    def run_git(repo, *args):
        argv = list(args)
        if argv[:2] == ["rev-parse", "--git-path"]:
            name = argv[2]
            target = (Path(repo) / ".git" / name if name == "rebase-merge"
                      else Path(repo) / "no-such-state")
            return subprocess.CompletedProcess(argv, 0, str(target) + "/", "")
        if argv[:2] == ["rebase", "--abort"]:
            return subprocess.CompletedProcess(argv, abort_returncode, "", "no")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run_git


def _seed_stopped_state(tmp_path: Path, name: str = "state") -> Path:
    """A tree holding a rebase-merge dir with the two files that mean 'stopped'.

    ``name`` only keeps several trees under one ``tmp_path`` apart, so a loop over
    the verdicts cannot have its second iteration read the first one's state.
    """
    repo = tmp_path / f"repo-{name}"
    gitdir = repo / ".git" / "rebase-merge"
    gitdir.mkdir(parents=True)
    (gitdir / "head-name").write_text("refs/heads/main\n", encoding="utf-8")
    (gitdir / "onto").write_text("0" * 40 + "\n", encoding="utf-8")
    return repo


def _classify(tmp_path, *, messages, timed_out=False, run_git=None,
              rebase=None):
    """One verdict, in the codes a writer would hand it."""
    return _session_push.classify_rebase_failure(
        tmp_path, rebase or _result(), label="claim.py",
        exit_push_failed=3, exit_rebase_conflict=5, exit_rebase_refused=6,
        timed_out=timed_out, messages=messages,
        run_git=run_git or _git_answering({}),
    )


# --- the parity gate ---------------------------------------------------------


def test_the_shipped_table_has_exactly_the_verdict_keys_the_classifier_indexes():
    """``claim._REBASE_MESSAGES``'s keys == the six verdict literals.

    The two halves of this contract live in different modules: ``_session_push``
    indexes ``messages`` by six names, and ``claim.py`` supplies the wording. A
    key added to one and not the other was previously caught only when an
    operator hit that exact rebase outcome and the run raised on the way to its
    report. This is the gate that replaces the second table.
    """
    assert set(claim_mod._REBASE_MESSAGES) == set(VERDICTS), (
        sorted(set(claim_mod._REBASE_MESSAGES) ^ set(VERDICTS)))
    # And the values are what the reporter formats: tuples of whole lines, never
    # one bare string (which would print one character per line).
    for verdict in VERDICTS:
        lines = claim_mod._REBASE_MESSAGES[verdict]
        assert isinstance(lines, tuple), (verdict, type(lines))
        assert lines, verdict
        assert all(isinstance(line, str) and line for line in lines), verdict


def test_no_module_holds_a_second_rebase_wording_table():
    """One table, in its owner. A second copy is the drift this gate exists for.

    Checked by name across the package: a module that grows its own
    ``_REBASE_MESSAGES`` (or a default table in the helper) is caught here rather
    than by an operator comparing two reports that disagree.
    """
    owners = [name for name in ("claim", "close", "release", "register",
                                "_session_push", "_session_git")
              if hasattr(__import__("noni." + name, fromlist=["x"]),
                         "_REBASE_MESSAGES")]
    assert owners == ["claim"], f"rebase wording lives in more than one place: {owners}"


def test_the_writers_that_push_share_the_one_table():
    """close/release/register push with claim's wording, not a private variant.

    All four publish the same 5/6 split, so an agent scripting ``rc == 5 ->
    resolve the file`` must read the same hint whichever verb printed it.
    """
    for module in (close_mod, release_mod, register_mod):
        assert module.claim._REBASE_MESSAGES is claim_mod._REBASE_MESSAGES, (
            module.__name__)


# --- the defensive lookups ---------------------------------------------------


def test_a_missing_verdict_key_prints_a_generic_line_instead_of_raising(tmp_path,
                                                                        capsys):
    """A failure path may not raise, and KeyError is a raise.

    The rebase has already failed and the abort has already run at the moment
    ``messages[verdict]`` is read, so a missing key would end the run before the
    operator learned the clone was mid-rebase. The table's own exit code is the
    caller's contract, so it is still handed back: what degrades is the prose,
    which now says the verdict's name and quotes git.

    Each verdict is reached by the state it is the answer for, not by naming it:
    the two conflict verdicts need a tree that really holds a stopped rebase, so
    the probe reports the state directory the test created. A seam that printed
    paths for states that do not exist would drive every verdict down the
    'never started' branch and the loop would assert the same line six times.
    """
    for verdict in VERDICTS:
        needs_state = verdict in ("abort_failed", "conflict", "timeout_stopped")
        repo = _seed_stopped_state(tmp_path, verdict) if needs_state else tmp_path
        if verdict == "state_unreadable":
            seam = _probe_that_cannot_run()
        elif needs_state:
            seam = _stopped_git(abort_returncode=1 if verdict == "abort_failed"
                                else 0)
        else:
            seam = _git_answering({})
        incomplete = {k: v for k, v in claim_mod._REBASE_MESSAGES.items()
                      if k != verdict}
        capsys.readouterr()
        code = _classify(repo, messages=incomplete,
                         timed_out=verdict in ("timeout", "timeout_stopped"),
                         run_git=seam)
        err = capsys.readouterr().err
        expected = {"state_unreadable": 6, "refused": 6, "timeout": 3,
                    "abort_failed": 5, "conflict": 5, "timeout_stopped": 3}
        assert code == expected[verdict], (verdict, code, err)
        assert verdict in err, (verdict, err)
        assert "rebase failed" in err, (verdict, err)


def test_an_empty_table_still_reports_the_verdict_and_the_callers_code(tmp_path,
                                                                      capsys):
    """A caller that handed in no wording at all is still answered.

    The loop's promise is a report and a code, never an exception, so an empty
    table degrades to generic lines for every verdict. This is the shape the
    deleted default table used to guarantee by existing; it is now guaranteed by
    the lookup, which is the honest way to hold that promise.
    """
    code = _classify(tmp_path, messages={})
    assert code == 6, code
    err = capsys.readouterr().err
    assert "refused" in err, err
    assert "fatal: conflict" in err, err


def test_a_stopped_rebase_with_no_wording_is_still_aborted_and_reported(tmp_path,
                                                                       capsys):
    """The abort decision does not depend on the wording being present.

    The two halves of the verdict are independent: whether to abort comes from the
    state files, and what to print comes from the table. A missing table must not
    quietly skip the abort, because an unabortable rebase is the state that wedges
    the next command.
    """
    repo = _seed_stopped_state(tmp_path, "keep")
    aborts: list[list[str]] = []

    def run_git(r, *args):
        argv = list(args)
        if argv[:2] == ["rebase", "--abort"]:
            aborts.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["rev-parse", "--git-path"]:
            name = argv[2]
            target = (Path(r) / ".git" / name if name == "rebase-merge"
                      else Path(r) / "no-such-state")
            return subprocess.CompletedProcess(argv, 0, str(target) + "/", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    code = _classify(repo, messages={}, run_git=run_git)
    assert code == 5, code
    assert aborts == [["rebase", "--abort"]], aborts
    err = capsys.readouterr().err
    assert "conflict" in err, err


def test_an_abort_that_fails_with_no_wording_keeps_the_conflict_code(tmp_path,
                                                                     capsys):
    """A failed abort with a missing key is still the conflict code, still printed.

    ``abort_failed`` carries the ``{abort}`` slot no generic line has, so the
    generic fallback has to survive a slot it does not fill rather than raise on
    it. The code is what an operator scripts on; the line is what they read --
    and a line a caller reads must never still show the slot's braces, which is
    an unfilled hole in the report rather than a sentence.
    """
    repo = _seed_stopped_state(tmp_path, "aborted")
    code = _classify(repo, messages={}, run_git=_stopped_git(abort_returncode=1),
                     rebase=_result())
    assert code == 5, code
    err = capsys.readouterr().err
    assert "abort_failed" in err, err
    assert "{" not in err, f"an unfilled slot leaked into the report: {err}"


def test_a_timeout_with_no_wording_reports_the_push_code(tmp_path, capsys):
    """The timeout verdict's generic line keeps the code the caller published.

    Same no-unfilled-slot rule as the abort case: the generic line fills
    ``{quoted}`` and no other slot, so no brace may survive into the report.
    """
    code = _classify(tmp_path, messages={}, timed_out=True,
                     run_git=_git_answering({}))
    assert code == 3, code
    err = capsys.readouterr().err
    assert "timeout" in err, err
    assert "{" not in err, f"an unfilled slot leaked into the report: {err}"
