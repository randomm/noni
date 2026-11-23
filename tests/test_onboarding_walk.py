"""The onboarding page's protocol, driven through the installed console command.

``tests/test_onboarding.py`` reads ``docs/ONBOARDING.md`` as text; this module runs
what the page tells an agent to do. The split is the page's own design: it prints no
commands, so the text checks and the executed walk can only be read against each
other from the outside -- the walk asserts the writers belong to skills the page
links, and the text module asserts the page still links them.

The walk is the honest half of AC7: the page sells a sequence of steps, and the
claim that survives "the page prints nothing" is that the steps are executable and
take an attached project from no state to an intent, an order, a recorded steer and
a clean census. It runs in the world the quickstart's own walks use, through the
installed console script, so what is observed is a reader's experience and not the
wrapper's argparse.

One step the walk used to skip is the page's own ``git clone`` of the private state
repository, and skipping it was a bug of issue #220's exact shape: ``.noni-state``
arrived as a plain directory inside the project, so the identity write that follows
was a ``git config`` on a non-repository -- the call that leaked the fixture
identity into this checkout's shared config. See the comment where the clone runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from docs_promises import STATE_DIR
from quickstart_topology import git as quickstart_git
from test_onboarding import page_text, step_link_for


def _run(world, *argv: str):
    """One ``noni`` subcommand through the installed console script.

    Launched by path under the world's own env and cwd, which is the shape the page
    describes: the reader's project as the working directory, the venv's console
    script as the program, and nothing of the harness's own environment in between.
    """
    return subprocess.run([str(world.noni), *argv], capture_output=True,
                          text=True, env=world.env, cwd=str(world.project),
                          timeout=180)


def _record_id_from(stdout: str) -> str:
    """The record id the decide writer printed, read off its own line.

    The writer's headline names the file it wrote; the id is read from it rather
    than from the file list so that the assertion in the caller -- the two direction
    files cite a record the ledger holds -- means the id this run actually made.
    """
    match = re.search(r"(\d{4}-\d{2}-\d{2}-[a-z0-9-]+)\.json", stdout)
    assert match, f"the decide line printed no record path in its headline: {stdout!r}"
    return match.group(1)

def test_the_protocol_steps_run_in_order_through_the_console_command(
    world, tmp_path: Path,
) -> None:
    """The writers of the page's three steps each exit 0 in the page's own order.

    AC7's honest reading: the page prints no commands, so the claim that survives is
    that the steps it tells an agent to take are executable and take an attached
    project from no state to an intent, an order and a recorded steer. The page
    links the skills rather than printing flags, so the harness supplies the flags --
    launched through the installed ``noni`` console script, in the world the
    quickstart's own walks use (project, private state clone, origin), so what is
    observed is the reader's experience rather than the wrapper's argparse.

    The census runs at the end, on the page's own advice, over exactly the state
    those three writers left: a tree that followed the protocol must census clean.
    """
    state, env = world.state, world.env
    # ``.noni-state`` is a repository because the page clones it, and this walk drives
    # the three writers and the census without ever running that clone -- so the state
    # tree arrived as a plain directory inside the project, and a ``git config`` on such
    # a directory is answered by the repository that encloses it (issue #220: that is
    # the leak, reproduced here by the fixture itself). Running the page's clone for
    # real, against the fixture's own bare origin, is both the step the page prints and
    # the precondition every writer below relies on. The harness's own git helper runs
    # it, so the clone is created under the same containment precondition the identity
    # lines are checked against a moment later.
    if not (state / ".git").exists():
        from quickstart_topology import git as topology_git

        cloned = topology_git(world.project, "clone", "-q", str(world.origin),
                              STATE_DIR, env=env)
        assert cloned.returncode == 0, (
            f"the page's state clone failed: {cloned.stdout}\n{cloned.stderr}")
    assert (state / ".git").exists(), (
        f"the fixture's state clone has no .git of its own at {state}, so a git call "
        "on it would be answered by the project that encloses it")
    # The identity the page's Route A block sets, written through the harness helper
    # that enforces the containment precondition rather than this module's unguarded
    # shape: a config write into the clone must be checked, because a clone that was
    # never created is exactly the plain directory whose config write lands upstairs.
    for key, value in (("user.name", "Replay"),
                       ("user.email", "replay@fixture.invalid")):
        proc = quickstart_git(state, "config", key, value, env=env)
        assert proc.returncode == 0, f"state identity {key}: {proc.stderr}"

    # The steer the two direction files cite. It is written first because the page
    # says so: the intent and the order name a record the ledger must already hold.
    # ``--init`` because the fixture's state clone is new, which is exactly the state
    # the flag exists to name.
    decide = _run(world, "decide", "--repo", str(state), "--init",
                  "--slug", "walk",
                  "--scope", "release ordering", "--asked-by", "developer",
                  "--question", "q1=Ship the beta this week?", "--option",
                  "q1=Ship it", "--option", "q1=Wait a week",
                  "--answer", "q1=Wait a week")
    assert decide.returncode == 0, f"decide: {decide.stderr}"
    record_id = _record_id_from(decide.stdout)

    intent_draft = tmp_path / "intent-draft.md"
    intent_draft.write_text(_INTENT_DRAFT, encoding="utf-8")
    intent = _run(world, "intent", "--repo", str(state), "set",
                  "--from", str(intent_draft), "--decision", record_id)
    assert intent.returncode == 0, f"intent: {intent.stderr}"
    assert (state / "noni" / "direction" / "intent.md").is_file(), (
        "the intent step wrote no standing intent file")

    order = _run(world, "order", "--repo", str(state), "add", "12",
                 "--decision", record_id)
    assert order.returncode == 0, f"order: {order.stderr}"
    assert (state / "noni" / "direction" / "order.json").is_file(), (
        "the order step wrote no ordering artifact")

    census = _run(world, "census", "--repo", str(state))
    assert census.returncode == 0, f"census: {census.stderr}\n{census.stdout}"
    assert census.stdout.splitlines()[-1].endswith("verdict ok"), (
        f"a session that followed the protocol did not census clean: "
        f"{census.stdout.splitlines()[-1:]!r}")


def test_the_page_links_the_skills_whose_writers_this_walk_runs() -> None:
    """The writers the walk drives belong to skills the page links.

    The walk is the evidence behind the page's protocol table; if it drifted to
    driving a skill the page never named, the two halves of this module would be
    testing different pages. The verbs below are the protocol's steps, and each is
    dispatched by the console command to a module of one skill.
    """
    page = page_text()
    for skill in ("steering-ledger", "direction", "census"):
        assert step_link_for(skill) in page, (
            f"the walk drives {skill}'s writers and the page does not link it")


# --- helpers used only by this module ---------------------------------------

# The standing intent the walk installs, in the shape the direction skill's own
# template validates: the four headings in order and one confirmation line, which
# the writer restamps with its own date.
_INTENT_DRAFT = """Last-confirmed: 2026-10-01

## Purpose

Ship the beta and keep the direction readable.

## Principles

Plain files and one arbiter.

## Never

Never answer for the operator.

## Ask first

Anything that changes the release scope.
"""
