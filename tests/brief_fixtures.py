"""Shared builders for the brief suite: the committed tree and its planted variants.

A helper module (never named ``test_*``, so pytest never collects it as a suite of its
own), following ``order_fixtures.py`` and ``items_fixtures.py``: the one copy of the
fixture path, the tree copier, and the planter every case in the brief's suite shares. A
fixture one test quietly relaxed would make the other's green meaningless, so none of them
carries a private copy.

The committed fixture is ``tests/fixtures/brief.tar``: a git repository holding the state
root the brief reads -- 11 order entries, 12 candidate items (two pairs sharing a
``created`` stamp), one intent file whose ``## Purpose`` body runs past the 20-line clip,
and one decision record the order and the intent both cite. It travels as a tar rather
than a directory because a repository's own ``index`` and pack files are binary and the
purity suites below read every file under ``tests/fixtures/`` as text. It is unpacked, not
symlinked, into the caller's ``tmp_path`` and its ``.git`` is renamed to ``.git-brief``
before any brief run:

- **Copied**, so a planted defect reaches one test's tree and no other test's.
- **Renamed rather than deleted**, because the tree's own history is what makes the
  census's ``intent`` class answer ``decided`` rather than ``uncited``, and the census
  reads history only through ``git -C <top>`` -- which resolves ``<top>/.git``, so a
  second ``.git`` sitting beside the working tree is invisible to it.

Malformed-input variants are planted into the copy and never into the committed fixture.
The purity and scrub suites (``test_purity``, ``test_skill_scrub``) walk every file under
``tests/fixtures/`` and read a tar's members as text, so a symlink or a non-UTF-8 byte
committed there would fail those suites rather than the brief's: the shapes that test the
brief's fault arms are planted by the test that needs them.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _harness import REPO, _git
from harness_runners import run_noni, subprocess_env

# The one spelling of the committed fixture's location. A test that hard-coded the
# path would keep passing after the tree moved and then assert about a file nothing reads.
FIXTURE = REPO / "tests" / "fixtures" / "brief.tar"

# The fixture tree's layout, as the tar names it and as the planted copy finds it. Spelled
# once so a reader of this file can see what the committed fixture holds without unpacking it.
FIXTURE_LAYOUT = {
    # The record the order's eleven entries and the intent file's own citation commit name.
    "noni/decisions/2026-10-01-brief.json": "one decided record, the whole tree's provenance",
    "noni/direction/order.json": "eleven entries, the fourth citing an item (noni.order/2)",
    "noni/direction/intent.md": "four sections, one stamp, a 25-line Purpose body",
    "noni/items/idea-0001.json": "twelve candidates; two pairs share a created stamp",
}


# The record id the fixture's order and intent both cite, so one committed record holds
# the whole tree's provenance and the census reports no ``intent`` row for it.
RECORD_ID = "2026-10-01-brief"

# The instant every brief run in the suite fixes. ``--now`` is passed verbatim to the
# census, so this is the one stamp both the brief's blocks and the verdict line are
# computed against, and the byte-equality cases depend on it appearing in both commands.
NOW = "2026-10-27T09:00:00Z"

# The stamps the fixture's twelve candidates carry, newest first, and the id the order's one
# item entry cites. Named here so the ordering cases state the fixture's own data rather than a
# number a reader has to go and count in the committed tree, and so a rebuild of the fixture
# that changes one of them fails a case instead of quietly proving less.
CREATED_NEWEST = "2026-10-24T09:00:00Z"
CREATED_TIED = ("idea-0001", "idea-0002")
ORDER_CITATION = "idea-0009"

# The ``confirmed`` stamp every order entry of the fixture carries, and the date the decided record is
# dated. An entry confirmed outside the census's staleness window of :data:`NOW` is reported
# ``ordering-stale``, and a record dated after the brief instant is dated a day the tree has not seen;
# both would put a row in the verdict line the read-only cases assert byte for byte. Named here so the
# builder writes the stamp and the cases that reason about staleness read the same value.
CONFIRMED = "2026-10-26T00:00:00Z"

# The twelve candidates grouped by the ``created`` stamp they carry, newest stamp first. The
# fixture's own statement of who was created when, and the single source the builder of
# ``tests/fixtures/brief.tar`` writes those stamps from: a case that asks what the newest-first
# block must print and the file that puts the stamps on disk read one table, so the pair cannot
# disagree about which ideas tie. Four of the eight instants carry a pair, and the pair named by
# :data:`CREATED_TIED` is the one whose order the tie-break decides.
ITEM_STAMPS: dict[str, tuple[str, ...]] = {
    "2026-10-24T09:00:00Z": ("idea-0001", "idea-0002"),
    "2026-10-24T08:00:00Z": ("idea-0007",),
    "2026-10-22T09:00:00Z": ("idea-0003", "idea-0004"),
    "2026-10-22T08:00:00Z": ("idea-0008",),
    "2026-10-20T09:00:00Z": ("idea-0005", "idea-0006"),
    "2026-10-20T08:00:00Z": ("idea-0009",),
    "2026-10-18T08:00:00Z": ("idea-0010", "idea-0011"),
    "2026-10-16T08:00:00Z": ("idea-0012",),
}

# What each candidate is called, keyed by id. The titles are the text the page prints, and two cases
# edit one of them out of the committed file to build their own scenario, so the words live beside the
# stamps the builder writes them from: a rebuild that renamed an item would fail those cases with a
# message that names the title instead of a missing-substring failure a reader has to trace.
ITEM_TITLES: dict[str, str] = {
    "idea-0001": "Cache the census result",
    "idea-0002": "Replay a decision into a fresh clone",
    "idea-0003": "Show the kill list beside the queue",
    "idea-0004": "One screen for the whole direction",
    "idea-0005": "Carry the rationale into the order",
    "idea-0006": "Name the state root in every refusal",
    "idea-0007": "Keep the order short",
    "idea-0008": "Read the ledger once per run",
    "idea-0009": "Explain a failing census",
    "idea-0010": "Print the queue the operator set",
    "idea-0011": "Bound every foreign message",
    "idea-0012": "Leave the tree exactly as it was",
}

# The fixture's purpose body, first line first. The two clip cases count against this tuple, so
# the committed file and the cases that depend on its length are one fact rather than two.
PURPOSE_LINES: tuple[str, ...] = (
    "Ship the direction layer, and keep it a layer a person reads.",
    "The order is the operator's own list, held in one committed file.",
    "Every claim is a signal, never a lock, and the census is the arbiter.",
    "A decision survives the session that made it or it is not a decision.",
    "Plain files under git are the only truth this product keeps.",
    "Metrics are derived from history, never reported by the thing measured.",
    "The state root is named by one flag and read from that one answer.",
    "Nothing here contacts a tracker: the issue number is only a number.",
    "A refusal names the path, the state and the fix, in that order.",
    "The census reports what it read and says what it could not read.",
    "An unreadable file is never the same report as an absent one.",
    "The brief is four blocks and a verdict, and it never writes.",
    "A tool that could not read its input does not call the tree clean.",
    "Every foreign message is scrubbed and bounded before it is printed.",
    "Adapters live outside the core and the core stays viable without them.",
    "A page that is true today and false in two hundred pull requests",
    "is not documentation, so this file states principles, not steps.",
    "Position in the queue is the operator's word and nobody else's.",
    "An item is one idea, filed once, and its reason is never deleted.",
    "Steering never answers for the operator; a question stays a question.",
    "The intent file is read first at session start and capped at a page.",
    "Superseding is the correction; the original record keeps its place.",
    "Scripts exist only where an exit code has to be honest.",
    "Two runs over one tree with one instant print the same bytes.",
    "What is not required is not built.",
)

# The subject of the commit :func:`commit_at` makes, and the register file's path. The
# census's ``intent`` class reads the subject of the last commit that touched the intent file,
# so a case adding a commit must leave that subject alone; the register file's name is the
# shape the sessions census allocates (a date and six hex digits), which
# :mod:`noni.census_sessions_checks` refuses anything else as ``session-malformed``.
STALL_COMMIT_SUBJECT = "session activity"
SESSION_REL = "noni/sessions/2026-10-20-abcdef.md"

# The state-root paths the brief reads, spelled once for the cases that plant one of them.
INTENT_REL = "noni/direction/intent.md"
ORDER_REL = "noni/direction/order.json"
ITEMS_REL = "noni/items"
DECISIONS_REL = "noni/decisions"

# The line the brief's read-fault blocks print, and the verdict it prints when the census
# produced none. Both are the tool's constants, read from the product so a rename that would
# strand an assertion makes the assertion fail instead of quietly asserting nothing.
from noni import brief as brief_module  # noqa: E402

NOT_READ = brief_module.NOT_READ
NOT_RUN_SUMMARY = brief_module.NOT_RUN_SUMMARY


def plant_brief_tree(tmp_path: Path, name: str = "repo") -> Path:
    """Unpack the committed brief tree into ``tmp_path`` and hand back the copy.

    Unpacked from a tar and not copied from a directory: the committed fixture is a
    git repository, and the suites that read every file under ``tests/fixtures/`` as
    UTF-8 would fail on the repository's own binary files. A tar keeps them out of the
    index. See ``FIXTURE``.

    ``.git`` is renamed to ``.git-brief`` on the way, which is what makes the copy
    invisible to any *outer* repository while leaving the census able to read the
    history: the census resolves ``--repo`` to a git top-level, so a second ``.git``
    beside a working tree is the only one it will find, and ``.git-brief`` is not it.
    A case that wants the census to see the history uses :func:`restore_history` or
    :func:`run_brief_with_history`, which put the name back for the length of the run.
    """
    target = tmp_path / name
    if target.exists():
        # A caller planting a state root inside a directory that already holds something
        # (a second repository, say) is the case this covers: the copy refuses a
        # destination that exists, and that refusal is not what the caller came for.
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(FIXTURE) as archive:
        archive.extractall(target)
    (target / ".git").rename(target / ".git-brief")
    return target


def item_path(root: Path, item_id: str) -> Path:
    """The store path of one candidate of the fixture, spelled from the fixture's own id."""
    return root / ITEMS_REL / f"{item_id}.json"


def order_path(root: Path) -> Path:
    """The ordering artifact of one planted tree."""
    return root / ORDER_REL


def intent_path(root: Path) -> Path:
    """The standing intent file of one planted tree."""
    return root / INTENT_REL


def record_path(root: Path) -> Path:
    """The one decision record the fixture's order and intent both cite."""
    return root / DECISIONS_REL / f"{RECORD_ID}.json"


def run_brief(root: Path, *extra: str) -> tuple[int, str, str]:
    """``noni brief`` as a launched command, with its exit code, stdout and stderr.

    Launched, for two reasons that both matter more than the speed of an in-process call.

    The census caches what it learned about a tree for the life of the process: the run records
    the tree it is auditing and resolves that tree's git top-level once. The brief runs that census
    in process for its own last line, so a suite that called the brief in process would have every
    case after the first reading the *first* case's tree -- and a fixture planted under ``tmp_path``
    is a different tree every time. The launched route is the only one where each run sees the tree
    it was pointed at.

    It is also the route the operator, a skill and a driver have, so the exit code and the bytes on
    the two streams are asserted as a process produces them rather than as a function returns them.
    The launched route is compared against the in-process call by
    :func:`tests.test_brief_entry_points.test_brief_the_console_route_prints_the_same_page`, which is where the
    dispatch layer's fidelity is what is being tested.
    """
    launched = run_noni("brief", "--repo", str(root), *extra)
    return launched.returncode, launched.stdout, launched.stderr


def run_brief_in_process(root: Path, *extra: str) -> tuple[int, str, str]:
    """:func:`run_brief` through ``brief.main`` in this process, for the seams only a call reaches.

    The census's own entry point does not exist as a thing a test can replace from outside, so the
    two cases that ask what the brief does when the arbiter says nothing, or dies saying it, patch
    it and must therefore run the brief in process too. Both ask about one tree in one process and
    neither compares a census run against another, which is what makes the cache above harmless
    here and fatal for the suite as a whole.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = brief_module.main(["--repo", str(root), *extra])
    return code, out.getvalue(), err.getvalue()


def run_brief_from(cwd: Path, root: Path, *extra: str) -> tuple[int, str, str]:
    """:func:`run_brief` with the process started in a directory that is not the state root.

    The brief has no cwd default -- ``--repo`` is required and resolved to an absolute path before
    any read -- so a run from elsewhere must print the same bytes as a run from the tree itself.
    """
    launched = run_noni("brief", "--repo", str(root), *extra, cwd=cwd)
    return launched.returncode, launched.stdout, launched.stderr


def run_brief_with_history(root: Path, *extra: str) -> tuple[int, str, str]:
    """:func:`run_brief` with the planted tree's own ``.git`` visible to the census.

    :func:`plant_brief_tree` renames ``.git`` out of the way so an outer repository cannot see a
    planted tree's files and a copy cannot be read as part of the suite's own repository. The
    census needs that name to be there to answer anything about history at all: it resolves the
    state root to a git top-level and, finding none, reports ``hygiene``, ``intent`` and
    ``session-stalled`` as states it could not tell. A case that asks what the verdict says about
    a session, a claim or a citation has to put the history back for the length of the run, which
    is what this does and what :func:`restore_history` alone cannot do -- that helper leaves the
    name in place only while its own block runs, and the brief run is the point of the block.
    """
    with restore_history(root):
        return run_brief(root, *extra)


def census_stdout(root: Path, *extra: str) -> tuple[int, str]:
    """The census's own stdout for one tree, for the summary-line equality assertion.

    Launched rather than called in process. The census records the tree under audit in a
    module-level slot (``census._set_run_root``) that each run overwrites, and the brief runs
    the census in process for its own last line: a suite that ran both in one process would be
    asserting about whichever tree ran last, and a case whose tree has no git at all would
    leak that run's recorded root into the comparison beside it. A launch is also the route a
    reader of this page actually has.
    """
    launched = subprocess.run(
        [sys.executable, "-m", "noni.cli", "census", "--repo", str(root), *extra],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    return launched.returncode, launched.stdout


def porcelain(root: Path) -> str:
    """``git status --porcelain`` of the tree's own repository.

    Used with the ``.git`` of a planted tree renamed back into place, so a read-only run is
    measured against the repository whose history it could have changed.
    """
    return _git(root, "status", "--porcelain").stdout


def porcelain_of(repo: Path, target: Path) -> str:
    """The status of ``target`` as seen from the repository at ``repo``.

    Asked with a path and not as a whole-tree status, because porcelain collapses an untracked
    *directory* to a single line: a tree that gained thirty files under ``noni/`` reports the same
    ``?? noni/`` as one that gained none, and a read-only assertion built on the collapsed form
    passes whether or not anything was written. With the path named, git walks it and prints what
    is actually in there.
    """
    relative = target.relative_to(repo).as_posix()
    return _git(repo, "status", "--porcelain", "--", relative).stdout


# The register file's path. The name is the shape the sessions census allocates -- a date and
# six hex digits, which :mod:`noni.census_sessions_checks` refuses anything else as
# ``session-malformed`` -- because a case that planted a file the census called malformed would
# be asserting about a fault of its own making and not about the stall window.
SESSION_REL = "noni/sessions/2026-10-20-abcdef.md"

# The register file's own fields, in the order the register's writer puts them and with the
# keys its reader reads. Held here rather than in the one case that needs it because the case
# asserts a census verdict, and a verdict that silently stopped being about staleness is the
# failure mode of a fixture whose file the reader never recognised in the first place.
def session_body(status: str = "active") -> str:
    """One register file for the planted tree, in the shape the sessions census reads.

    ``status: active`` is the only status the ``session-stalled`` class looks at: a closed or
    released session is never stale, so a case that planted a file without that field would
    prove that ``--now`` is forwarded by nothing at all.
    """
    return ("\n".join([
        "- identity: brief-verify",
        "- host/worktree: fixture",
        "- started: 2026-10-20T09:00:00Z",
        f"- status: {status}",
        "- claims:",
        "  - claim: issue-127",
    ]) + "\n")


def plant_session(root: Path) -> Path:
    """Write the register file into the planted tree; the caller commits it when it wants to.

    Written, not committed: the case that wants the file's history to predate one instant and
    postdate another is the case that decides when to commit it, and a helper that committed on
    the caller's behalf would fix the date of the very commit the case is about.
    """
    path = root / SESSION_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session_body(), encoding="utf-8")
    return path


def commit_at(root: Path, paths: list[str], when: str, subject: str) -> None:
    """Commit ``paths`` with a committer date of ``when``, identity pinned.

    The census's ``session-stalled`` class measures a session against the commit that last
    touched its register file -- and it reads the commit's *timestamp*, which git takes from
    the committer date. ``--date`` alone sets the author date, so a launcher that passed only
    that would leave every session looking as old as the fixture's own build and make the case
    a test of git's defaults. Both dates are set, and the run goes through :func:`_git`, which
    pins the author identity: a launched ``git commit`` with no identity and no ``--author``
    dies on a machine holding no ``user.name``, and the failure looks like a brief that could
    not render.
    """
    _git(root, "add", "-A", "--", *paths)
    # ``GIT_COMMITTER_DATE`` and not ``--author``: the census reads the commit's timestamp, git
    # takes that from the committer date, and ``--date`` alone moves only the author date. The
    # variable is set for this one call and restored after it, so no other git run in the case
    # finds its committer date pinned to an afternoon in 2026.
    previous = os.environ.get("GIT_COMMITTER_DATE")
    os.environ["GIT_COMMITTER_DATE"] = when
    try:
        _git(root, "commit", "-q", f"--date={when}", "-m", subject)
    finally:
        if previous is None:
            os.environ.pop("GIT_COMMITTER_DATE", None)
        else:
            os.environ["GIT_COMMITTER_DATE"] = previous


def restore_history(root: Path):
    """Put the fixture's ``.git`` back where git looks for it, for the duration of a block.

    A context manager rather than a pair of calls, so a case that asserts between the rename
    and the rename back cannot leave the tree with the two names half-swapped when one of its
    assertions fails -- a tree in that state makes the *next* case read a repository that is
    not the one it planted.
    """
    class _Restore:
        def __enter__(self) -> Path:
            hidden = root / ".git-brief"
            if hidden.exists() and not (root / ".git").exists():
                hidden.rename(root / ".git")
            return root

        def __exit__(self, *exc: object) -> None:
            real = root / ".git"
            if real.exists() and not (root / ".git-brief").exists():
                real.rename(root / ".git-brief")
            return None

    return _Restore()


def tree_paths(root: Path) -> set[str]:
    """Every path under ``root``, as repo-relative posix strings.

    The read-only assertion for a state root: the set of paths is compared before and after
    a run, so a write, a delete or a rename anywhere under the tree is a difference, not
    only a difference in the bytes of the files the brief reads.
    """
    return {path.relative_to(root).as_posix()
            for path in root.rglob("*") if ".git-brief" not in path.parts}
