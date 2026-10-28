"""Shared git / script helpers for the steering-ledger test harness.

Held in its own module (not ``conftest.py``) so that ``scenario_eval.py`` —
which is both a test module and a standalone build tool
(``python tests/scenario_eval.py <path>``) — can import these helpers
without pulling in ``conftest.py`` and its module-level ``import pytest``.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The package's modules, measured by the gate and imported by the tests as
# ``noni.<module>``. The package must be installed (``pip install -e ".[dev]"``
# or the built wheel) or its ``src/`` put on ``PYTHONPATH``; conftest.py does the
# latter so the in-place suite needs no install step.
SRC = REPO / "src"

# The Python product modules the coverage gate measures, relative to the repo
# root. Naming them here keeps the list in one place: pyproject's
# [tool.coverage.report] include carries the same paths and
# tests/test_gate_wiring.py compares the two, so a module cannot quietly
# disappear from the gate. Tests are excluded by construction — only these
# files are measured, so the reported total is the coverage of shipped code.
# The package modules under src/noni/ are the shipped code; the skills/*/
# scripts/ wrappers are thin shims and are deliberately not measured.
PRODUCT_MODULES = (
    "integrations/adapter_protocol.py",
    "integrations/github-issues/github_issues_adapter.py",
    "src/noni/_session_git.py",
    "src/noni/close.py",
    "src/noni/release.py",
    "src/noni/census.py",
    "src/noni/census_hygiene.py",
    "src/noni/census_json.py",
    "src/noni/census_ledger.py",
    "src/noni/census_ordering.py",
    "src/noni/census_ordering_readers.py",
    "src/noni/census_sessions.py",
    "src/noni/census_sessions_checks.py",
    "src/noni/census_sessions_probe.py",
    "src/noni/census_text.py",
    "src/noni/claim.py",
    "src/noni/cli.py",
    "src/noni/decide.py",
    "src/noni/gitwrite.py",
    "src/noni/labels.py",
    "src/noni/order.py",
    "src/noni/order_gitwrite.py",
    "src/noni/orderschema.py",
    "src/noni/orderstate.py",
    "src/noni/public_safety.py",
    "src/noni/register.py",
    "src/noni/shim_help.py",
    "src/noni/targetschema.py",
)

# The env var coverage's subprocess support needs. A launched interpreter
# starts measuring only when this names the config file to read, so it is set
# here — in the launcher itself, not only in the shell that started pytest —
# and a bare local `pytest` gets the same measurement as the documented
# three-command gate.
COVERAGE_PROCESS_START = str(REPO / "pyproject.toml")


# Width every launched tool sees, pinned so the --help byte-for-byte
# comparisons cannot depend on the terminal the suite happened to run under.
# The launchers force this value (not setdefault): a caller's own COLUMNS --
# including one a test deliberately sets to 80 to prove width-independence --
# must not change the bytes argparse emits.
HELP_COLUMNS = "100"


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


# The package is the single importable home of the product modules (the
# wrappers under skills/*/scripts/ are shims, and scripts/public_safety.py is
# reached only as a subprocess for its CLI exit-code contract). Put src/ on
# sys.path here so every harness consumer gets the same noni.public_safety
# object whether or not the wheel was installed, and so the fixture builders
# below can derive from its pattern tables.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from noni.public_safety import HOME_PATH_PATTERNS, SECRET_PATTERNS  # noqa: E402

# Back-compatible module aliases for the tests that were written against the
# flat scripts/ layout. Those files imported the tool by its script name
# (``import census``, ``import public_safety``) after putting the script's own
# directory on sys.path; the package is the only importable home now, and a
# lookalike earlier on sys.path must not be trusted as the census's own code, so
# the aliases are registered here from the package rather than by path. They are
# the *same objects* the console route imports, which is what makes a seam a test
# installs visible to the other route as well.
for _alias, _pkg_name in (
    ("_session_git", "_session_git"),
    ("close", "close"),
    ("release", "release"),
    ("census", "census"),
    ("census_hygiene", "census_hygiene"),
    ("census_json", "census_json"),
    ("census_ledger", "census_ledger"),
    ("census_ordering", "census_ordering"),
    ("census_ordering_readers", "census_ordering_readers"),
    ("census_sessions", "census_sessions"),
    ("census_sessions_probe", "census_sessions_probe"),
    ("census_text", "census_text"),
    ("claim", "claim"),
    ("decide", "decide"),
    ("gitwrite", "gitwrite"),
    ("order", "order"),
    ("order_gitwrite", "order_gitwrite"),
    ("orderschema", "orderschema"),
    ("orderstate", "orderstate"),
    ("public_safety", "public_safety"),
    ("register", "register"),
    ("targetschema", "targetschema"),
):
    _module = importlib.import_module(f"noni.{_pkg_name}")
    sys.modules.setdefault(_alias, _module)
del _alias, _pkg_name, _module


def load_package_module(name: str) -> object:
    """A fresh copy of a package module, under a test-private name.

    For the tests that mutate a module's globals (a seam on a constant, a
    replaced helper) and must not leak the change into the module the next test
    imports. The package's own copy is left untouched, and the copy is exec'd
    from the same source rather than shallow-copied: a module whose globals are a
    borrowed dict would make a seam on one module visible through the other.
    """
    module = importlib.import_module(f"noni.{name}")
    # Importing first is the point: it proves the module exists in the package
    # before a copy of its file is exec'd, so a name that is not a package
    # module fails here rather than as a confusing file-not-found below.
    del module
    source = _product_source(SRC / "noni" / f"{name}.py")
    private = f"noni_under_test_{name}"
    sys.modules.pop(private, None)
    spec = importlib.util.spec_from_file_location(private, source)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load a fresh copy of the package module {name}")
    fresh = importlib.util.module_from_spec(spec)
    sys.modules[private] = fresh
    spec.loader.exec_module(fresh)
    return fresh


def _claim_module() -> object:
    """The claim module, for the tests that drive its internals.

    Defined here, next to the wrapper path the subprocess tests launch. It is
    the package module, imported under its real name, so a seam a test puts on
    it is visible to the console route too. ``test_claim_validation``
    re-exports it so the name resolves inside that file's globals.
    """
    from noni import claim

    return claim


def _decide_module() -> object:
    """The decide module, for the tests that name its constants.

    The exit-5 tests need the writer's own failure-seam constant rather than a
    copy of its name: a rename in the product then fails the test that drives
    it instead of leaving that test exercising a real commit. The package module
    under its real name, so the constants are the ones the shipped code reads.
    """
    from noni import decide

    return decide


def _script_constant(tree: ast.Module, name: str, origin: str) -> object:
    """One module-level ``NAME = <literal>`` read from an already-parsed script.

    The route for a fixture or an assertion that must hold the value the
    product owns (a row grammar, a set of directory names): the literal is read
    from the shipped file rather than copied, so the two cannot drift.

    Tuples are returned too, not just scalars: a set the product owns (the
    rebase state directories) is a tuple literal, and an assertion set copied
    from it by hand is exactly the drift this helper exists to prevent.
    """
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Constant) or (
            isinstance(value, ast.Tuple) and all(isinstance(e, ast.Constant) for e in value.elts)
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(value, ast.Tuple):
                        return tuple(e.value for e in value.elts)
                    return value.value
    raise AssertionError(f"{origin} defines no module-level constant {name}")


def _script_ast(path: Path) -> ast.Module:
    """Parse ``path`` once and hand the tree to the readers above.

    For a wrapper under ``skills/*/scripts/`` the tree of the package source it
    dispatches to is parsed instead: these readers ask what the *product*
    declares (its exit codes, its parser flags, its docstring), and a wrapper is
    a shim whose own docstring says nothing about the tool's contract. The
    wrapper's source is still read whole by the scrub and presence checks, which
    take a path rather than this helper.
    """
    source = _product_source(path)
    return ast.parse(source.read_text(encoding="utf-8"))


def _harness_source(path: Path) -> str:
    """The text of the product source behind a wrapper path.

    For the checks that read a shipped guard off the source it lives in (a
    compiled regex is a Call, so ``_script_constant`` cannot reach it): they must
    read the package module, since the wrapper is a shim that holds none of the
    tool's logic.
    """
    return _product_source(path).read_text(encoding="utf-8")


def _product_source(path: Path) -> Path:
    """The package source behind a wrapper path (identity for a package path).

    A wrapper is recognised by the package module it imports, so the mapping is a
    property of the file rather than a table of paths that can go stale when a
    tool is renamed.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(r"from noni import ([a-z_][a-z_0-9]*)\b", text)
    if match is None:
        return path
    candidate = SRC / "noni" / f"{match.group(1)}.py"
    if not candidate.is_file():
        raise AssertionError(
            f"{path} imports noni.{match.group(1)} but {candidate} does not exist"
        )
    return candidate


def _git_e2(
    repo: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git in a repo with a deterministic identity and no GPG signing.

    ``env`` is for a call that must not inherit the ambient git identity. A
    supplied mapping *replaces* the process environment rather than augmenting
    it, so callers merge it into ``os.environ`` themselves (see
    ``advance_origin_with_claim``): a partial dict would drop PATH or HOME and
    fail as a confusing git-not-found or dubious-ownership error."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git with the deterministic harness identity (Replay), checking.

    The shared form the test modules' private ``_git`` helpers used:
    ``-c user.name/user.email/commit.gpgsign=false`` and ``check=True``.
    Returns the CompletedProcess so callers can read stdout (e.g. a
    ``git status --porcelain`` round-trip). ``_git_e2`` (no identity pin, no
    check) stays for the push-retry path, which drives its own git config."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    """Create and initialise a throwaway git repo at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "commit", "-q", "--allow-empty", "-m", "initial")
    return path


def _commit_file(repo: Path, rel: str, content: str) -> None:
    """Write ``content`` to ``repo/rel`` and commit it under the harness
    identity (creating parent dirs as needed)."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


# --- Injected ledger-listing faults -------------------------------------------
#
# One builder for both groups' faulted readdirs. The seam is the census's own
# ``Path.iterdir`` and never a mode bit: a root-equivalent runner reads a
# 000-mode directory, so a chmod fixture would read as listable and the test
# would pass vacuously. It is never ``Path.glob`` either -- ``glob`` swallows
# the ``OSError`` a readdir raises and yields nothing, which is the very
# dishonesty the census no longer has, so patching it would fault nothing at all.


def _permission_fault_guard(target: Path, *, text: str = "input/output error",
                            filename: str | None = None):
    """The ``Path.iterdir`` replacement that faults one directory's readdir.

    The guard on the receiver keeps every other listing of the run honest, so
    only the named directory's readdir faults. The exception is built inside the
    guard, so each raise hands the census a fresh ``OSError`` and nothing a
    handler does to it can leak into a later raise.

    With ``filename`` the fault is the errno-pair form that puts the words in
    ``strerror`` and the path it failed on in ``filename``, so ``str()`` holds
    both and a row built from it must print one of them and not the other; that
    is the shape the row's path-leak rule is tested against. Without it the
    fault is a plain ``OSError(text)``, whose ``str()`` is the words alone.

    Returns the replacement; the callers below install it, and a test that needs
    to install it itself (to fault a path the census does not reach by default)
    gets the same builder. In-process callers only -- a subprocess would not see
    the patch.
    """
    import census

    target = Path(target)
    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == target:
            raise (OSError(13, text, filename) if filename is not None
                   else OSError(text))
        return real_iterdir(self)

    return boom


def _fault_the_ledger_listing(monkeypatch, ledger: Path) -> None:
    """Fault the census's listing of ``ledger`` for an in-process run.

    One install over :func:`_permission_fault_guard`, so the ledger and sessions
    sides of the seam are the same fixture and cannot drift into two conventions
    for it (see the block comment for why the seam is ``iterdir``).
    """
    import census

    monkeypatch.setattr(census.Path, "iterdir",
                        _permission_fault_guard(ledger, text="readdir denied"))


def _fault_the_sessions_listing(monkeypatch, sessions: Path,
                                text: str = "input/output error") -> None:
    """Fault the census's listing of ``sessions`` for an in-process run.

    The sessions-side twin of :func:`_fault_the_ledger_listing`: same builder,
    same seam, same in-process-only caveat. ``text`` defaults to the slash-free
    errno words an unmounted device reports, so a test can quote the fault back
    out of the row unchanged -- the scrubber replaces every ``/segment`` run with
    its marker, and a message carrying a separator could not be.
    """
    import census

    monkeypatch.setattr(census.Path, "iterdir",
                        _permission_fault_guard(sessions, text=text))


def _permission_fault_on(sessions: Path, leaked: str):
    """The installable fixture of a fault that carries a path in ``filename``.

    Thin over :func:`_permission_fault_guard`, and named for what it tests: the
    one shape that carries both halves of the row's rule in a single exception,
    so the row must print the words and not the path. Returns the replacement for
    the caller to install with ``monkeypatch.setattr(census.Path, "iterdir", ...)``.
    """
    return _permission_fault_guard(sessions,
                                   text="Permission denied - input/output error",
                                   filename=leaked)


# --- Synthetic hygiene fixtures ------------------------------------------------
#
# One home for the violation strings the census hygiene tests plant. They are
# built from public_safety's OWN pattern components rather than written out:
# a copy-pasted literal silently stops matching the moment a pattern is added
# or reworded, and a fixture that no longer trips the scanner makes the tests
# that depend on it pass for the wrong reason (the same reason
# tests/test_skill_scrub.py and tests/test_purity.py build their fixtures from
# the imported tables).
#
# They must not appear as literals either: these files are git-tracked, and the
# census's own hygiene class — and tests/test_public_safety.py's repo-clean
# check — flag a literal /home/<known identity> path or token shape in a
# Tracked-file literals that would trip the census's own hygiene class (and
# tests/test_public_safety.py's repo-clean check) are never written as literals:
# only the three self files are exempted (src/noni/public_safety.py,
# scripts/public_safety.py and tests/test_public_safety.py), hence the runtime
# assembly.

_HOME_PATH_KNOWN_IDENTITY = "admin"
_SECRET_TOKEN_PREFIX = "ghp_"


def _home_path_violation() -> str:
    """A machine-local home path that HOME_PATH_PATTERNS matches: built from
    the same identity list the pattern itself interpolates."""
    _patterns, label = HOME_PATH_PATTERNS[1]
    assert label.startswith("machine-local absolute home path (/home/"), (
        f"HOME_PATH_PATTERNS[1] is no longer the /home/<known identity> pattern: {label}"
    )
    return f"/home/{_HOME_PATH_KNOWN_IDENTITY}/.ssh/id_ed25519"


def _secret_violation() -> str:
    """A token that SECRET_PATTERNS matches, assembled from the pattern's own
    prefix so a prefix change here cannot quietly un-pin the fixture."""
    prefix = _SECRET_TOKEN_PREFIX
    assert any(p.pattern.startswith("\\b" + prefix) for p, _l in SECRET_PATTERNS), (
        f"{prefix!r} is no longer a SECRET_PATTERNS prefix"
    )
    return prefix + "synthsynth" * 3



def _git_ok(
    repo: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    proc = _git_e2(repo, *args, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr.strip()}")
    return proc


def _git_env_with_identity() -> dict[str, str]:
    """An env that pins a deterministic git identity for subprocesses.

    claim.py commits under the caller's configured identity (it no longer
    hardcodes one), so the test harness pins one here: GIT_CONFIG_GLOBAL
    points at /dev/null so the host's ~/.gitconfig cannot leak in, and the
    GIT_AUTHOR_*/GIT_COMMITTER_* env vars supply the identity (signing is
    handled by the scripts' own commit.gpgsign=false)."""
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Replay",
        "GIT_AUTHOR_EMAIL": "replay@fixture.invalid",
        "GIT_COMMITTER_NAME": "Replay",
        "GIT_COMMITTER_EMAIL": "replay@fixture.invalid",
    }


def git_pin_date(repo: Path, iso_utc: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command with identity and commit dates pinned.

    ``iso_utc`` is the fixed timestamp; GIT_CONFIG_GLOBAL/SYSTEM point at
    /dev/null to block host gitconfig."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    env = dict(os.environ)
    env.update(_git_env_with_identity())
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_AUTHOR_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    env["GIT_COMMITTER_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # core.hooksPath at the null device, like every writer's own git call: a
    # fixture that commits (or amends) must not run the repository's hooks any
    # more than the product does, and this helper runs a bare 'git' where the
    # writers run their hardened one.
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
         "-c", "core.hooksPath=" + os.devnull, *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git (pinned {iso_utc}) {args} failed: {proc.stderr.strip()}"
        )
    return proc


def build_bare_origin(origin: Path, worktrees: list[Path]) -> None:
    """Build a bare origin plus one or more clones all on branch 'main'.

    Every worktree is cloned from the bare origin (so the origin is actually
    shared — not one clone of another) and starts with one committed file so
    it has a commit to push. The caller then drives register.py / claim.py /
    push-retry against the clones.

    Every clone takes ``main`` from the clone command itself, not from its own
    ``init.defaultbranch``: the suite's sandboxed HOME carries no gitconfig, so
    a plain clone falls back to git's own default (master) and lands on a
    branch origin never had. That is invisible while the fixture alone commits,
    because the manual ``checkout -b main`` moves the uncommitted files over —
    but a writer that commits by itself (register.py) puts its commit on
    master, and the push of ``main`` then has nothing to push.
    """
    origin.mkdir(parents=True, exist_ok=True)
    _git_ok(origin, "init", "-q", "--bare")
    first = worktrees[0]
    first.mkdir(parents=True, exist_ok=True)
    _git_ok(first, "init", "-q", "-b", "main")
    (first / "README.md").write_text("test repo\n")
    _git_ok(first, "add", "README.md")
    _git_ok(first, "commit", "-q", "-m", "initial commit")
    _git_ok(first, "remote", "add", "origin", str(origin))
    _git_ok(first, "push", "-q", "-u", "origin", "main")
    for wt in worktrees[1:]:
        wt.mkdir(parents=True, exist_ok=True)
        _git_ok(wt.parent, "clone", "-q", "-b", "main", str(origin), str(wt))


def advance_origin_with_claim(
    origin: Path, seeder: Path, session_file: str, task: str, branch: str = "main"
) -> str:
    """Deterministically advance ``origin`` with a conflicting claim row.

    Clones ``origin`` into ``seeder``, appends one ``- claim: <task>`` row at
    EOF of ``session_file`` (the repo-relative path a claim.py run will also
    append to), commits and pushes it, then removes the seed clone. Because
    both writers append at EOF of the same file, the caller's next
    fetch-rebase-push stops in a real conflict rather than merging cleanly,
    which is what makes the exit-5 path testable without a race. Returns the
    pushed sha.

    ``build_bare_origin`` builds every clone from the same bare origin, so
    the committed baseline of ``session_file`` is identical here and in the
    caller's clone: that is what makes the EOF append conflict deterministic.

    The row is written with claim.py's own ``CLAIM_PREFIX``, so the seeded
    claimant writes exactly what a real one would (see ``_script_constant``).
    """
    for label, value in (("session_file", session_file), ("task", task), ("branch", branch)):
        if not isinstance(value, str) or not value:
            raise TypeError(
                f"advance_origin_with_claim needs a non-empty str {label}, got {value!r}"
            )
    prefix = _script_constant(_script_ast(CLAIM), "CLAIM_PREFIX", CLAIM.name)
    if seeder.exists():
        shutil.rmtree(seeder)
    seeder.parent.mkdir(parents=True, exist_ok=True)
    # The clone is pinned to the branch it is seeding. Two host inputs would
    # otherwise decide that for it: a ~/.gitconfig carrying
    # init.defaultbranch, and the pytest HOME sandbox that carries no
    # gitconfig at all. Under the sandbox git falls back to its own default
    # (master), origin has no master, and the clone checks out an empty
    # worktree on a branch that does not exist - which is how a seed clone
    # silently stops being a seed. So the branch is named in the clone
    # command and confirmed against HEAD before anything is appended.
    env = {**os.environ, **_git_env_with_identity()}
    try:
        # ``-b`` names the branch outright, so it does not matter that the
        # sandboxed HOME carries no init.defaultbranch, nor what origin's own
        # HEAD points at (a bare init repo defaults to master even when the
        # only branch ever pushed is main): an explicit checkout of a branch
        # that exists on origin is what makes the worktree non-empty.
        _git_ok(
            seeder.parent, "clone", "-q", "-b", branch, str(origin), str(seeder),
            env=env,
        )
    except RuntimeError as exc:
        # A bare 'clone has no <file>' would hide why: surface git's own
        # words (dubious ownership, empty remote, no such ref) with them.
        raise RuntimeError(f"seed clone of {origin} failed: {exc}") from None
    landed = _git_ok(seeder, "rev-parse", "--abbrev-ref", "HEAD", env=env).stdout.strip()
    if landed != branch:
        raise RuntimeError(
            f"seed clone checked out {landed!r}, not {branch!r}: the conflict "
            "fixture would seed the wrong branch"
        )
    target = seeder / session_file
    if not target.is_file():
        listing = " ".join(_git_ok(seeder, "ls-files", env=env).stdout.split()) or "<no files>"
        raise RuntimeError(
            f"seed clone has no {session_file} to append to; it checked out: {listing}"
        )
    body = target.read_text(encoding="utf-8")
    if not body.endswith("\n"):
        body += "\n"
    target.write_text(body + prefix + task + "\n", encoding="utf-8")
    _git_ok(seeder, "add", session_file, env=env)
    _git_ok(seeder, "commit", "-q", "-m", f"claim: {task}", env=env)
    _git_ok(seeder, "push", "-q", "origin", branch, env=env)
    sha = _git_ok(seeder, "rev-parse", "HEAD", env=env).stdout.strip()
    shutil.rmtree(seeder)
    return sha


class PushProtocolDrift(AssertionError):
    """Raised by :func:`push_with_retry` when the rebase step fails.

    The harness copy of the push protocol cannot mirror claim.py's exit-code
    contract (it is a fixture, not the product), so it names the two cases the
    product distinguishes and says plainly that it aborts nothing. A scenario
    that needs the real 5/6 semantics drives ``run_claim(..., push=True)``
    instead of this helper.
    """


def push_with_retry(repo: Path, branch: str, attempts: int = 3) -> None:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. This is the push protocol documented in the
    skill (fetch-rebase-push, at most 3 attempts).

    A failing rebase is not classified the way claim.py classifies it: this
    helper runs no abort and raises PushProtocolDrift, which says so. Callers
    that need the product's behaviour drive claim.py --push itself.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _git_ok(repo, "fetch", "origin")
            rebase = _git_e2(repo, "rebase", f"origin/{branch}")
            if rebase.returncode != 0:
                raise PushProtocolDrift(
                    "git rebase origin/" + branch + " failed in the harness push "
                    "helper: " + rebase.stderr.strip()
                    + "; this fixture aborts nothing and does not tell conflict "
                    "from refusal — drive claim.py --push (exit 5/6) for that"
                )
        proc = _git_e2(repo, "push", "origin", branch)
        if proc.returncode == 0:
            return
        if attempt == attempts:
            raise RuntimeError(f"push failed after {attempts} attempts: {proc.stderr.strip()}")

SESSIONS_SKILL = REPO / "skills" / "sessions-claims" / "scripts"
STEERING_SKILL = REPO / "skills" / "steering-ledger" / "scripts"
DIRECTION_SKILL = REPO / "skills" / "direction" / "scripts"
CENSUS_SKILL = REPO / "skills" / "census" / "scripts"
# The in-place entry points: the thin wrappers the skills document. They are the
# compatibility route, and the paired test compares each of them against the
# console route, so the paths are the product's public surface, not a detail.
CENSUS_SH = STEERING_SKILL / "census.sh"
CENSUS_SESSIONS = SESSIONS_SKILL / "census-sessions.sh"
CENSUS_SESSIONS_PY = SESSIONS_SKILL / "census-sessions.py"
REGISTER = SESSIONS_SKILL / "register.py"
CLAIM = SESSIONS_SKILL / "claim.py"
CLOSE = SESSIONS_SKILL / "close.py"
RELEASE = SESSIONS_SKILL / "release.py"
DECIDE = STEERING_SKILL / "decide.py"
ORDER = DIRECTION_SKILL / "order.py"
CENSUS = CENSUS_SKILL / "census.py"

# The five tools the ``noni`` command dispatches: subcommand -> the wrapper that
# must produce the same bytes. The sessions census has no subcommand of its own
# (it is the shim's --sessions dispatch), so it is compared through its wrapper
# against the package module directly.
TOOL_WRAPPERS: tuple[tuple[str, Path], ...] = (
    ("census", CENSUS),
    ("register", REGISTER),
    ("claim", CLAIM),
    ("decide", DECIDE),
    ("order", ORDER),
)


def run_noni(*args: str, env: Mapping[str, str] | None = None,
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
                          timeout=timeout)


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
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=120)


def run_register(repo: Path, identity: str, **kwargs) -> subprocess.CompletedProcess[str]:
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
    )


def run_claim(
    repo: Path, session_id: str, task: str, push: bool = False, **kwargs
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
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=120)


def run_close(
    repo: Path, session_id: str, push: bool = False, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run close.py with ``--repo repo --session-id SID`` and optional --push.

    Mirrors :func:`run_claim`: the deterministic identity env (close.py commits
    under the tree's configured identity, and a --no-commit run must not be
    influenced by a host gitconfig either), and the same
    ``**{"no-commit": None}`` form for a valueless flag.
    """
    return _run_session_writer(CLOSE, repo, session_id, push=push, **kwargs)


def run_release(
    repo: Path, session_id: str, task: str, push: bool = False, **kwargs
) -> subprocess.CompletedProcess[str]:
    """Run release.py with the standard arguments and optional --push.

    Same launcher contract as :func:`run_claim` (deterministic identity env,
    ``**{"no-commit": None}`` for a valueless flag): the two writers that name
    a task commit under the tree's identity, so both are launched the same way.
    """
    return _run_session_writer(RELEASE, repo, session_id, task=task, push=push, **kwargs)


def _run_session_writer(
    script: Path, repo: Path, session_id: str, *, task: str | None = None,
    push: bool = False, **kwargs,
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
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=120)


def run_decide(repo: Path, *args: str, env: Mapping[str, str] | None = None,
               extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
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
    own git config (see ``tests/test_decide.py``'s ``_decide`` helper), and a
    test that wants the missing-identity refusal passes its own ``env``, which
    replaces that identity rather than extending it.
    """
    cmd = [sys.executable, str(DECIDE), "--repo", str(repo), *args, *(extra or [])]
    full_env = subprocess_env()
    if env is None:
        full_env.update(_git_env_with_identity())
    else:
        full_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=120)
