"""Shared fixtures for the E1-E5 hardening half of the decide.py writer suite.

The hardening round's tests share the in-process writer seam (a spy on the
writer's git calls, and stand-ins for its one atomic write) and the target-
shaped fixtures (a committed target whose bytes are whatever a fixture plants).
Pure moves from the file that covered all of them: no behaviour here changed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from _harness import _git, _git_e2, git_pin_date, subprocess_env
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_DATE,
    BASELINE_ID,
    NEW_DATE,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _decide_module,
    _identity_env,
    _pin_identity,
    _porcelain,
    _record_json,
    _record_path,
    _supersede,
)

# The repository of the in-process run currently in flight, or [None].
_RUN_REPO: list[Path | None] = [None]

# The three trees of a census.sh state-root run; see _census_sh_case.
CENSUS_SH_STATE_DIR = "census-sh-state-root"
CENSUS_SH_CWD_DIR = "census-sh-cwd"
CENSUS_SH_DECOY_DIR = "census-sh-decoy"


def _census_sh_from(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """census.sh launched from ``cwd`` with the arguments given verbatim.

    Verbatim, because the point of these tests is the absence of an argument:
    a helper that always passed a ledger could not express the run that gives
    the shim nothing.
    """
    from decide_fixtures import CENSUS_SH

    return subprocess.run(
        ["bash", str(CENSUS_SH), *args],
        capture_output=True, text=True, env=subprocess_env(),
        cwd=str(cwd), timeout=120,
    )


def _census_sh_snapshot(tree: Path) -> dict[str, str]:
    """Every file under ``tree`` as path -> bytes, so a claim of 'untouched'
    names what moved rather than only that something did."""
    return {str(p.relative_to(tree)): p.read_bytes()
            for p in sorted(tree.rglob("*")) if p.is_file()}


def _census_sh_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one census-sh state-root run: (state root, decoy, cwd).

    Both ledgers hold one committed decided record, so both are censusable: a
    run that resolved its ledger from the cwd would answer on the decoy's
    bytes, and the assertion can tell that from a run that read the state
    root's. The decoy is a real git repo for the same reason the decide decoy
    is one — a decoy the tool could not have worked in is not a decoy.
    """
    root = _baseline_repo(tmp_path, CENSUS_SH_STATE_DIR)
    decoy = _baseline_repo(tmp_path, CENSUS_SH_DECOY_DIR)
    cwd = tmp_path / CENSUS_SH_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


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
    """The positional arguments of a _git command line, past the hardening block."""
    index = 1
    while index < len(cmd):
        arg = cmd[index]
        if arg in ("-C", "-c"):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return [str(part) for part in cmd[index:]]
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


def _canonical_body(target_id: str, status: str = "decided") -> str:
    """``target_id``'s record in the writer's canonical bytes (the _render form).

    The record is built by the fixture helper and rendered by the writer's own
    _render, so the bytes a canonical fixture commits are exactly the bytes this
    writer would have written for that record.
    """
    record = json.loads(_record_json(target_id, status, "yes", None))
    return _decide_module()._render(record)


def _non_canonical_target_repo(
    tmp_path: Path, body: str, name: str = "odd", target_id: str | None = None
) -> tuple[Path, str, str]:
    """A repo whose committed target is ``body`` verbatim.

    ``target_id`` is the record's id and defaults to ``<BASELINE date>-<name>``;
    a fixture that builds its bytes from another id passes it so the record's
    own ``id`` field and its filename agree. The commit bypasses
    ``_commit_tree``'s identical-bytes guard on purpose: these fixtures commit
    bytes the writer itself would not have produced, and the whole point is
    that HEAD holds them exactly as given.
    """
    repo = _baseline_repo(tmp_path, f"target-{name}")
    target_id = target_id or f"{BASELINE_ID[:10]}-{name}"
    rel = f"noni/decisions/{target_id}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"fixture: odd target {name}")
    return repo, rel, target_id


def _refused_target_repo(tmp_path: Path, name: str, raw: str) -> tuple[Path, str]:
    """A repo whose committed supersede target is ``raw``, the bytes verbatim.

    ``raw`` is given as text so a fixture can plant a shape no flag of this
    writer can produce (``NaN`` as a bare token, a quoted date, a numeric
    answer): the commit goes in raw so HEAD holds exactly those characters,
    which is what the writer is asked to read.
    """
    target_id = f"{BASELINE_ID[:10]}-{name}"
    repo, rel, _id = _non_canonical_target_repo(tmp_path, raw, name, target_id)
    return repo, target_id


def _refuse_raw_target(tmp_path: Path, name: str, raw: str) -> tuple[str, Path, str]:
    """The stderr of the standard supersede of a planted target, plus its paths.

    The run is the launched one (no in-process spy), so it reads the committed
    bytes the way a real run does. The assertion every caller makes is exit 4
    with the target and the tree untouched: a refusal is only worth having if
    it refuses rather than rewrites.
    """
    repo, target_id = _refused_target_repo(tmp_path, name, raw)
    rel = f"noni/decisions/{target_id}.json"
    committed = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    proc = _supersede(repo, target_id)
    assert proc.returncode == 4, f"{name}: expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert _porcelain(repo) == "", f"{name}: a refused run must leave the tree alone"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), name
    assert _git_e2(repo, "show", f"HEAD:{rel}").stdout == committed, (
        f"{name}: the refused target's committed bytes must be exactly what they were"
    )
    return proc.stderr, repo, rel


def _planted_body(target_id: str, **overrides: object) -> str:
    """A canonical record body for ``target_id`` with ``overrides`` applied.

    The record is built by the fixture helper and rendered by the writer's own
    ``_render``, so the bytes are canonical except for the one field under test --
    which is what routes the refusal to the rule being probed rather than to the
    canonical-form check or the id/name match. A caller that mutates a nested
    value (``questions``) applies its own patch and passes no override for it.
    """
    record = json.loads(_canonical_body(target_id))
    record.update(overrides)
    return _decide_module()._render(record)


def _refused_path_repo(tmp_path: Path, name: str, plant: Callable[[Path], str]) -> tuple[Path, str]:
    """A repo whose committed target is whatever ``plant`` leaves at the target path.

    ``plant`` receives the target path and returns the single line describing the
    shape it made (``symlink -> elsewhere``, ``<dir>``), which the caller asserts
    back after the commit: git stores a link as a link and a directory as its
    files, so a fixture that planted one and lost it would assert a refusal that
    git had quietly un-planted. The commit is the writer's own route (add, then
    commit at the pinned date), so HEAD really holds the path under the target's
    name and only the file kinds are unusual.
    """
    target_id = f"{BASELINE_ID[:10]}-{name}"
    repo = _baseline_repo(tmp_path, f"target-{name}")
    rel = f"noni/decisions/{target_id}.json"
    target = repo / rel
    described = plant(target)
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"fixture: odd target {name}")
    assert described == _describe_path(target), (
        f"{name}: the planted shape is not what is on disk ({described!r} vs "
        f"{_describe_path(target)!r})"
    )
    return repo, target_id


def _describe_path(path: Path) -> str:
    """One line naming what ``path`` actually is, read without following a link."""
    if not os.path.lexists(path):
        return "<absent>"
    if path.is_symlink():
        return f"symlink -> {os.readlink(path)}"
    if path.is_dir():
        return "<dir>"
    if path.is_file():
        return "<file>"
    return "<other>"


def _assert_wrote_nothing(repo: Path, *expected_untracked: str) -> None:
    """A refused run touches neither the ledger nor the index.

    ``expected_untracked`` names the repo-relative paths the fixture itself left
    untracked (a planted symlink's body, say): the assertion is that this run
    staged and wrote nothing, not that the fixture repo was pristine, and
    spelling out what may be untracked is what keeps a record this run did write
    from being mistaken for fixture noise.
    """
    new_record = f"noni/decisions/{NEW_ID}.json"
    listed = [line.strip() for line in _porcelain(repo).splitlines() if line.strip()]
    assert not any(new_record in line for line in listed), (
        f"a refused run wrote {new_record}: {listed}"
    )
    assert not any(line.startswith("A ") or line.startswith("M ") or line.startswith("D ")
                   for line in listed), f"a refused run staged something: {listed}"
    allowed = set(expected_untracked)
    for line in listed:
        path = line[3:]
        assert path in allowed, f"unexpected path after a refused run: {line!r} (allowed: {sorted(allowed)})"
