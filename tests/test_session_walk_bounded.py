"""The session guard's walk is bounded by the state root, in both directions (issue #68).

Two faults lived in the walk, and they are opposite in kind, which is why one suite
holds both.

The first is a name that is not a file under the root at all. ``write_refusal`` walked
``while path != repo`` from the session file's parent, so a ``rel`` of ``.`` (or a
``..`` that stepped past the root) never equalled ``repo`` and the loop walked up to
``/`` and then, on the parent of ``/``, round forever. The adversarial review
reproduced the hang with ``write_refusal(repo, ".")``. A writer cannot hand that in
through ``--session-id`` -- ``writer_name`` refuses an id that is not one token -- so
the reachable entry is the commit primitive, whose ``name`` argument is whatever a
caller built. A name the guard cannot answer is now refused BY NAME, before anything
is lstat'ed, in words that describe a name rather than a path kind.

The second is an ancestor of the root that is a symlink, with ``--repo`` spelled
through it. That is the layout the quickstart sells and the state-root refusal is
careful not to refuse it, but a walk that climbed with ``while str(path) !=
str(path.parent)`` lstat'ed the root's ancestors anyway -- so the same layout was a
refusal for a writer that reached the sessions directory by the other helper. The walk
is now bounded structurally: it iterates the parts of the name relative to the root,
so there is no upward step to bound and no ancestor can be examined however the root
was spelled.

The timeouts are not decoration. A regression of the first fault is a hang, and a
hanging test is a suite that never reports anything, so each case that could hang runs
either under ``pytest-timeout`` where it is installed or in a subprocess with a hard
``timeout=`` where it is not.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, _git_ok, run_from
from harness_paths import SRC
from session_git_support import STATE_DIR, _nested_state

# A name that is not a session file under the root: the empty name, the root itself,
# and a '..' walk that leaves it. Each used to be a hang or a wrong walk; each must
# now come back as a refusal in bounded time.
NAMES_THAT_ARE_NOT_FILES = (".", "", "noni/../../x.md", "noni/sessions/../../out.md",
                            "/abs/x.md", "../other/noni/sessions/x.md")

# The one write location every case uses, so a name is the only variable.
ROOT = Path("/home/janni/projects/noni/state/st")

# Each writer and the code docs/PRODUCT.md 7 gives it for a wrong path: 2 for
# register, 4 for the others, with the minimum argv to reach the guard.
WRITERS = ((REGISTER, 2, ("--identity", "developer")),
           (CLAIM, 4, ("--session-id", "2026-10-01-cccccc", "--task", "#9")),
           (CLOSE, 4, ("--session-id", "2026-10-01-cccccc")),
           (RELEASE, 4, ("--session-id", "2026-10-01-cccccc", "--task", "#1")))

# A second's worth of margin over what a refusal actually costs (single-digit
# milliseconds), so a test that fails on a hang fails in seconds and not in minutes.
BOUND_SECONDS = 5


def _refusal_in_time(rel: str, repo: Path = ROOT) -> tuple[str, str] | None:
    """The guard's answer for ``rel``, or a failure if it did not answer in time.

    Run in a subprocess rather than in-process: the fault being pinned is a loop that
    does not terminate, and an in-process hang takes the whole worker with it. The
    child prints the refusal on a marker line so the parent can tell "no refusal"
    from "no output yet".
    """
    script = (
        "import sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import _session_paths\n"
        "refused = _session_paths.write_refusal(Path({repo!r}), {rel!r})\n"
        "print('REFUSED::' + refused[0] if refused else 'CLEAN::')\n"
    ).format(src=str(SRC), repo=str(repo), rel=rel)
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True, timeout=BOUND_SECONDS)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"{rel!r}: guard crashed: {proc.stderr}"
    line = proc.stdout.strip()
    assert line.startswith("REFUSED::"), (
        f"{rel!r}: expected a refusal, got {line!r} ({proc.stderr})")
    # The whole subprocess costs well under the bound; a run that reached it would
    # have tripped the timeout above, so this is the assertion that says the walk
    # terminated rather than merely that the child died in time.
    assert elapsed < BOUND_SECONDS, f"{rel!r}: took {elapsed:.1f}s"
    return line[len("REFUSED::"):]


def test_a_name_that_is_not_a_file_under_the_root_is_refused_fast():
    """The hang, and the wording: a name that is not a file inside the root is
    refused by name, quickly, and never in the link's words.
    """
    for rel in NAMES_THAT_ARE_NOT_FILES:
        headline = _refusal_in_time(rel)
        low = headline.lower()
        assert "inside the state root" in low, f"{rel!r}: {headline}"
        # The name is not a link and not a non-directory, so the refusal must not
        # blame either: the sentence describes the NAME it was handed.
        assert "symlink" not in low, f"{rel!r} blamed a symlink: {headline}"
        assert rel in headline, f"{rel!r}: the refusal must name it: {headline}"


def test_a_good_name_under_the_root_is_not_refused():
    """The other half of the name rule: a session file's own name, and the two
    spellings that mean the same file, walk without a refusal.
    """
    from noni import _session_paths

    for rel in ("noni/sessions/2026-10-01-cccccc.md",
                "./noni/sessions/2026-10-01-cccccc.md",
                "noni/./sessions/2026-10-01-cccccc.md"):
        assert _session_paths.write_refusal(ROOT, rel) is None, rel


def test_the_commit_primitive_refuses_a_bad_name_without_hanging(tmp_path):
    """``stage_and_commit`` is the reachable entry: it takes a name and walks it.

    The primitive is driven with the same names the guard is driven with above, on a
    real tree, because the writers all reach the walk through here. A refusal must
    come back as ``(False, why)`` in bounded time and must not touch the tree.
    """
    from noni import _session_git

    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)
    _git_ok(repo, "init", "-q", "-b", "main")
    _git_ok(repo, "config", "user.name", "Replay")
    _git_ok(repo, "config", "user.email", "replay@fixture.invalid")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "commit", "-q", "-m", "seed")
    head_before = _git_ok(repo, "rev-parse", "HEAD").stdout.strip()

    for rel in NAMES_THAT_ARE_NOT_FILES:
        started = time.monotonic()
        ok, why = _session_git.stage_and_commit(repo, rel, "nope")
        elapsed = time.monotonic() - started
        assert ok is False, f"{rel!r}: the primitive committed {rel}"
        assert elapsed < BOUND_SECONDS, f"{rel!r}: took {elapsed:.1f}s"
        assert "inside the state root" in why.lower(), f"{rel!r}: {why}"
        assert "symlink" not in why.lower(), f"{rel!r} blamed a link: {why}"

    assert _git_ok(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _git_ok(repo, "status", "--porcelain").stdout.splitlines() == []


def test_a_state_root_whose_ancestor_is_a_symlink_runs_for_each_verb(tmp_path):
    """The ancestor half, end to end: a project reached *through* a link, with
    ``--repo`` spelled through it, is a normal run for all four writers.

    The old ``_directory_chain`` climbed to ``/`` with no regard for the root, so
    this layout was a refusal for the writers even though the state-root refusal
    deliberately allows it and docs/PRODUCT.md 7 says so in its own words. The
    assertion is not just "exit 0": the run must commit, and never say the word
    symlink.
    """
    for index, (script, code, extra) in enumerate(WRITERS):
        case = tmp_path / f"ancestor-{index}"
        case.mkdir()
        label = script.stem
        project, state, _session = _nested_state(case, "2026-10-01-cccccc",
                                                 name=f"project-{index}")
        through = case / f"project-link-{index}"
        through.symlink_to(project)

        proc = run_from(through, script, "--repo", STATE_DIR, *extra)

        assert proc.returncode == 0, (
            f"{label}: a state root reached through a linked ancestor must run, got "
            f"exit {proc.returncode} (its own code {code} means a wrong path): "
            f"{proc.stderr}")
        assert "symlink" not in (proc.stdout + proc.stderr).lower(), (
            f"{label}: {proc.stderr}")
        # The commit is the one session file, and only that one. register mints its
        # own id, so the name is asserted by shape rather than by value.
        committed = _git_ok(state, "diff", "--name-only", "HEAD~1", "HEAD").stdout
        assert len(committed.split()) == 1, f"{label}: {committed}"
        assert committed.startswith("noni/sessions/"), f"{label}: {committed}"


def test_the_walk_never_lstats_an_ancestor_of_the_state_root(tmp_path):
    """The bound, asserted at the syscall rather than by behaviour.

    A parent of the root that no reader may stat is the sharpest probe available: if
    the walk climbs one level past the root, it sees that refusal and the whole run
    changes its answer. With the walk bounded at the root, the guard never asks and
    the write proceeds. (Skipped where the user can stat anything, which is root.)
    """
    import os

    from noni import _session_paths

    root = tmp_path / "hidden" / "st"
    (root / "noni" / "sessions").mkdir(parents=True)
    (root / "noni" / "sessions" / "s.md").write_text("- status: active\n",
                                                     encoding="utf-8")
    hidden = root.parent
    hidden.chmod(0o000)
    try:
        os.lstat(hidden)
    except OSError:
        pass
    else:
        hidden.chmod(0o755)
        import pytest
        pytest.skip("the reading user can stat a 000-mode directory")
    try:
        assert _session_paths.write_refusal(root, "noni/sessions/s.md") is None, (
            "the walk examined an ancestor of the state root")
        assert _session_paths.session_file_refusal(
            root, "noni/sessions/s.md") is None
    finally:
        hidden.chmod(0o755)
