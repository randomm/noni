"""The in-process decide.py seam shared by the hardening half of the writer suite.

These are the fixtures that drive the writer inside the test process, so a spy
can see its git calls and a stand-in can refuse its one atomic write: the
per-verb git spy, the two write stand-ins, and the two drivers that install them
for one run (``_decide_in_process`` and ``_supersede_in_process``). The
target-shaped fixtures live in ``decide_hardening_fixtures``, which imports them
from here. Pure moves from the file that covered all of them: no behaviour here
changed.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
from pathlib import Path
from typing import Callable

from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_DATE,
    OPTIONS,
    QUESTION,
    _decide_module,
    _identity_env,
    _pin_identity,
)

# The repository of the in-process run currently in flight, or [None].
_RUN_REPO: list[Path | None] = [None]


def _gitwrite_module():
    """The git helper module the writer itself uses, so a spy on its
    subprocess.run is the one ``run_git`` resolves through.

    The package module is the one the writer imports, so a spy installed in
    front of it is the one ``run_git`` resolves through and no product file is
    touched.
    """
    from noni import gitwrite

    return gitwrite


def _subcommand(cmd: list[str]) -> str:
    """The git subcommand of a _git command line: the first argument past the
    ``-C <repo>`` pair and any ``-c <key=value>`` hardening options.

    A spy that monkeypatches subprocess.run needs this rather than a fixed
    index: the hardening options sit between -C and the subcommand, so the
    position of the verb moves when they are added.
    """
    index = 1
    while index < len(cmd):
        arg = cmd[index]
        if arg in ("-C", "-c"):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg
    return ""


def _git_arguments(cmd: list[str]) -> list[str]:
    """The git arguments of a writer command line: everything past the hardening
    options, in order (the verb first). Pairs with ``_subcommand``, which reads
    the same positions to pick the verb.
    """
    index = 1
    while index < len(cmd):
        arg = cmd[index]
        if arg in ("-C", "-c"):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return cmd[index:]
    return []


def _writer_git_call(cmd: list[str], repo: Path | None) -> bool:
    """Whether ``cmd`` is the writer's own hardened call in the repo under test.

    sys.modules is process-wide, so while an in-process run is going on the
    harness's fixture calls (git init, add, commit) pass through the same spy
    installed in front of it. Matching the run's ``-C`` directory is what keeps
    those calls real: only the writer's calls in the repo under test are answered.
    """
    if repo is None or cmd[:1] != ["git"] or len(cmd) < 3 or cmd[1] != "-C":
        return False
    if not any(arg == "protocol.ext.allow=never" for arg in cmd):
        return False
    try:
        return Path(cmd[2]).resolve() == repo
    except OSError:
        return False


def _git_spy(failures: dict[str, tuple[int, str]],
             calls: Callable[[str, tuple[str, ...]], None] | None = None) -> None:
    """Make the writer's git calls answer ``failures[verb]`` with that rc.

    subprocess.run is replaced in the namespace ``run_git`` looks the name up in,
    taken from the helper's one cached load, so the product file is never modified
    and every writer run in this session resolves through the same spy. A verb
    outside ``failures`` runs for real, so the run reaches the call under test
    with its normal surroundings; each stand-in carries no stdout, as a hung or
    refused call does.

    The spy answers only the repo of the run in flight (``_RUN_REPO``), which is
    what keeps the harness's own fixture calls real while sys.modules is shared.
    A test that installs it drives the writer with ``_decide_in_process``, which
    sets both knobs for that run; a launched interpreter is a different process
    and never sees them.

    ``calls``, when given, is told the verb and the git arguments of every call
    the writer makes in the repo under test, before it is answered: that is the
    route for a test that must read the pathspec a run handed ``git reset`` or
    ``git add``, which the writer's own ``_git`` alias cannot show because the
    rollback calls the helper's ``run_git`` directly.
    """
    gitwrite = _gitwrite_module()
    real_run = gitwrite.run_git.__globals__["subprocess"].run
    claimed = dict(failures)
    # The repo is snapshotted here, not read at call time: _writer_git_call reads
    # the module-level name, and a test that assigned it as a local would leave
    # the spy answering no call at all (the symptom that sent one run down to a
    # later guard's refusal instead of the injected failure).
    repo_under_test = _RUN_REPO[0]

    def _spy(cmd, *args, **kwargs):
        argv = [str(part) for part in cmd]
        verb = _subcommand(argv)
        if _writer_git_call(argv, repo_under_test):
            if calls is not None:
                calls(verb, tuple(_git_arguments(argv)))
            if verb in claimed:
                rc, stderr = claimed[verb]
                return subprocess.CompletedProcess(argv, returncode=rc, stdout="",
                                                   stderr=stderr)
        return real_run(cmd, *args, **kwargs)

    gitwrite.run_git.__globals__["subprocess"].run = _spy


def _target_write_fails_after_staging(decide, repo: Path, rel: str):
    """A ``_write_atomic`` stand-in that stages ``repo/rel`` and then refuses it.

    The write-failure branch is a state no flag produces, so it is reached by
    replacing the writer's one atomic-write call for one run. The stand-in
    lands the bytes, stages them with the same ``git add`` the writer itself
    uses a few statements later, and only then raises the ``OSError`` a full or
    read-only filesystem raises: that is the failure this branch exists for,
    where the target's path holds this run's bytes in the index and on disk but
    the writer never got to say so. Landing nothing would leave the target
    untouched and hide the very thing under test.

    The rollback restores the target through the same call, so every other path
    (and this path's second call) goes to the real write.
    """
    doomed = str((repo / rel).resolve())
    original = decide._write_atomic
    state = {"fired": False}

    def _fail_once(path, text):
        # Resolved on both sides: decide.py builds its paths from ``--repo`` as
        # given, and a tmp dir reached through a symlink must not make the
        # stand-in answer nothing (the symptom of which is a green run).
        if not state["fired"] and str(Path(path).resolve()) == doomed:
            state["fired"] = True
            original(path, text)
            run_git = decide._git
            run_git(repo, "add", "--", rel)
            raise OSError(1, "Operation not permitted")
        return original(path, text)

    _fail_once.fired = lambda: state["fired"]
    return _fail_once


def _write_once_fails(decide, repo: Path, rel: str):
    """A ``_write_atomic`` stand-in that raises ``OSError`` once, on ``repo/rel``.

    A path the writer cannot land is a state no input flag produces (the disk,
    not the flags, says no), so the write-failure branch is reached by replacing
    the writer's one atomic-write call for the duration of one run. The name is
    patched where ``main`` resolves it, the module's own globals, and not on the
    helper: decide.py binds ``_write_atomic = gitwrite.write_atomic`` at load, so
    a helper-level patch would leave a green run that injected nothing.

    The stand-in raises the error a read-only or full filesystem raises,
    ``OSError(EPERM)``, on the first call for that one path and hands every
    other call to the real write: the rollback restores the target through the
    same call, and a blanket refusal would test the refusal instead of the
    rollback.
    """
    doomed = str((repo / rel).resolve())
    original = decide._write_atomic
    state = {"fired": False}

    def _fail_once(path, text):
        # Resolved on both sides: decide.py builds its paths from ``--repo`` as
        # given, and a tmp dir reached through a symlink must not make the
        # stand-in answer nothing (the symptom of which is a green run).
        if not state["fired"] and str(Path(path).resolve()) == doomed:
            state["fired"] = True
            raise OSError(1, "Operation not permitted")
        return original(path, text)

    _fail_once.fired = lambda: state["fired"]
    # ``fired()`` answers whether the refusal was ever asked for: if it was
    # not, the run never reached the write this test exists to fail, and a
    # green run would have proved nothing.
    return _fail_once


def _decide_in_process(repo: Path, *args: str, env: dict | None = None,
                       failures: dict[str, tuple[int, str]] | None = None,
                       write_fails_on: str | None = None,
                       staged_target: bool = True,
                       monkeypatch=None,
                       render_observer: Callable[[str], None] | None = None,
                       call_observer: Callable[[str, tuple[str, ...]], None] | None = None,
                       ) -> subprocess.CompletedProcess[str]:
    """Run the writer in this process, so a spy sees its git calls, and report
    what a launched run would have reported.

    The launched route (``_decide`` / ``run_decide``) cannot observe a patch of
    this process's subprocess.run, so the tests that inject a specific git call's
    failure drive the writer here instead. The flag set matches ``_decide``'s
    (``--slug scheduler --date NEW_DATE`` plus BASE, QUESTION and OPTIONS), with
    ``args`` appended as ``_decide`` appends them. stdout and stderr are captured
    the way the CLI's prints and ``_fail`` write them, and the exit code is
    main()'s return value. The identity is pinned in the repo's config first, as
    ``_decide`` does, because decide.py reads ``by`` from git config.

    The seam variable is cleared for the run unless ``env`` sets it, so an
    in-process run cannot inherit a forced failure a sibling test left in this
    process's environment. The test's ``monkeypatch`` fixture is used when given:
    a launched fixture call inherits this process's environment, and an
    unpersisted seam would force a failure inside the harness's own git commit.

    ``failures`` is this run's per-verb injection (verb -> ``(returncode,
    stderr)``), installed through ``_git_spy`` and scoped to ``repo`` for the
    duration of the run; with none the run is a plain in-process run.
    ``write_fails_on`` is a repo-relative path whose one atomic write raises
    ``OSError`` the first time; ``staged_target`` picks the shape of that
    failure (see ``_target_write_fails_after_staging`` and ``_write_once_fails``).
    ``render_observer``, when given, sees every string the writer's renderer
    returns for this run, which is how the non-finite-number test proves the
    token it planted actually reached the render, and not just the fixture.
    ``call_observer``, when given, sees every call the writer makes in this repo
    as ``(verb, arguments)`` before it runs, which is how the path-list test
    reads the pathspec this run handed ``git reset``.

    The helper spy is installed before the writer is loaded, so the module object
    decide.py binds its constants through is the one carrying the spy.
    """
    _pin_identity(repo, "Replay")
    argv = ["--repo", str(repo), "--slug", "scheduler", "--date", NEW_DATE,
            *BASE, *QUESTION, *OPTIONS, *args]
    seam = _decide_module().FAIL_COMMIT_ENV_VAR
    run_env = {seam: None, **(env or {})}
    saved = {key: os.environ.get(key) for key in run_env}
    previous_repo = _RUN_REPO[0]
    _RUN_REPO[0] = repo.resolve()
    # A write injection is this run's only, so an exception between here and
    # the finally below cannot leave a raising writer for the next test.
    writer = _decide_module()
    original_write = writer._write_atomic
    original_render = writer._render
    rendered: list[str] = []

    def _observed_render(record):
        text = original_render(record)
        # The local copy lets the helper report what the run rendered when the
        # caller's observer was never reached.
        rendered.append(text)
        if render_observer is not None:
            render_observer(text)
        return text

    # The observer wraps the writer's own renderer so the run below resolves
    # ``_render`` from the module globals and sees it; a target-shape refusal
    # happens in the same call chain, so the bytes it compared are the ones
    # reported here.
    writer._render = _observed_render if render_observer is not None else original_render

    injected = None
    if write_fails_on is not None:
        # Installed before the run begins, and the run below calls this same
        # ``main``: decide.py resolves ``_write_atomic`` from its own globals on
        # each call, so a patch applied after the call started would be a patch
        # the writer never looked at.
        injected = (_target_write_fails_after_staging(writer, repo, write_fails_on)
                    if staged_target else _write_once_fails(writer, repo, write_fails_on))
        writer._write_atomic = injected
    else:
        # A run with no write injection must still get a real writer, and never
        # one left raising by an earlier in-process run.
        writer._write_atomic = original_write
    try:
        _git_spy(failures or {}, calls=call_observer)
        for key, value in run_env.items():
            if monkeypatch is not None:
                if value is None:
                    monkeypatch.delenv(key, raising=False)
                else:
                    monkeypatch.setenv(key, value)
            elif value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = writer.main(argv)
        if injected is not None:
            # A stand-in that was never reached would leave the run looking
            # exactly like a successful one, so the injection reports whether
            # its refusal was actually asked for.
            assert injected.fired(), (
                f"the injected write failure on {write_fails_on} was never reached: "
                "the run wrote nothing to that path and proved nothing"
            )
    finally:
        _RUN_REPO[0] = previous_repo
        writer._write_atomic = original_write
        writer._render = original_render
        if monkeypatch is None:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return subprocess.CompletedProcess(argv, returncode=code,
                                       stdout=out.getvalue(), stderr=err.getvalue())


def _supersede_in_process(repo: Path, write_fails_on: str | None, staged_target: bool = True,
                          failures: dict[str, tuple[int, str]] | None = None,
                          monkeypatch=None,
                          env: dict | None = None,
                          target_id: str | None = None,
                          render_observer: Callable[[str], None] | None = None,
                          call_observer: Callable[[str, tuple[str, ...]], None] | None = None,
                          ) -> subprocess.CompletedProcess[str]:
    """The in-process supersede, with this run's injections.

    The flag set is ``_supersede``'s own (the baseline's ``--date``, every answer,
    ``--supersedes``): a launched run cannot see a patch of this
    process, so the write-failure and probe-failure tests drive the writer
    in-process, and a second ``--date`` appended here would be overridden by the
    one ``_decide_in_process`` already passed rather than selecting the baseline's
    day. ``target_id`` names the record to supersede and defaults to the baseline:
    a fixture that planted its own target must name it, or the run supersedes a
    different record and proves nothing about the one under test. ``write_fails_on``,
    ``failures``, ``render_observer`` and ``call_observer`` are the seams it passes
    through.
    """
    return _decide_in_process(
        repo, "--date", BASELINE_ID[:10], *ANSWERED,
        "--supersedes", target_id or BASELINE_ID,
        env={**_identity_env(), **(env or {})}, write_fails_on=write_fails_on,
        failures=failures, staged_target=staged_target, monkeypatch=monkeypatch,
        render_observer=render_observer, call_observer=call_observer,
    )
