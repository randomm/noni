"""The quickstart's Route B, run on a repository whose branch is not ``main``.

Split out of ``tests/test_quickstart.py`` on the seam the pilot's own failure made
(the 500-line cap in ``tests/test_file_size_limit.py`` is the reason it is a file
and not another block there): every other Route B walk in the suite runs against an
origin seeded on ``main``, which is the case where a literal branch name and the
token ``HEAD`` behave identically and no assertion can tell them apart.

That is the whole of this module's reason to exist. A second pilot team created its
private state repository from a fresh ``git init`` whose default branch was not
``main``, typed the page's first push -- ``git -C .noni-state push -u origin main``
-- and pushed a branch that did not exist there. The page now prints ``HEAD``, which
is right for any branch, and the only way to check that a page change kept the
generality is to run the route on a branch the page never names. The rest of the
suite cannot do it: the fixture's branch name and the page's assumption agree
everywhere else, so the regression is invisible there by construction.

The commands are the harness's golden ones throughout --
:func:`quickstart_runner.run_route_b` walks the page's own fences after comparing
them to :mod:`quickstart_golden`, so what is exercised here is the line the page
prints, on the branch the fixture drifted to, and not a paraphrase of either.
"""

from __future__ import annotations

from pathlib import Path

from docs_promises import FIRST_PUSH_COMMAND
from quickstart_runner import checked, git, route_commands, run_route_b
from quickstart_topology import InstalledWorld, fresh_scratch

# The branch the drifted Route B walk creates its trees on: a name the page never
# prints, so the push line has to derive it rather than assume it.
OTHER_BRANCH = "trunk"


def test_the_first_push_of_a_non_main_default_branch_lands_and_tracks(
    installed: InstalledWorld, tmp_path: Path,
) -> None:
    """Route B on a forge repository whose branch is not ``main``: the page still works.

    The walk builds the same topology the main-branch tests use, on a branch the
    page never names, runs every Route B command, and reads back the two things the
    page promises: the whole walk exits 0 (``run_route_b`` checks every exit code),
    and the clone reports an upstream on the branch it was actually created on. The
    branch check sits *after* the walk because the clone is itself one of the page's
    lines -- asserting the drifted branch reached it is a read of what the page's
    ``git clone`` produced, not a fixture precondition the harness arranged.

    A page that reverted to a literal branch name is caught twice over: the golden
    comparison inside :func:`route_commands` refuses the changed line, and the
    upstream the clone reports is then ``main`` rather than the drifted branch.
    """
    world = fresh_scratch(installed, tmp_path / "drift", branch=OTHER_BRANCH)
    assert world.branch == OTHER_BRANCH, (
        "the fixture did not record the branch it built on, so the assertions below "
        "would read a name the trees were never created with")
    run_route_b(world)

    checked(git(world.state, "rev-parse", "--verify", "HEAD", env=world.env),
            "the clone names a branch")
    head = git(world.state, "symbolic-ref", "--short", "HEAD", env=world.env)
    _checked(head, "the state clone's branch")
    assert head.stdout.strip() == OTHER_BRANCH, (
        f"the fixture's drifted branch did not reach the clone, so the push line "
        f"is being tested on {head.stdout.strip()!r} and proves nothing: "
        f"{head.stderr!r}")

    upstream = git(world.state, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                   "@{u}", env=world.env)
    _checked(upstream, "the upstream of the drifted state branch")
    assert upstream.stdout.strip() == f"origin/{OTHER_BRANCH}", (
        f"the page's first push did not track origin/{OTHER_BRANCH}, so a reader "
        f"whose repository was not seeded with main is left with a branch that has "
        f"no remote to push to: {upstream.stdout!r} {upstream.stderr!r}")
    on_origin = git(world.origin, "rev-parse", "--verify", OTHER_BRANCH, env=world.env)
    _checked(on_origin, "the drifted branch on the origin")
    pushes = [a for a in route_commands(("Route B",))
              if " ".join(a) == FIRST_PUSH_COMMAND]
    assert pushes, (
        f"the page's first push is no longer {FIRST_PUSH_COMMAND!r}, so a reader "
        f"whose branch is {OTHER_BRANCH!r} is told to push a branch that does not "
        "exist")


# The must-succeed wrapper, under the short name the assertions above use (the same
# alias ``tests/test_quickstart.py`` gives it, so a red run names the step either
# way and the two modules read alike).
_checked = checked
