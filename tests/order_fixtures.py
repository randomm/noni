"""Shared fixtures for the order.py writer test modules.

The order.py suite is split across files by subject (add, the verbs, the
artifact, usage, the git layer, the arbiter, the deep paths, the docs, and the
state root); this module holds the one copy of the fixtures those files share.
Pure moves from the file that covered all of them: no behaviour here changed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from _harness import (
    ORDER,
    REPO,
    _git,
    _git_e2,
    _init_repo,
    git_pin_date,
    load_package_module,
    run_order,
    subprocess_env,
)
from order_doc_readers import (
    SKILL_DIR,
    _doc_block,
    _doc_usage_flags,
    _docstring,
    _module_exit_codes,
    _order_ast,
    _parser_flags,
    _skill_section,
)

__all__ = [
    "CENSUS", "ORDER", "REPO", "SKILL_DIR", "FIXTURE", "ORDER_REL", "NOW", "STAMP",
    "BASELINE_ID", "BASELINE_DATE", "SUPERSEDING_ID", "RIVAL_DATE", "SEED_STAMP",
    "ORDERING_CHECKS",
    "_schema_module", "_gitwrite_module", "_order_module", "_orderstate_module",
    "_order_path", "_read", "_issues", "_repo", "_record_json", "_commit_record",
    "_supersede_baseline", "_order", "_order_inprocess", "_census_ordering",
    "_assert_census_clean", "_head_paths", "_porcelain", "_canonical", "_seed",
    "_spied_git", "_writer_git_call", "_git_verb", "_entry", "_rival_commit",
    "_committed_order", "_schema_case",
    "_doc_block", "_doc_usage_flags", "_docstring", "_module_exit_codes",
    "_order_ast", "_parser_flags", "_skill_section",
]

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
FIXTURE = REPO / "tests" / "fixtures" / "ordering" / "order-valid.json"

ORDER_REL = "noni/direction/order.json"
NOW = "2026-10-27T12:00:00Z"
STAMP = "2026-10-27T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
BASELINE_DATE = "2026-10-01T10:00:00Z"
SUPERSEDING_ID = "2026-10-20-scheduler"

# The stamp the rival writer of the race tests commits at, and the stamp its
# losing opponent's baseline is seeded at. Both differ from ``NOW`` for the same
# reason and the same verb: a run whose planned bytes equal the bytes already on
# disk takes the writer's no-change shortcut and returns before the guard is
# reached, so a race test built on such bytes would be measuring the shortcut and
# not the probe.
RIVAL_DATE = "2026-11-02T09:00:00Z"
SEED_STAMP = "2026-10-20T08:00:00Z"

# The three ordering checks, so a census here arbitrates the artifact and
# nothing else: the hygiene class is not this writer's contract (a tree with no
# deny-list reports it as a warn, which --strict promotes to 50), and the ledger
# and session groups have their own writers and their own tests.
ORDERING_CHECKS = ("ordering-malformed", "ordering-stale", "ordering-closed")


def _schema_module() -> object:
    """orderschema.py as a fresh module object: the artifact's shape, from the product.

    The tests that need the canonical renderer or the timestamp parser ask the
    module that owns them. A copy of the contract in the test file would be a
    second one, so this is the product's code, exec'd again under a private name
    rather than the shared package module: the seam test replaces ``order_bytes``
    on the *shared* module (which is what the writer resolves), and a test that
    rendered from that same object afterwards would inherit the lie.
    """
    return load_package_module("orderschema")


def _gitwrite_module() -> object:
    """gitwrite.py loaded as a module, for the tests that name its constants.

    Returned as the writer itself resolves it -- ``noni.order_gitwrite`` -- and not
    through the bare ``order_gitwrite`` alias ``tests/harness_module.py`` registers
    for the skill wrappers. The two names can bind two module objects (the alias is
    ``setdefault``, so an earlier import of the bare name wins for that name), and a
    test that patched one while the writer called the other would measure nothing:
    every patched call of the test would land on a copy and the run would go ahead as
    if the guard were absent.
    """
    import importlib

    return importlib.import_module("noni.order_gitwrite")


def _order_module() -> object:
    """order.py loaded as a module, for the tests that drive its internals.

    ``noni.order``, for the same reason ``_gitwrite_module`` asks for its qualified
    name: the in-process tests patch ``module.gitwrite``, so the module they hand
    back and the module the writer runs must be one object.
    """
    import importlib

    return importlib.import_module("noni.order")


def _orderstate_module() -> object:
    """orderstate.py loaded as a module, for the tests that drive its reads.

    The two JSON reads are what these tests ask about, and they are reached
    directly: no verb of the writer reads a record on the way to the answer a
    subprocess run would print, and a copy of the read in the test file would be
    a second contract for it.
    """
    from noni import orderstate

    return orderstate


def _order_path(repo: Path) -> Path:
    return repo / ORDER_REL


def _read(repo: Path) -> dict:
    return json.loads(_order_path(repo).read_text(encoding="utf-8"))


def _issues(repo: Path) -> list[int]:
    return [entry["issue"] for entry in _read(repo)["entries"]]


def _repo(tmp_path: Path, subdir: str = "repo") -> Path:
    """A repo whose ledger holds one committed decided record at a pinned date.

    A committed baseline record is what makes ``--decision`` answerable without
    every test having to write its own ledger: the writer looks a decision id up
    by its filename stem, so the id in a test is a file the census can also see.
    ``subdir`` lets one test build two trees without the second finding the
    first already there.
    """
    repo = _init_repo(tmp_path / subdir)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_record(repo, BASELINE_ID, "decided", None)
    return repo


def _record_json(record_id: str, status: str, supersedes: str | None) -> str:
    return json.dumps(
        {
            "id": record_id,
            "date": f"{record_id[:10]}T00:00:00Z",
            "asked_by": "developer",
            "questions": [
                {
                    "id": "q1",
                    "text": "Which order do we work the queue in?",
                    "options": ["as listed", "by risk"],
                    "answer": "as listed",
                }
            ],
            "by": "Replay",
            "scope": "release ordering",
            "status": status,
            "supersedes": supersedes,
        },
        indent=2,
    ) + "\n"


def _commit_record(repo: Path, record_id: str, status: str, supersedes: str | None) -> None:
    """Commit one decision record under a pinned date."""
    rel = f"noni/decisions/{record_id}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_record_json(record_id, status, supersedes), encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, f"{record_id[:10]}T00:00:00Z", "commit", "-q", "-m",
                 f"steering: {record_id}")


def _supersede_baseline(repo: Path) -> None:
    """Move the chain past the baseline record, the way decide.py does.

    A supersede is two committed bytes-changes, not one: the new record
    supersedes the target and the target's own status becomes superseded. A
    fixture that wrote only the new record would leave the target decided, and
    the writer's refusal would then have nothing to refuse, which is how a
    supersede test can pass for the wrong reason.
    """
    _commit_record(repo, SUPERSEDING_ID, "decided", BASELINE_ID)
    target = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    body = json.loads(target.read_text(encoding="utf-8"))
    body["status"] = "superseded"
    target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", target.relative_to(repo).as_posix())
    git_pin_date(repo, NOW, "commit", "-q", "-m",
                 f"steering: supersede {BASELINE_ID} with {SUPERSEDING_ID}")


def _order(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run order.py with exactly the arguments given, identity pinned to Replay."""
    return run_order(repo, *args, env=env)


def _order_inprocess(repo: Path, *args: str) -> tuple[int, str, str]:
    """Run one order.py verb in-process and return ``(code, stdout, stderr)``.

    The guard tests need this rather than a subprocess: a freshness probe, a lying
    ``git show`` or a tripwire on ``write_atomic`` is a patch on the module object,
    and the writer only sees it if it runs *in that object*. Spawning the skill
    wrapper would run the installed copy of the package -- a different module, an
    unpatched helper, and a run that reports success for a guard that was never
    installed. Everything else is the subprocess launcher's own contract: the same
    argv after ``--repo``, the same ``main()`` entry point, the same two streams.
    """
    module = _order_module()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(["--repo", str(repo), *args])
    return code, out.getvalue(), err.getvalue()


def _census_ordering(repo: Path, *extra: str) -> tuple[int, list[dict], str]:
    """The unified census over the three ordering classes: the writer's arbiter."""
    args = ["--repo", str(repo), "--json", "--now", NOW]
    for check in ORDERING_CHECKS:
        args += ["--only", check]
    args += list(extra)
    proc = subprocess.run(
        [sys.executable, str(CENSUS), *args],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    findings = [r for r in rows if r.get("kind") == "finding"]
    return proc.returncode, findings, proc.stdout + proc.stderr


def _assert_census_clean(repo: Path, context: str, *extra: str) -> None:
    code, rows, output = _census_ordering(repo, *extra)
    assert code == 0, f"ordering census not clean after {context} (exit {code}):\n{output}"
    assert not rows, f"unexpected ordering rows after {context}: {rows}"


def _head_paths(repo: Path) -> list[str]:
    out = _git_e2(repo, "show", "--format=", "--name-only", "HEAD").stdout
    return [line for line in out.splitlines() if line.strip()]


def _porcelain(repo: Path, *rels: str) -> str:
    return _git_e2(repo, "status", "--porcelain", "--", *rels).stdout.strip()


def _canonical(entries: list[dict]) -> str:
    """The bytes the writer itself emits for ``entries``, via its own renderer.

    A fixture that hand-wrote the canonical form would be a second copy of the
    contract; deriving it from the product's function is what keeps a form change
    from silently turning every canonical fixture into a refusal. The renderer
    lives in the skill's own schema module, loaded the way the writer loads it.
    """
    schema = _schema_module()
    return schema.order_bytes({"schema": schema.ORDER_SCHEMA, "entries": entries}).decode()


def _seed(repo: Path, *entries: dict, message: str = "direction: seed the order") -> None:
    """Commit the artifact holding ``entries`` in the writer's own canonical form."""
    body = _canonical([dict(e) for e in entries])
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", message)


def _spied_git(real_run, seen: list[list[str]]):
    """A stand-in for the writer's git helper that records each command line.

    Deliberately not a wrapper around the real helper: this records the argv the
    writer built, which is the contract under test (the hardening flags, and the
    `-- path` that scopes the commit), and delegates only the execution. A test
    that patched subprocess.run instead would see the harness's git calls too
    and would have to guess which were the product's.
    """
    def git(repo_arg: Path, *args: str):
        cmd = [
            "git", "-C", str(repo_arg),
            "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={os.devnull}",
            "-c", "protocol.ext.allow=never",
            "-c", "core.fsmonitor=false",
            *args,
        ]
        seen.append(cmd)
        return real_run(cmd, capture_output=True, text=True, errors="replace",
                        timeout=_gitwrite_module().GIT_TIMEOUT)

    return git


def _writer_git_call(cmd: object, repo: Path) -> bool:
    """Whether ``cmd`` is one of the writer's own git calls, not the harness's.

    The spy wraps subprocess.run, which the fixture's own git calls go through
    too. The harness pins an identity as its first -c pair; the writer never
    does, so the shape of the -c block tells the two apart, along with the tree
    each call names.
    """
    if not isinstance(cmd, list) or cmd[:2] != ["git", "-C"] or len(cmd) < 4:
        return False
    if cmd[2] != str(repo):
        return False
    return cmd[3] != "-c" or not cmd[3 + 1].startswith("user.name=")


def _git_verb(cmd: list[str]) -> str | None:
    """The git verb of one of the writer's own calls: the word after the -c block."""
    index = 3
    while index + 1 < len(cmd) and cmd[index] == "-c":
        index += 2
    return cmd[index] if index < len(cmd) else None


def _entry(issue: int, decision: str = BASELINE_ID, confirmed: str = STAMP) -> dict:
    return {"issue": issue, "decision": decision, "confirmed": confirmed}


def _rival_commit(repo: Path, entries: list[dict],
                  message: str = "direction: rival writer commits first") -> None:
    """Commit ``entries`` at the artifact path, then leave the tree as it was found.

    The deterministic half of the two-writer race (issue #116): the real race is a
    window of milliseconds, so racing processes would be flaky by construction, and
    what has to be reproduced is the state the losing run reaches its write phase in
    -- one sentence, HEAD moved after this run read.

    Three things have to be true at once, which is why this is a fixture and not a
    bare commit:

      HEAD  -- moved, so the run's commit would overwrite an order it never read.
      file  -- left exactly as it was found, because "HEAD moved after this run
               read" is the state under test and nothing else: a rival that also
               rewrote the working copy would be caught by the reader's own
               comparison, which is a different case with a different message.
      the run's plan -- still a write, so the run cannot take the no-change
               shortcut and exit 0 having committed nothing.

    So the fixture commits the entries it is handed with the rival's own stamp on
    every entry (bytes that differ from HEAD's, so git makes the commit rather than
    refusing an empty one), and puts the file back byte for byte afterwards. The
    caller seeds the order first: the seeded bytes are then the baseline the losing
    run reads, and the only thing that has moved by the time it writes is HEAD.

    Committing the rival's brand-new entries and leaving them in the tree instead
    would model something else entirely -- a run that read the rival's order and
    wrote it back -- which is a correct run, and refusing it would be a bug.

    The commit goes through :func:`git_pin_date` rather than a bare ``_git``: the
    writer's git calls run under ``gitenv.child_env()``, which strips every ``GIT_*``
    name and sandboxes ``HOME``, so a rival committed with the ambient identity is a
    commit the writer's ``git show`` cannot always resolve -- the probe then reads
    "nothing committed" where HEAD holds the rival's order, and the run this guard
    exists to refuse goes ahead. Pinned identity and date are what both can see.
    """
    target = _order_path(repo)
    parent_existed = target.parent.is_dir()
    as_the_run_read_it = target.read_bytes() if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([dict(entry) for entry in entries]), encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, RIVAL_DATE, "commit", "-q", "-m", message)

    # Undo the rival's write, everything but the commit. Three things move together
    # in a `git add` and a commit, and leaving any one of them behind describes a
    # scenario that is not this one:
    #
    #   HEAD   -- left where the rival put it, which is the whole point. This is a
    #            real commit and not a rewound history: `git reset` here would move
    #            HEAD back and erase the very thing the guard is meant to notice.
    #   file   -- back to the exact bytes the losing run reads, or unlinked when it
    #            read no file at all.
    #   index  -- back to the commit this run read against, so the tree reports no
    #            staged change the rival's `git add` made and the writer's own
    #            `git add` cannot stage it. `--mixed` on the path, so the working
    #            copy keeps the bytes restored below.
    _git(repo, "reset", "--quiet", "HEAD~1", "--", ORDER_REL)
    if as_the_run_read_it is None:
        target.unlink()
        # Tolerated rather than checked: when the rival's order was the path's first
        # appearance in HEAD, the reset above already took it out of the index, and
        # `git rm --cached` on a path the index does not know exits 128. The state
        # wanted is "the index does not hold this path", which both answers leave.
        _git(repo, "rm", "--cached", "--ignore-unmatch", "--quiet", "--", ORDER_REL)
        if not parent_existed:
            target.parent.rmdir()
    else:
        target.write_bytes(as_the_run_read_it)


def _committed_order(repo: Path) -> bytes | None:
    """What HEAD holds at the artifact path, or ``None`` when nothing is there.

    Read straight from git rather than through the writer's own probe, so a test
    can assert what the committed order is without trusting the code under test to
    report it. The harness's ``_git`` returns no stdout, hence ``_git_e2``.
    """
    shown = _git_e2(repo, "show", f"HEAD:{ORDER_REL}")
    if shown.returncode != 0:
        return None
    return shown.stdout.encode("utf-8")


# --- add ----------------------------------------------------------------------


def _schema_case(**entry_fields):
    """A well-formed document whose single entry has ``entry_fields`` overridden,
    or gained when the name is not one of the entry's three fields."""
    schema = _schema_module()
    entry = {"issue": 1, "decision": BASELINE_ID, "confirmed": "2026-10-27T12:00:00Z"}
    for name, value in entry_fields.items():
        entry[name] = value
    return {"schema": schema.ORDER_SCHEMA, "entries": [entry]}


<<<<<<< HEAD
def _order_ast() -> ast.Module:
    return _script_ast(ORDER)


def _docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "order.py has no module docstring"
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
    assert codes, "order.py defines no EXIT_* constants"
    return codes


def _doc_block(doc: str, header: str) -> dict[int, str] | dict[str, str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise AssertionError(f"docstring has no {header!r} block") from None
    block: dict = {}
    current = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif isinstance(current, int):
            block[current] += " " + line.strip()
    assert block, f"the {header!r} block is empty"
    return block


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


# --- State root: the artifact path resolves from --repo and nothing else -------
#
# order.py's artifact lives at a fixed path under the state root, so the whole
# contract is whether that root is the one --repo named. The three trees: a
# separate state repository holding the ledger the writer cites, a decoy order
# file beside the cwd carrying an order no run of these tests makes, and an
# empty cwd a stray write would show up in.

ORDER_STATE_DIR = "order-state-root"
ORDER_CWD_DIR = "order-cwd"
ORDER_DECOY_DIR = "order-decoy"
# An order the decoy holds and no test writes: the entry, not just the file, is
# the thing a comparison can prove nobody touched.
ORDER_DECOY_ISSUE = 999

def _order_state_root(tmp_path: Path) -> Path:
    """The state repository: a git repo with an identity and the baseline
    record ``add --decision`` cites, and no order file yet."""
    root = _repo(tmp_path, ORDER_STATE_DIR)
    _git(root, "config", "user.name", "Replay")
    _git(root, "config", "user.email", "replay@fixture.invalid")
    return root


def _order_decoy(tmp_path: Path) -> Path:
    """A decoy state root beside the cwd: a git repo holding one committed
    ordering artifact, so a cwd-driven run would have had an order to overwrite.

    A git repository for the same reason as decide.py's decoy: a plain directory
    would make the writer's own path probes answer first, and the test would
    measure the probe rather than the resolution.
    """
    decoy = _init_repo(tmp_path / ORDER_DECOY_DIR)
    _git(decoy, "config", "user.name", "Replay")
    _git(decoy, "config", "user.email", "replay@fixture.invalid")
    commit_artifact(decoy, _canonical([_entry(ORDER_DECOY_ISSUE, BASELINE_ID)]))
    return decoy


def _order_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one order state-root run: (state root, decoy, cwd)."""
    root = _order_state_root(tmp_path)
    decoy = _order_decoy(tmp_path)
    cwd = tmp_path / ORDER_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _order_from(cwd: Path, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """order.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, ORDER, "--repo", str(repo), *args)

=======
>>>>>>> 29aa8ac (fix(work): order writes silently drop a concurrent writer's…)
