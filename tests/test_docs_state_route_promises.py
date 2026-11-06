"""What the docs promise about the private state repository, checked as text.

Split out of ``tests/test_docs_promises.py`` at the seam the pilot's Route B run
opened (the 500-line cap in ``tests/test_file_size_limit.py`` is why this is a file
and not another block there): the three claims here are all about one tree -- the
separate private state repository of ``docs/QUICKSTART.md`` Route B and
``docs/PRODUCT.md`` §7 -- and each was a gap a pilot team fell into rather than a
claim this suite had to imagine.

- **The repository holds the ``noni/`` layout and nothing else.** The census's
  hygiene class reads every tracked file of the tree ``--repo`` names, so a state
  repository seeded with other work reports that work as direction. The pilot's
  first team pointed ``--repo`` at a clone of an existing private repository and
  got a census full of findings about files nobody meant as direction.
- **Route B writes the deny-list into the state clone and never commits it.** The
  file lives beside the layout and must stay untracked, which is the one thing the
  page cannot get from the project's own ``.gitignore``.
- **Route B's first push names ``HEAD``, not a branch.** The pilot's second team
  created its state repository on a default branch that was not ``main``, and the
  page's literal ``push -u origin main`` pushed a branch that did not exist. That
  push is also *walked* end to end on a non-``main`` branch by
  ``tests/test_quickstart_branch_drift.py``; what is checked here is that the page
  still prints the line that walk depends on, and explains it.

Each check reads the pages as data and the constants from :mod:`docs_promises`, and
the printed commands are the harness's own golden Route B list, so a page that
reworded a command fails the harness's comparison and not merely a keyword search.
"""

from __future__ import annotations

from pathlib import Path

from docs_commands import read
from docs_promises import (
    FIRST_PUSH_COMMAND,
    PRODUCT,
    QUICKSTART,
    STATE_REPO_LAYOUT_ONLY,
    section_body,
)
from quickstart_page import flowed_text as flowed
from quickstart_runner import (
    denylist_file,
    fresh_scratch,
    git,
    route_commands,
    run_route_b,
)
from quickstart_topology import InstalledWorld

from noni import public_safety

# The deny-list file's name, taken from the product rather than typed here, so a
# rename in ``src/noni/public_safety.py`` moves these assertions to the new name
# instead of leaving a page that describes a file nothing reads.
DENYLIST_NAME = public_safety.DENYLIST_FILENAME
# The example entry the page's Route B fence writes; the harness keeps its own copy
# of the same name in ``quickstart_page_steps``.
DENYLIST_ENTRY = "example-corp"


def test_the_state_repository_holds_only_the_noni_layout() -> None:
    """Both pages that offer the private state repository say what may live in it.

    The census's hygiene class reads every tracked file of the tree ``--repo``
    names (``docs/PRODUCT.md`` §7 says so, and ``src/noni/census_hygiene.py``
    enforces it), so a state repository that also carries source, build output or
    someone's notes reports all of it as direction. The pilot's first team pointed
    ``--repo`` at a clone of an existing private repository and got a census full
    of findings about files nobody had meant as direction; the page offered the
    route without its precondition.

    Located, not keyword-scanned: the rule has to be in §7 of the product document
    and in Route B's own section of the quickstart, since those are the two places
    the choice is on the table. A word that happens to appear elsewhere in either
    file does not carry the promise.
    """
    section = section_body(read(PRODUCT), "7.")
    assert section, "docs/PRODUCT.md no longer has a section 7 to carry the rule"
    assert all(phrase in flowed(section) for phrase in STATE_REPO_LAYOUT_ONLY), (
        "docs/PRODUCT.md §7 no longer states the state-repository rule; it omits "
        f"{[p for p in STATE_REPO_LAYOUT_ONLY if p not in flowed(section)]}")
    route_b = flowed(read(QUICKSTART).split("## Route B")[1])
    assert all(phrase in route_b for phrase in STATE_REPO_LAYOUT_ONLY), (
        "docs/QUICKSTART.md Route B no longer states the state-repository rule; it "
        f"omits {[p for p in STATE_REPO_LAYOUT_ONLY if p not in route_b]}")


def test_route_b_writes_the_deny_list_into_the_state_clone_and_never_commits_it(
    installed: InstalledWorld, tmp_path: Path,
) -> None:
    """Route B's walk leaves an active deny-list at the clone's root, untracked.

    The harness's own Route B walk used to write the file to the *project* folder
    and still exit 0, because the census passes without a deny-list when no secret
    patterns match: a reader who followed that line literally got a hygiene class
    that silently did nothing on a repository that does hold a secret. So the
    placement is product surface, and it is read off the disk the walk wrote rather
    than off the page's prose -- three things at once, each invisible to an
    exit-code check: the file sits at the root of the tree ``--repo`` names (the
    clone, not the project around it), the product's own ``load_denylist`` counts
    what the page's line wrote as an active class holding an entry (a file of
    comments alone is ``present but empty``), and the clone's git does not see the
    file at all.

    The commands themselves are pinned by the harness's golden comparison inside
    :func:`run_route_b`, so a page that moved the write or dropped the ignore line
    fails there; the assertions below are what the walk leaves behind.
    """
    world = fresh_scratch(installed, tmp_path / "state-route")
    run_route_b(world)
    denylist = denylist_file(world)
    assert denylist.is_file(), (
        f"Route B's walk left no deny-list at {denylist}, the root of the tree "
        "--repo names: the hygiene class would report the class absent")
    # The product's own reader decides whether the file the page writes is active;
    # the harness's idea of a usable entry would be a second opinion, not a check.
    result = public_safety.load_denylist(world.state)
    assert DENYLIST_ENTRY in result.entries, (
        f"the deny-list the page's line writes is read by the product as "
        f"{result.status!r} holding {result.entries}, not the active class with the "
        f"page's example {DENYLIST_ENTRY!r}: {denylist.read_text()!r}")
    # The untracked promise, read the way git answers it: ``check-ignore`` says
    # whether the clone's own ``.gitignore`` holds the file, and a tracked deny-list
    # -- the leak the file exists to prevent -- is the other answer it must not give.
    tracked = git(world.state, "ls-files", DENYLIST_NAME, env=world.env)
    assert tracked.returncode == 0, f"git ls-files on the clone failed: {tracked.stderr!r}"
    assert not tracked.stdout.strip(), (
        f"the state clone tracks {DENYLIST_NAME!r}, so the names the scan looks for "
        "are in the repository's history")
    ignored = git(world.state, "check-ignore", "-q", DENYLIST_NAME, env=world.env)
    assert ignored.returncode == 0, (
        f"the clone's .gitignore does not hide {DENYLIST_NAME!r} "
        f"(git check-ignore exited {ignored.returncode}), so the next commit adds a "
        "file the census only ever reads")


def test_route_b_pushes_head_rather_than_a_branch_the_page_cannot_know() -> None:
    """The one-time push names the clone's own branch, and says why.

    The pilot's second team ran Route B on a fresh state repository whose default
    branch was not ``main``, and the page's ``push -u origin main`` named a branch
    that did not exist there: a fresh ``git init`` owes nobody a branch name, and
    the page cannot know which one the reader has. ``HEAD`` is the token that means
    "whichever branch this clone is on".

    This is the static half of the promise; ``tests/test_quickstart.py`` *walks*
    the same push on a branch other than ``main`` and reads the upstream back off
    the clone, which is where a page that reverted to a literal branch name would
    otherwise pass on exit code alone. The sentence naming ``HEAD`` is required
    beside the command because the command's correctness is not self-evident: a
    reader who does not know why it says ``HEAD`` will "fix" it to their branch.
    """
    commands = [cmd for cmd in route_commands(("Route B",))
              if " ".join(cmd) == FIRST_PUSH_COMMAND]
    assert commands, (
        f"Route B no longer prints {FIRST_PUSH_COMMAND!r}: the push would name a "
        "branch the page cannot know the reader has")
    route_b = flowed(read(QUICKSTART).split("## Route B")[1])
    assert "main" in route_b and "branch" in route_b, (
        "Route B prints the push without stating that a fresh repository need not "
        "default to the branch most forges seed, which is the assumption that broke")


