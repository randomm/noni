

"""Shared fixtures for the decide.py writer test modules.

The decide.py suite is split across files by subject (a record, a supersede,
the state root, the commit path, the hardening round, the docs, and the
census.sh shim); this module holds the one copy of the fixtures those files
share. Pure moves from the file that covered all of them: no behaviour here
changed.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

from _harness import (
    DECIDE,
    REPO,
    _git,
    _git_e2,
    _init_repo,
    _script_ast,
    git_pin_date,
    run_decide,
    run_from,
    subprocess_env,
)
from _harness import _git_env_with_identity as _harness_identity_env

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

# Every census in the decide suite is pinned: --now stops the wall clock from
# deciding a staleness or empty-ledger row, and the baseline records are
# committed under the same fixed dates (see git_pin_date).
NOW = "2026-10-26T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
BASELINE_DATE = "2026-10-01T10:00:00Z"
NEW_DATE = "2026-10-26"
NEW_ID = f"{NEW_DATE}-scheduler"
# A day beside NEW_DATE, for the supersede tests that name an explicit date other
# than the baseline's or the run's own: a new constant rather than a reassigned
# NEW_DATE, so no other decide test moves off its pinned day.
OTHER_DATE = "2026-11-05"

# One question, two options: the smallest shape both censuses accept. Flags are
# kept as lists so each test reads as the command line it runs.
QUESTION = ["--question", "q1=Which release carries the scheduler?"]
OPTIONS = ["--option", "q1=next train", "--option", "q1=after that"]
ANSWERED = ["--answer", "q1=next train"]
BASE = ["--scope", "release ordering", "--asked-by", "developer"]

# The three trees of a decide state-root run; see _decide_case.
DECIDE_STATE_DIR = "decide-state-root"
DECIDE_CWD_DIR = "decide-cwd"
DECIDE_DECOY_DIR = "decide-decoy"
DECIDE_DECOY_ID = "2026-10-05-decoy-stands"

# The script and skill under test, for the files that read their text.
SKILL = REPO / "skills" / "steering-ledger" / "SKILL.md"


def _record_path(repo: Path, record_id: str) -> Path:
    return repo / "noni" / "decisions" / f"{record_id}.json"


def _read(repo: Path, record_id: str) -> dict:
    return json.loads(_record_path(repo, record_id).read_text(encoding="utf-8"))


def _run(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run decide.py with exactly the flags given, identity pinned to Replay."""
    _pin_identity(repo, "Replay")
    return run_decide(repo, *args, env=env)


def _baseline_repo(tmp_path: Path, subdir: str = "repo") -> Path:
    """A repo whose ledger holds one committed decided record, at a pinned date.

    ``subdir`` names the repo's directory under ``tmp_path``: pytest gives one
    directory per test, so a test that builds two baselines (a loop over
    refusal shapes) needs two names, or the second call would find the first
    repo already there and commit nothing.

    The census needs a committed record to have anything to arbitrate: an
    empty ledger is a warn (42 under --strict) and census.sh's edited-after-
    commit check skips a path with no commit, so both would report a state
    unrelated to what decide.py just did.
    """
    repo = _init_repo(tmp_path / subdir)
    record = {
        "id": BASELINE_ID,
        "date": BASELINE_DATE,
        "asked_by": "developer",
        "questions": [
            {
                "id": "q1",
                "text": "Adopt the new scheduler?",
                "options": ["yes", "no", "later"],
                "answer": "yes",
            }
        ],
        "by": "Replay",
        "scope": "release ordering",
        "status": "decided",
        "supersedes": None,
    }
    rel = f"noni/decisions/{BASELINE_ID}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"steering: {BASELINE_ID}")
    return repo


def _decide(repo: Path, *args: str, env: dict | None = None, identity: str | None = "Replay"):
    """Run decide.py with the standard flags, overridable per test.

    ``identity`` is written into the repo's own git config before the run.
    The harness identity env pins ``GIT_CONFIG_GLOBAL=/dev/null`` (so a host
    ``~/.gitconfig`` cannot leak into a test), which also blocks the local
    config ``_init_repo`` would otherwise carry, so the name decide.py reads
    for ``by`` is set here rather than inherited: naming it is also what makes
    the exit-3 test's ``identity=None`` a real absence and not a sandbox
    coincidence.
    """
    _pin_identity(repo, identity)
    return run_decide(
        repo,
        "--slug", "scheduler",
        "--date", NEW_DATE,
        *BASE, *QUESTION, *OPTIONS, *args,
        env=env,
    )


def _pin_identity(repo: Path, identity: str | None) -> None:
    """Give the repo an author name, or make sure it has none.

    ``git config --unset`` runs even for ``None``: a repo built by a previous
    helper in the same test must not keep an identity the current run means to
    withhold.
    """
    if identity is None:
        _git_e2(repo, "config", "--unset", "user.name")
        _git_e2(repo, "config", "--unset", "user.email")
        return
    _git(repo, "config", "user.name", identity)
    _git(repo, "config", "user.email", "replay@fixture.invalid")


def _census_py(repo: Path) -> tuple[int, str]:
    """The unified census under --strict: the arbiter that owns the schema.

    The hygiene class is not this writer's contract (a tree with no deny-list
    reports it as a warn, which --strict promotes to 50), so the ledger group
    is what a decide.py run is held to: --only names the three ledger checks
    plus ledger-empty, which is the group the record and its chain belong to.
    """
    args = ["--repo", str(repo), "--json", "--strict", "--now", NOW]
    for check in ("ledger-record", "ledger-edited", "ledger-chain", "ledger-empty"):
        args += ["--only", check]
    proc = subprocess.run(
        [sys.executable, str(CENSUS), *args],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _census_sh(repo: Path) -> tuple[int, str]:
    """The per-epic census.sh shim over the same ledger."""
    proc = subprocess.run(
        ["bash", str(CENSUS_SH), str(repo / "noni" / "decisions")],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _assert_both_censuses_clean(repo: Path, context: str) -> None:
    code_py, out_py = _census_py(repo)
    code_sh, out_sh = _census_sh(repo)
    assert code_py == 0, f"unified census not clean after {context} (exit {code_py}):\n{out_py}"
    assert code_sh == 0, f"census.sh not clean after {context} (exit {code_sh}):\n{out_sh}"


def _head_paths(repo: Path) -> list[str]:
    """The paths HEAD's own commit touches (no header, no rename rewriting)."""
    out = _git_e2(repo, "show", "--format=", "--name-only", "HEAD").stdout
    return [line for line in out.splitlines() if line.strip()]


def _committed_code_repo(tmp_path: Path, name: str) -> Path:
    """A git tree with an identity, one commit, and no ``noni/`` of its own.

    The tree the pilot's mistake is reproduced on: a valid work tree, so a writer's
    work-tree probe admits it and only the state-root question refuses it. Shared
    between the decide suite and the two route-equivalence suites, each of which builds
    one, so no suite reaches into another's private helpers for it.
    """
    repo = _init_repo(tmp_path / name)
    _git_e2(repo, "config", "user.name", "Replay")
    _git_e2(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_tree(repo, "README.md", "# a code repository\n", "add readme",
                 "2026-10-01T00:00:00Z")
    return repo


def _porcelain(repo: Path, *rels: str) -> str:
    return _git_e2(repo, "status", "--porcelain", "--", *rels).stdout.strip()


def _commit_tree(repo: Path, rel: str, body: str, message: str, date: str) -> None:
    """Commit ``rel`` under a pinned date, creating parents as needed.

    Re-committing a path that is already tracked is how a fixture restates a
    record (the one legal restatement is a supersede target's ``status``).
    ``git add`` on a path whose bytes already match the index is a no-op, and
    ``git commit`` with nothing staged would fail, so the write is forced to
    differ from HEAD: a fixture that asked for the bytes HEAD already has is
    a fixture bug, and this says so rather than committing nothing.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_text(encoding="utf-8") == body:
        raise AssertionError(f"fixture commits identical bytes for {rel}: change the record")
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", message)


def _record_json(record_id: str, status: str, answer: str | None, supersedes: str | None) -> str:
    return json.dumps(
        {
            "id": record_id,
            "date": f"{record_id[:10]}T00:00:00Z",
            "asked_by": "developer",
            "questions": [
                {
                    "id": "q1",
                    "text": "Adopt the new scheduler?",
                    "options": ["yes", "no", "later"],
                    "answer": answer,
                }
            ],
            "by": "Replay",
            "scope": "release ordering",
            "status": status,
            "supersedes": supersedes,
        },
        indent=2,
    ) + "\n"


def _decide_state_root(tmp_path: Path) -> Path:
    """The state repository: a git repo with an identity and one committed
    record, and nothing else — so it is not the cwd and cannot be reached by
    anything but ``--repo``."""
    root = _baseline_repo(tmp_path, DECIDE_STATE_DIR)
    _pin_identity(root, "Replay")
    return root


def _decide_decoy(tmp_path: Path) -> Path:
    """A decoy state root beside the cwd: a ``noni/decisions/`` with one live
    record, planted so a run that resolved its ledger from the cwd would find a
    ledger worth writing into.

    It is a git repository (``_init_repo``) because a decoy is only a decoy if
    the tool under test could have worked in it: a plain directory would make
    decide.py's own ``--is-inside-work-tree`` probe answer first, so a cwd-driven
    run would be stopped for the wrong reason and the assertion would measure
    nothing. Its one record is committed under a pinned date, the same rule the
    state root's baseline follows.
    """
    decoy = _init_repo(tmp_path / DECIDE_DECOY_DIR)
    _commit_tree(decoy, f"noni/decisions/{DECIDE_DECOY_ID}.json",
                 _record_json(DECIDE_DECOY_ID, "decided", "yes", None),
                 f"steering: {DECIDE_DECOY_ID}", "2026-10-05T00:00:00Z")
    return decoy


def _decide_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one decide state-root run: (state root, decoy, cwd)."""
    root = _decide_state_root(tmp_path)
    decoy = _decide_decoy(tmp_path)
    cwd = tmp_path / DECIDE_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _decide_snapshot(tree: Path) -> dict[str, str]:
    """Every file under ``tree`` as path -> bytes, so a comparison can name what
    moved rather than only that something did."""
    return {str(p.relative_to(tree)): p.read_bytes()
            for p in sorted(tree.rglob("*")) if p.is_file()}


def _decide_from(cwd: Path, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """decide.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, DECIDE, "--repo", str(repo), *args)


def _decide_module():
    """decide.py loaded as a module, for the constants its tests name.

    A fresh exec on every call, the harness's own shape: a cached module would
    outlive the file it came from and hand a later test a copy of an earlier
    one's globals (the symptom is an injected failure that reads as a clean run,
    because the run went to a module nobody patched). A caller that patches a
    name on the module and then runs it therefore holds this object across both
    steps; see ``_decide_in_process``.
    """
    from _harness import _decide_module as load

    return load()


def _decide_ast() -> ast.Module:
    return _script_ast(DECIDE)


def _forced_commit_failure():
    """The env a decide.py run needs to have its commit fail on purpose.

    The exit-5 rollback path is unreachable through inputs: every input that
    could make git refuse the commit is refused earlier by an exit 2, 3 or 4
    check, so the only way to watch a rollback happen is to inject the failure.
    The injection is a real (if narrow) property of the product: a committed
    record's bytes can be clobbered out of band, which is exactly the state the
    rollback exists to undo, and no input flag reproduces it.

    The variable's name comes from decide.py's own ``FAIL_COMMIT_ENV_VAR``
    constant (read off the loaded module, not copied), so renaming the seam in
    the product fails these two tests instead of leaving them quietly exercising
    a real commit.

    The env seam has exactly one value, ``1``: it makes the commit step fail and
    nothing else. A per-verb or per-rc form is not a property of the writer, so
    the tests that need one specific git call to fail inject it in-process
    (``_git_spy``) instead of widening the variable.
    """
    return {**_identity_env(), _decide_module().FAIL_COMMIT_ENV_VAR: "1"}


def _identity_env() -> dict:
    """The harness git identity, for a test that must add one variable."""
    return dict(_harness_identity_env())


def _no_identity_env(tmp_path: Path) -> dict:
    """An env with no gitconfig anywhere and no author vars: the identity-less run."""
    return {
        "PATH": sys.executable.rsplit("/", 2)[0] + ":/usr/bin:/bin",
        "HOME": str(tmp_path / "no-home"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }


def _supersede(repo: Path, target_id: str, env: dict | None = None,
               date: str | None = None) -> subprocess.CompletedProcess[str]:
    """The standard supersede of ``target_id``, for the hardening tests.

    ``date`` is the run's ``--date`` and defaults to the baseline's own day,
    which is the day every hardening assertion derives its new record's id
    from; a caller that wants a cross-day supersede names one.
    """
    return _run(
        repo,
        "--slug", "scheduler",
        "--date", date or BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", target_id,
        env=env,
    )


def _docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "decide.py has no module docstring"
    return doc


def _module_exit_codes(tree: ast.Module) -> set[int]:
    """The codes the EXIT_* module constants hold, read from the source."""
    codes: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{target.id} is not an int"
                codes.add(value.value)
    assert codes, "decide.py defines no EXIT_* constants"
    return codes


def _doc_exit_codes(doc: str) -> set[int]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Exit codes:")
    except StopIteration:
        raise AssertionError("docstring has no 'Exit codes:' block") from None
    codes: set[int] = set()
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            codes.add(int(head[0]))
    assert codes, "the 'Exit codes:' block lists no codes"
    return codes


def _parser_flags(tree: ast.Module) -> set[str]:
    """The long options the parser declares, read from main()."""
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.startswith("--"):
                            flags.add(arg.value)
    assert flags, "no add_argument calls found in main()"
    return flags


def _doc_usage_flags(doc: str) -> set[str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Usage:")
    except StopIteration:
        raise AssertionError("docstring has no 'Usage:' block") from None
    flags: set[str] = set()
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, "the 'Usage:' block names no flags"
    return flags
