"""Launchers for the product's entry points, as the test harness runs them.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every ``from _harness import`` keeps resolving.
A helper module: never named ``test_*``.

"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from harness_git import _git_env_with_identity
from harness_paths import (
    CLAIM,
    CLOSE,
    COVERAGE_PROCESS_START,
    DECIDE,
    HELP_COLUMNS,
    ORDER,
    REGISTER,
    RELEASE,
    REPO,
    SRC,
)


def subprocess_env(base: dict | None = None) -> dict:
    """An env for a launched product script, with coverage's hook enabled.

    ``base`` starts from a specific environment instead of the current one.
    Every test launcher of a product Python script goes through this, which
    is what makes the subprocess half of the coverage gate fire.

    ``PYTHONPATH`` is pinned to this tree's ``src/`` and put first. The suite
    runs in a worktree while the venv carries an editable install of ``noni``
    pointing at the checkout it was installed from, and a wrapper resolves
    ``from noni import register`` through the *installed* path — so without
    this pin the child runs another tree's modules: the worktree's tests assert
    against one copy of the product and exercise another. Prepending (not
    replacing) keeps an inherited path element that a caller put there on
    purpose, and keeps ``sys.path.insert`` in conftest honest for the in-process
    route: both routes now resolve ``noni`` into this tree.

    ``COLUMNS`` is forced (see :data:`HELP_COLUMNS`) so the ``--help``
    byte-for-byte comparisons are width-independent: argparse wraps its usage
    and option help to the terminal width, so without the pin the wrapper and
    the console route would differ whenever the harness runs under a different
    width than the caller's shell (or no width at all, which is what a piped
    test run gives).
    """
    env = dict(os.environ if base is None else base)
    env["COVERAGE_PROCESS_START"] = COVERAGE_PROCESS_START
    env["COLUMNS"] = HELP_COLUMNS
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (str(SRC) + os.pathsep + inherited
                         if inherited else str(SRC))
    return env


def run_noni(*args: str, env: Mapping[str, str] | None = None,
             cwd: Path | None = None,
             timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """The installed console command over ``noni.cli:main``, as a subprocess.

    Launched as ``python -m noni.cli`` rather than the ``noni`` script so the
    job needs no console-script entry on PATH while still going through the
    console module's own dispatch; ``tests/test_console_equivalence.py`` runs
    the ``noni`` script itself against the installed wheel.

    Like :func:`run_wrapper`, this forces the pinned ``COLUMNS`` on a
    caller-supplied env, so both routes of a ``--help`` pair wrap at the same
    width whatever the caller's environment says.
    """
    cmd = [sys.executable, "-m", "noni.cli", *args]
    full = subprocess_env() if env is None else dict(env)
    full["COLUMNS"] = HELP_COLUMNS
    return subprocess.run(cmd, capture_output=True, text=True, env=full,
                          timeout=timeout, **_cwd_kwarg(cwd))


def run_wrapper(script: Path, *args: str, env: Mapping[str, str] | None = None,
                cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """One in-place wrapper under the running interpreter, argv verbatim.

    The wrapper is launched by path (the form the skills document and the README
    sells), so the comparison against ``noni <tool>`` covers the wrapper's own
    import of the package and not just the package's output.

    A caller-supplied ``env`` still gets the pinned ``COLUMNS`` (see
    :data:`HELP_COLUMNS`): the width the help text wraps at is not a knob a
    caller may turn, which is what makes the equivalence width-independent.
    """
    cmd = [sys.executable, str(script), *args]
    full = subprocess_env() if env is None else dict(env)
    full["COLUMNS"] = HELP_COLUMNS
    return subprocess.run(cmd, capture_output=True, text=True, env=full,
                          cwd=None if cwd is None else str(cwd), timeout=timeout)


def _order_module() -> object:
    """The order module, for the tests that drive its internals.

    The package module under its real name, so the writer's own constants (its
    exit codes, its canonical form) are read from the product rather than copied
    and its ``__main__`` guard is never mistaken for a test entry point.
    """
    from noni import order

    return order


def run_order(repo: Path, *args: str, env: Mapping[str, str] | None = None,
              cwd: Path | None = None,
              ) -> subprocess.CompletedProcess[str]:
    """Run order.py with ``--repo repo`` plus the arguments given as plain strings.

    The caller owns the exact command line (``"add", "7", "--at", "2"``), which is
    what the exit-code tests assert. Runs with the deterministic identity env
    (``GIT_CONFIG_GLOBAL=/dev/null`` plus GIT_AUTHOR_*/GIT_COMMITTER_*) because
    order.py commits under the tree's configured identity and --no-commit runs
    must not be influenced by a host gitconfig either.
    """
    cmd = [sys.executable, str(ORDER), "--repo", str(repo), *args]
    full_env = subprocess_env()
    if env is None:
        full_env.update(_git_env_with_identity())
    else:
        full_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env,
                          timeout=120, **_cwd_kwarg(cwd))


def run_register(repo: Path, identity: str, cwd: Path | None = None,
                 **kwargs) -> subprocess.CompletedProcess[str]:
    """Run register.py with --repo repo --identity identity and extra kwargs.

    Launched under the deterministic identity env, like the other writers that
    commit (``run_claim``, ``_run_session_writer``): register.py makes its own
    commit, and the suite's autouse fixture clears ``GIT_AUTHOR_*`` /
    ``GIT_COMMITTER_*`` from the environment, so a launcher that inherited the
    ambient env would have git refuse the commit for want of an identity — the
    writer answers that honestly with exit 3, which is not what the fixture
    means to be testing. A ``--no-commit`` run is unaffected by the pin.
    """
    extra = []
    for key, value in kwargs.items():
        if value is None:
            extra.append(f"--{key}")
        else:
            extra.extend([f"--{key}", str(value)])
    full_env = subprocess_env()
    full_env.update(_git_env_with_identity())
    return subprocess.run(
        [sys.executable, str(REGISTER), "--repo", str(repo), "--identity", identity, *extra],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=120,
        **_cwd_kwarg(cwd),
    )


def run_claim(
    repo: Path, session_id: str, task: str, push: bool = False,
    cwd: Path | None = None, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run claim.py with the standard arguments and optional --push.

    Runs with the deterministic identity env (claim.py commits under the
    caller's configured identity; the harness pins one here).

    A valueless flag is passed as ``**{"no-commit": None}`` (a Python name
    cannot carry a dash, hence the dict-expansion form): a ``None`` value
    emits the bare flag, any other value emits ``--key value``."""
    extra = []
    for key, value in kwargs.items():
        if value is None:
            extra.append(f"--{key}")
        else:
            extra.extend([f"--{key}", str(value)])
    cmd = [
        sys.executable, str(CLAIM),
        "--repo", str(repo),
        "--session-id", session_id,
        "--task", task,
        *extra,
    ]
    if push:
        cmd.append("--push")
    full_env = subprocess_env()
    full_env.update(_git_env_with_identity())
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env,
                          timeout=120, **_cwd_kwarg(cwd))


def run_close(
    repo: Path, session_id: str, push: bool = False, cwd: Path | None = None,
    **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run close.py with ``--repo repo --session-id SID`` and optional --push.

    Mirrors :func:`run_claim`: the deterministic identity env (close.py commits
    under the tree's configured identity, and a --no-commit run must not be
    influenced by a host gitconfig either), and the same
    ``**{"no-commit": None}`` form for a valueless flag.
    """
    return _run_session_writer(CLOSE, repo, session_id, push=push, cwd=cwd, **kwargs)


def run_release(
    repo: Path, session_id: str, task: str, push: bool = False,
    cwd: Path | None = None, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run release.py with the standard arguments and optional --push.

    Same launcher contract as :func:`run_claim` (deterministic identity env,
    ``**{"no-commit": None}`` for a valueless flag): the two writers that name
    a task commit under the tree's identity, so both are launched the same way.
    """
    return _run_session_writer(RELEASE, repo, session_id, task=task, push=push,
                               cwd=cwd, **kwargs)


def _cwd_kwarg(cwd: Path | None) -> dict[str, str]:
    """The ``cwd=`` keyword for a launcher's ``subprocess.run``, or none.

    Every launcher takes an optional ``cwd`` so its isolation test can run the
    tool from a directory that is not the state root; passing ``cwd=None``
    would mean something different to ``subprocess.run`` in older releases
    than omitting it, so the keyword is simply absent when the caller did not
    name a directory (the historical behaviour: inherit pytest's own).
    """
    return {} if cwd is None else {"cwd": str(cwd)}


def _run_session_writer(
    script: Path, repo: Path, session_id: str, *, task: str | None = None,
    push: bool = False, cwd: Path | None = None, **kwargs,
) -> subprocess.CompletedProcess[str]:
    """One sessions writer under the running interpreter, argv built the same way.

    close.py and release.py differ only in whether a ``--task`` is named, so the
    argv build lives in one place and cannot drift from :func:`run_claim`'s.
    """
    extra = []
    for key, value in kwargs.items():
        if value is None:
            extra.append(f"--{key}")
        else:
            extra.extend([f"--{key}", str(value)])
    cmd = [sys.executable, str(script), "--repo", str(repo),
           "--session-id", session_id]
    if task is not None:
        cmd += ["--task", task]
    cmd += extra
    if push:
        cmd.append("--push")
    full_env = subprocess_env()
    full_env.update(_git_env_with_identity())
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env,
                          timeout=120, **_cwd_kwarg(cwd))


def run_from(cwd: Path, script: Path, *args: str,
             identity: bool = True,
             env: Mapping[str, str] | None = None,
             ) -> subprocess.CompletedProcess[str]:
    """One product entry point launched from a directory that is not the state root.

    The state-root contract every shipped tool makes is that ``--repo`` alone
    decides where noni state is read and written. A launcher that always ran in
    the test's own directory could not tell that promise from the same tool
    quietly reading a ``noni/`` tree next to its cwd, because the two trees were
    never separated. This launches under an explicit ``cwd`` and leaves the argv
    verbatim, so a test plants a decoy ``noni/`` under ``cwd``, points ``--repo``
    at the state root elsewhere, and the assertion measures the difference.

    ``script`` is either a wrapper under ``skills/*/scripts/`` or a package
    module file under ``src/noni/``: both are launched by path, which is the
    form the skills and the README document. ``identity`` applies the same
    deterministic git identity the committing launchers use (``run_claim``,
    ``run_order``, ``run_decide``): a writer launched from a foreign cwd still
    commits under the harness identity, so a failure is the tool's and not the
    absence of an author. A caller that wants the bare environment (a refusal
    with no identity, say) passes ``identity=False`` and its own ``env``.

    A relative ``script`` is the one case the cwd must not decide, so it is
    rooted at this repository before the launch: otherwise a relative wrapper
    path would resolve against the foreign cwd and name no file at all.
    """
    full_env = subprocess_env()
    if env is None:
        if identity:
            full_env.update(_git_env_with_identity())
    else:
        full_env.update(env)
    script_path = script if script.is_absolute() else REPO / script
    return subprocess.run([sys.executable, str(script_path), *args],
                          capture_output=True, text=True, env=full_env,
                          cwd=str(cwd), timeout=120)


def run_decide(repo: Path, *args: str, env: Mapping[str, str] | None = None,
               extra: list[str] | None = None,
               cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run decide.py with ``--repo repo`` plus the flags given as plain strings.

    The flags are passed as plain strings (``"--slug", "scheduler"``) rather
    than kwargs: decide.py's repeats (`--question`, `--option`, `--answer`)
    carry values with '=' and spaces in them, and a kwargs-to-flag conversion
    would either mangle those or need a name no Python identifier can spell
    (``--asked-by``). The caller owns the exact command line, which is what the
    exit-code tests assert.

    Runs with the deterministic identity env (``GIT_CONFIG_GLOBAL=/dev/null``,
    so no host gitconfig, plus GIT_AUTHOR_*/GIT_COMMITTER_*), because decide.py
    commits under the tree's configured identity and ``by`` comes from that
    same config: a test that wants a real author name pins it in the repo's
    own git config (see ``tests/decide_fixtures.py``'s ``_decide`` helper), and a
    test that wants the missing-identity refusal passes its own ``env``, which
    replaces that identity rather than extending it.
    """
    cmd = [sys.executable, str(DECIDE), "--repo", str(repo), *args, *(extra or [])]
    full_env = subprocess_env()
    if env is None:
        full_env.update(_git_env_with_identity())
    else:
        full_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env,
                          timeout=120, **_cwd_kwarg(cwd))
