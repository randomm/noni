"""Shared fixtures for the claim.py test modules.

The claim suite is split across files by subject (the guards, the no-commit
rule, the rebase rules, and the census parity); this module holds the one copy
of the fixtures those files share. Pure moves from the file that covered all of
them: no behaviour here changed.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from _harness import (
    REPO,
    _claim_module,
    _git,
    _git_e2,
    _init_repo,
    _script_ast,
    run_from,
)

CLAIM = REPO / "skills" / "sessions-claims" / "scripts" / "claim.py"
SESSION_ID = "2026-10-01-aaaaaa"

# claim.py loaded as a module for the tests that drive its internals in-process
# (see _harness._claim_module: loaded by path under a name of our own, so no
# sys.path mutation and no collision with any other module named "claim").
claim_mod = _claim_module()

# The census scripts the parity tests run over the same sessions directory.
CENSUS_PY = REPO / "skills" / "census" / "scripts" / "census.py"
CENSUS_SH = REPO / "skills" / "sessions-claims" / "scripts" / "census.sh"


def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for c in claims or []:
        # Indented under the marker, the shape register.py writes and the
        # census parses; claim.py appends its own row at file EOF.
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _appended(body: str, tasks: list[str]) -> str:
    """``body`` plus one claim row per task, appended where claim.py puts
    them: at file EOF, unindented."""
    for task in tasks:
        body += f"- claim: {task}\n"
    return body


def _make_session(tmp_path: Path, session_id: str = SESSION_ID,
                  claims: list[str] | None = None) -> Path:
    repo = _init_repo(tmp_path / "repo")
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{session_id}.md").write_text(_session_body("dev", claims))
    _git(repo, "add", f"noni/sessions/{session_id}.md")
    _git(repo, "commit", "-q", "-m", "session")
    return repo


def _session_path(repo: Path, session_id: str = SESSION_ID) -> Path:
    return repo / "noni" / "sessions" / f"{session_id}.md"


def _git_blob(repo: Path, revision: str, rel_path: str) -> str:
    """The exact bytes of ``rel_path`` at ``revision`` (plumbing, no filters).

    ``git cat-file`` rather than ``git show``: show runs the working-tree's
    textconv / clean-smudge filters over the blob it prints and can hand back an
    empty string for a file that is plainly there, which would make a fixture
    precondition fail on a file that is fine. cat-file is the plumbing path and
    prints the stored blob; a revision without that path exits non-zero, and the
    caller decides whether absence is an answer or a failure.
    """
    proc = _git_e2(repo, "cat-file", "-p", f"{revision}:{rel_path}")
    assert proc.returncode == 0, (
        f"git has no {rel_path} at {str(revision)[:12]}: {proc.stderr.strip()}"
    )
    return proc.stdout


def _git_text(repo: Path, *args: str) -> str:
    """Stdout of a plumbing git call (no identity needed, so nothing is written)."""
    return _git_e2(repo, *args).stdout.strip()


# --- State-root (--repo) isolation fixtures -----------------------------------
#
# claim.py takes no positional path: the state root is --repo and nothing else,
# so the isolation fixture separates that root from the process cwd as far as
# the filesystem allows. One scratch root holds all three trees, so the decoy is
# neither a parent of nor a sibling of the state root by accident.

CLAIM_STATE_ARG = "claim-state"
CLAIM_CWD_ARG = "claim-cwd"
CLAIM_DECOY_ARG = "claim-decoy"
CLAIM_DECOY_TASK = "#999"


def _state_root(tmp_path: Path) -> Path:
    """The state repository: a git repo with one session, at a path that is
    neither the decoy nor the cwd.

    The run under test is launched from ``_claim_cwd`` with --repo naming this
    tree; because the tree's own name is not the caller's cwd, a run that
    resolved state from something other than --repo cannot land here by
    accident.
    """
    root = _init_repo(tmp_path / CLAIM_STATE_ARG)
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{SESSION_ID}.md").write_text(_session_body("dev"), encoding="utf-8")
    _git(root, "add", f"noni/sessions/{SESSION_ID}.md")
    _git(root, "commit", "-q", "-m", "session")
    return root


def _decoy_tree(tmp_path: Path) -> Path:
    """A tree holding a ``noni/`` the run under test must never read or write.

    The register carries a claim row no claim.py run of this test makes: a tool
    that resolved state from its own location or the cwd would append to this
    file, and the assertion on these exact bytes is what catches it. Not a git
    repository: a run driven by cwd would also fail to commit, so the row alone
    is the signal.
    """
    decoy = tmp_path / CLAIM_DECOY_ARG
    sessions = decoy / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{SESSION_ID}.md").write_text(
        _session_body("decoy", [CLAIM_DECOY_TASK]), encoding="utf-8")
    return decoy


def _claim_cwd(tmp_path: Path) -> Path:
    """The directory the isolated run launches from: empty, so a ``noni/`` it
    could read has to have been created by the run under test."""
    cwd = tmp_path / CLAIM_CWD_ARG
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd


def _claim_state_root_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one state-root run: (state root, decoy, cwd)."""
    root = _state_root(tmp_path)
    decoy = _decoy_tree(tmp_path)
    return root, decoy, _claim_cwd(tmp_path)


def _claim_from(cwd: Path, root: Path, task: str) -> subprocess.CompletedProcess[str]:
    """claim.py launched from ``cwd`` with ``--repo`` naming the state root.

    The wrapper path, not the package module: this is the entry point the skill
    documents and the one a reader copies, so it is the one whose cwd behaviour
    the contract covers.
    """
    return run_from(cwd, CLAIM, "--repo", str(root), "--session-id", SESSION_ID,
                    "--task", task)


def _claim_tree() -> ast.Module:
    """Parse claim.py once so the parity readers below share one tree and one
    read of the file instead of each paying for both."""
    return _script_ast(CLAIM)


def _claim_docstring(tree: ast.Module) -> str:
    """The module docstring, typed before use: ast.get_docstring returns
    Optional[str] and every reader below splits it unconditionally."""
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "claim.py has no module docstring"
    return doc


def _markdown_exit_codes(text: str, origin: str, only: set[int] | None = None) -> set[int]:
    """The codes in a markdown exit table: the rows are ``| `n` | meaning |``.

    The markdown copies of the claim exit table are the operator-facing
    contract; parsing them against the same constant set is what keeps them
    from renumbering quietly while the docstring parity test stays green.

    ``only`` restricts the parse to the codes the claim protocol owns: SKILL.md
    also carries the sessions-census table (30/31/32), which belongs to
    census-sessions.py and is not this script's contract.
    """
    rows = re.findall(r"^\|\s*`(\d+)`\s*\|", text, re.MULTILINE)
    assert rows, f"{origin} carries no '| `n` |' exit-code rows"
    codes = {int(m) for m in rows}
    if only is not None:
        claimed = codes & only
        assert claimed == only, (
            f"{origin} omits claim exit code(s) {sorted(only - claimed)} from its "
            f"table (it lists {sorted(codes)})"
        )
        codes = claimed
    assert codes, f"{origin} lists none of the claim codes {sorted(only or [])}"
    return codes


def _module_exit_codes(tree: ast.Module, origin: str = "claim.py") -> set[int]:
    """The set of codes the EXIT_* module constants hold, read via AST (no
    import: claim.py is a script the suite reaches as a subprocess).

    The constants carry an ``int`` annotation each, which makes this an
    AnnAssign node rather than an Assign; both forms are accepted so the check
    keeps working whichever way they are written. ``type() is int``, not
    isinstance: bool is an int subclass, and an exit code that drifted to
    True would otherwise pass.
    """
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
    assert codes, f"{origin} defines no EXIT_* constants"
    return codes


def _docstring_exit_codes(doc: str) -> set[int]:
    """The codes listed in the docstring's 'Exit codes:' block."""
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
            break  # the block ended; the prose after it is not an exit row
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            codes.add(int(head[0]))
    assert codes, "the 'Exit codes:' block lists no codes"
    return codes


def _parser_flags(tree: ast.Module) -> set[str]:
    """The long option strings claim.py's argparse parser declares."""
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.startswith("--"):
                        flags.add(arg.value)
    assert flags, "no add_argument calls found in main()"
    return flags


def _parser_dests(tree: ast.Module) -> dict[str, str]:
    """Map each long option string to the attribute name its action writes.

    The dash spelling alone is not the whole contract: claim.py reads
    ``args.no_commit``, so the dest is the other half and is what an alias or a
    renamed dest would silently break.
    """
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    dests: dict[str, str] = {}
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            opts = [
                arg.value for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and arg.value.startswith("--")
            ]
            dest = next(
                (
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)
                ),
                None,
            )
            if dest is None and opts:
                # argparse's own rule: the first long option, dashes to
                # underscores.
                dest = opts[0].lstrip("-").replace("-", "_")
            if dest:
                for opt in opts:
                    dests[opt] = dest
    return dests


def _docstring_usage_flags(doc: str) -> set[str]:
    """Every --flag token anywhere in the docstring's 'Usage:' block."""
    # Anchor on the line, not the word: the prose above the block mentions
    # 'the Usage line' and would otherwise win the split.
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
