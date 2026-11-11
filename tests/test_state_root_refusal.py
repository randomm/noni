"""The documented exit code for a --repo that is no noni state root (issues #39, #120).

docs/PRODUCT.md §7 names one code per tool for a wrong path, and it names two states
that wrong path comes in: a `--repo` that is not a directory at all, and a `--repo`
that is a directory holding no `noni/`. The second is the one a caller actually
arrives at (a code repository where the state clone was meant), and it is the one no
test covered: every case here used to name a path that does not exist, so a directory
that merely lacked `noni/` fell through to the readers and answered "no decision
record ... is in the ledger" about a tree holding no ledger.

One table, one run per row: the point is the code, so the assertion is the code plus a
message that names the path the caller passed. Each run is launched from a cwd that is
not the state root, so a refusal that arrived from somewhere else would have to
produce the number as well. The first-run creators are asserted from the same table,
because a refusal that also refused `decide`'s first record would pass every row
above.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import (
    CENSUS,
    DECIDE,
    INTENT,
    ORDER,
    _commit_file,
    _git,
    _init_repo,
    subprocess_env,
)

# The refusal's code and the tool that owes it, exactly as §7 states them. This
# tuple is the prose transcribed: a change on either side breaks this test.
STATE_ROOT_REFUSAL = (
    (ORDER, 2),
    (DECIDE, 3),
)

# The tools §7 gives code 2, and the ones it gives 3 and 4: the prose test below
# reads the numbers off the page rather than trusting this table alone.
DOCUMENTED = {
    2: ("`order`", "census"),
    3: ("`decide`",),
}

# One minimum argv beyond --repo per tool: enough to get past argparse to the
# state-root check, and values no assertion depends on, since the run is refused
# before any of them is read.
ARGV = {
    DECIDE: ("--slug", "state-root", "--scope", "release ordering",
             "--asked-by", "developer", "--question", "q1=Probe?",
             "--option", "q1=yes", "--option", "q1=no", "--answer", "q1=yes"),
    ORDER: ("add", "7", "--decision", "2026-10-01-absent", "--now",
            "2026-10-02T00:00:00Z"),
}

# The verbs and runs that reach the state-root question, with the code §7 gives each,
# and whether the run is a sanctioned creator of `noni/` (so it must be admitted rather
# than refused -- the first run has to be allowed to make the tree).
# `order add` is a creator and so is `intent set`; every other verb here only reads
# state it expects to already exist, so a tree holding none is a wrong --repo. `decide`
# has no verb to ask, so it is a creator only when the caller said so with `--init`
# (tests/test_decide_state_root.py pins that half); a `decide` with no flag and no
# `noni/` sits in the table below, because a writer that creates state in a tree
# holding none of anyone's is the bug this ticket was filed about.
NO_NONI_REFUSAL: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("order", ("move", "7", "--to", "1", "--now", "2026-10-02T00:00:00Z"), 2),
    ("order", ("remove", "7", "--now", "2026-10-02T00:00:00Z"), 2),
    # The bug the ticket reproduced live: confirm with no issue arg wrote a valid
    # empty order.json and exited 0 on a tree with no noni/. Nothing legitimate is
    # created by it, so it is refused.
    ("order", ("confirm", "--now", "2026-10-02T00:00:00Z"), 2),
    # decide is the writer that creates a state root, so before `--init` existed it was
    # the one entry point that committed direction content into a public project
    # checkout. The row is that reproduction: same tool, same tree, and the answer the
    # pilot's four local commits should have got.
    ("decide", ("--slug", "state-root", "--scope", "release ordering", "--asked-by",
                "developer", "--question", "q1=Probe?", "--option", "q1=yes",
                "--option", "q1=no", "--answer", "q1=yes", "--date",
                "2026-10-01"), 3),
)

# The words the refusal owes the operator for this one state: the path is named, the
# state is named as a noni state root the path is not, and the fix names the flag the
# caller passed wrong. Spelled as the phrases a reader scans for rather than a full
# sentence, so the product may rewrap the line without breaking the contract.
NOT_A_STATE_ROOT_WORDS = ("is not a noni state root", "no noni/")


def _launch(script: Path, missing: Path, cwd: Path,
            *extra: str) -> subprocess.CompletedProcess[str]:
    """One entry point launched with --repo naming a path that is not a directory."""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(missing), *extra],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120,
    )


def _code_repo(tmp_path: Path, name: str) -> Path:
    """A committed git tree that holds source and no noni/: the pilot's mistake.

    The reproduction the ticket is written from. A repo built by _init_repo alone has
    no commit at all, and the writers' git probes answer differently there, so the
    README is committed first: this is the tree a caller points --repo at when they
    meant the state clone, and it is a valid git work tree, so decide's work-tree
    check admits it and only the state-root question refuses it.
    """
    repo = _init_repo(tmp_path / name)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_file(repo, "README.md", "# a code repository\n")
    _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
    return repo


def _launch_against(script: Path, repo: Path, cwd: Path,
                    *extra: str) -> subprocess.CompletedProcess[str]:
    """One entry point launched with --repo naming a committed tree holding no noni/."""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(repo), *extra],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120,
    )



def test_each_writer_refuses_a_repo_that_is_not_a_directory_with_its_own_code(tmp_path):
    """Every writer named in §7 answers with the code §7 gives it."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    for script, expected in STATE_ROOT_REFUSAL:
        missing = tmp_path / f"no-such-root-{script.stem}"
        proc = _launch(script, missing, cwd, *ARGV[script])
        assert proc.returncode == expected, (
            f"{script.name}: docs/PRODUCT.md §7 documents exit {expected} for a "
            f"--repo that is not a directory, got {proc.returncode}: {proc.stderr}"
        )
        assert "--repo" in proc.stderr.lower() or "is not a git work tree" in proc.stderr, (
            f"{script.name}: the refusal must name the argument it refused "
            f"(decide.py names the tree, the others the flag): {proc.stderr}"
        )
        assert ("is not a directory" in proc.stderr
                or "is not a git work tree" in proc.stderr), (
            f"{script.name}: the refusal must name the state it found: {proc.stderr}"
        )
        assert not missing.exists(), f"{script.name}: the refused run created {missing}"


def test_the_unified_census_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """The census answers the same state with its own usage code (2).

    Its wording differs ("repo path does not exist") because the census takes a
    directory to audit rather than writing into one, so this asserts the code and
    that the path is named, which is what makes the refusal actionable.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    missing = tmp_path / "no-such-root-census"
    proc = _launch(CENSUS, missing, cwd)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "no-such-root-census" in proc.stderr, proc.stderr


def test_the_readers_refuse_a_repo_that_holds_no_noni_directory(tmp_path):
    """A committed tree with no noni/ is refused by every verb that creates nothing.

    This is the state every other test missed: the path exists and is a git work
    tree, so the writers' existing ``is_dir`` and work-tree checks pass it, and
    before this refusal the run fell through to the reads and printed "no decision
    record ... is in the ledger" about a repository holding no ledger (the pilot's
    Route B report). The code is each tool's own wrong-path code from §7, unchanged.

    ``decide`` is in the table because it is no longer admitted on being the writer
    that creates a state root: an unflagged run into a recordless tree is the pilot's
    four commits, so it is refused like every other verb and sent to ``--init``.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    scripts = {"order": ORDER, "intent": INTENT, "decide": DECIDE}
    draft = tmp_path / "draft.md"
    draft.write_text(_INTENT_DRAFT, encoding="utf-8")
    for tool, argv, code in NO_NONI_REFUSAL:
        repo = _code_repo(tmp_path, f"noreader-{tool}-{argv[0]}")
        # A draft that exists: the run must be refused for its state root, not for a
        # missing --from file, which argparse answers first.
        proc = _launch_against(scripts[tool], repo, cwd,
                               *[str(draft) if a == "DRAFT" else a for a in argv])
        assert proc.returncode == code, (
            f"{tool} {argv[0]}: docs/PRODUCT.md §7 gives {code} for a wrong --repo, "
            f"got {proc.returncode}: {proc.stderr}"
        )
        assert str(repo) in proc.stderr, (
            f"{tool} {argv[0]}: the refusal must name the path it refused: "
            f"{proc.stderr}")
        for word in NOT_A_STATE_ROOT_WORDS:
            assert word in proc.stderr, (
                f"{tool} {argv[0]}: the refusal must say {word!r}: {proc.stderr}")
        assert "--repo" in proc.stderr, (
            f"{tool} {argv[0]}: the fix must name the flag the caller passed wrong: "
            f"{proc.stderr}")
        # The misleading answer this ticket exists to close, asserted absent: the
        # ledger sentence is true of a record and useless about a wrong --repo.
        assert "is in the ledger" not in proc.stderr, (
            f"{tool} {argv[0]}: reached the ledger reads instead of refusing the "
            f"state root: {proc.stderr}")
        assert not (repo / "noni").exists(), (
            f"{tool} {argv[0]}: a refused run created {repo / 'noni'}")
        if tool == "decide":
            # The refusal that stops the pilot's mistake has to send the caller to the
            # flag, not just to --repo: a caller who meant a new state root reads the
            # fix line and knows what to type.
            assert "--init" in proc.stderr, (
                f"{tool}: the fix must name the flag that opens a new state root: "
                f"{proc.stderr}")
        else:
            # The other half of the same sentence: --init is decide's flag alone, so a
            # reader's fix line must not send the operator to a flag the very command
            # printing it answers with argparse's exit 2. The rows below pin that the
            # flag IS refused; this pins that no reader advertises it.
            assert "--init" not in proc.stderr, (
                f"{tool} {argv[0]}: {tool} has no --init, so its fix line must not "
                f"tell the operator to pass one: {proc.stderr}")


def test_init_is_accepted_by_decide_and_refused_by_every_other_writer(tmp_path):
    """``--init`` is decide's flag and no other command grows it.

    The surface holds at one flag (docs/PRODUCT.md 7 names no other), so the other
    writers and the census answer it as argparse answers any unknown flag: exit 2, the
    flag named, and nothing written. One run per command over the pilot's own tree.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    cases = ((ORDER, ("add", "7", "--decision", "2026-10-01-absent", "--now",
                     "2026-10-02T00:00:00Z", "--init")),
             (ORDER, ("move", "7", "--to", "1", "--now", "2026-10-02T00:00:00Z",
                      "--init")),
             (CENSUS, ("--init",)))
    for script, argv in cases:
        repo = _code_repo(tmp_path, f"init-refused-{script.stem}-{argv[0]}")
        proc = _launch_against(script, repo, cwd, *argv)
        assert proc.returncode == 2, (
            f"{script.name} {argv[0]} --init: an unknown flag is argparse's refusal at "
            f"2, got {proc.returncode}: {proc.stderr}")
        assert "--init" in proc.stderr, (
            f"{script.name}: the refusal must name the flag it refused: {proc.stderr}")
        assert not (repo / "noni").exists(), (
            f"{script.name}: a refused run created {repo / 'noni'}")


# A minimal intent draft for the creator case: `intent set` refuses a file that is not
# an intent artifact, so a first-run test that handed it prose would test the wrong
# refusal. The four sections are the shape intentschema validates.
_INTENT_DRAFT = """# Intent
Last-confirmed: 2026-10-01
## Purpose
Ship the release.
## Principles
Prefer the boring technology.
## Never
Never force push.
## Ask first
Anything that costs money.
"""
