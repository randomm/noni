"""The brief suite, part 6 of 6: the other entry points and the paths in.

The console route prints the page and returns the tool's code, and the path a caller
hands ``--repo`` is read at that path: relative, trailing slash, dotted, or a state root
inside a larger repository.
"""


from __future__ import annotations

import os
from pathlib import Path

import pytest
from _harness import REPO
from brief_fixtures import (
    NOW,
    PURPOSE_LINES,
    intent_path,
    plant_brief_tree,
    run_brief,
    run_brief_from,
    run_brief_in_process,
)
from brief_support import (
    is_refusal,
    sections,
    stripped,
)
from harness_runners import run_noni

from noni import brief as brief_module


def test_brief_the_console_route_prints_the_same_page(tmp_path: Path) -> None:
    """``noni brief`` and the in-process call are byte-identical.

    The console dispatch hands its argv over verbatim and returns the tool's code unchanged, so the
    two routes differ only if that layer rewrote one of them. The launched run is the one the
    operator has; the in-process run is the one the seam cases use, and this is where the two are
    held to each other.
    """
    root = plant_brief_tree(tmp_path)
    inprocess = run_brief_in_process(root, "--now", NOW)
    launched = run_noni("brief", "--repo", str(root), "--now", NOW)
    assert launched.returncode == inprocess[0] == 0
    assert launched.stdout == inprocess[1]
    assert launched.stderr == ""


def test_brief_the_console_route_returns_the_tools_exit_code(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    launched = run_noni("brief", "--repo", str(root / "nope"))
    assert launched.returncode == 2
    assert launched.stdout == ""
    assert is_refusal(launched.stderr)


@pytest.mark.parametrize("argv", [
    ["--repo", "x", "--skip", "hygiene"],
    ["--repo=x", "--now", "not-a-timestamp"],
    ["--now", NOW],
])
def test_brief_a_launched_usage_error_exits_two(argv: list[str], tmp_path: Path) -> None:
    """The same refusals through the launched route, where the exit status is a real one.

    The in-process cases read the code behind argparse's ``SystemExit``; this is what a shell, a
    skill or a driver actually sees.
    """
    root = plant_brief_tree(tmp_path)
    launched = run_noni("brief",
                        *[part if part != "x" else str(root) for part in argv],
                        cwd=tmp_path)
    assert launched.returncode == 2
    assert launched.stdout == ""
    assert is_refusal(launched.stderr)


def test_brief_is_listed_in_the_tool_index(tmp_path: Path) -> None:
    """The index of ``noni --help`` names the tool, and its own help names both flags."""
    from noni import cli

    assert cli.TOOLS["brief"] == ("noni.brief", "main")
    assert "brief" in cli.SUMMARIES
    # Both launched through the harness launcher, which pins COLUMNS: argparse wraps its usage and
    # its option help to the terminal width, so a bare launch under a caller's own width is a
    # different question from the one this case asks.
    index = run_noni("--help")
    assert index.returncode == 0
    assert "brief" in index.stdout
    # argparse's ``--help`` path raises SystemExit(0) before the tool can refuse anything, and the
    # console dispatch returns the tool's code unchanged, so a help page exiting 2 would be the
    # brief's refusal code leaking onto an answer. Both codes are load-bearing.
    help_text = run_noni("brief", "--help", cwd=tmp_path)
    assert help_text.returncode == 0
    assert help_text.stdout.startswith("usage:")
    assert "--repo" in help_text.stdout and "--now" in help_text.stdout
    assert help_text.stderr == ""


def test_brief_a_relative_repo_prints_the_same_page(tmp_path: Path) -> None:
    """The cwd of the run is not an input to anything the page says.

    ``--repo`` is resolved once, before the first read, and the same resolved directory is what the
    census is handed, so a relative path and a run from elsewhere cannot make the two halves of one
    page audit different trees.
    """
    root = plant_brief_tree(tmp_path, name="repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    absolute = run_brief(root, "--now", NOW)
    relative = run_brief_from(elsewhere, Path(os.path.relpath(root, elsewhere)), "--now", NOW)
    assert absolute[0] == relative[0] == 0
    assert absolute[1] == relative[1]


def test_brief_a_trailing_slash_and_a_dotted_path_are_one_page(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    assert run_brief(Path(str(root) + "/"), "--now", NOW)[1] == \
        run_brief(root / ".." / root.name, "--now", NOW)[1]


def test_brief_the_repo_is_read_at_the_path_it_was_given(tmp_path: Path) -> None:
    """A page is about the tree named, never about the tree the process happens to sit in.

    The state root and the cwd hold different content; the page names the state root's, which is the
    assertion that no cwd default was smuggled in behind the resolution. The cwd's own purpose line
    is planted beside its item so the case asks one question of both artifacts the page does read.
    """
    root = plant_brief_tree(tmp_path, name="state-root")
    elsewhere = tmp_path / "cwd-tree"
    (elsewhere / "noni" / "items").mkdir(parents=True)
    from noni import itemschema

    (elsewhere / "noni/items/idea-0001.json").write_bytes(itemschema.item_bytes(
        itemschema.entry("idea-0001", "Belongs to the other tree",
                         itemschema.STATUS_CANDIDATE, "2027-01-01T00:00:00Z")))
    out = run_brief_from(elsewhere, root, "--now", NOW)[1]
    assert "Belongs to the other tree" not in out
    assert len(stripped(sections(out), brief_module.ORDER_HEADER)) == \
        brief_module.TOP_ENTRIES


def test_brief_reads_no_census_state_from_the_previous_run(tmp_path: Path) -> None:
    """Two trees briefed one after the other in one process each get their own page.

    The census records the tree it is auditing for the life of the run, and the brief runs it in
    process. The launched route the suite uses cannot show what that means, so this case drives the
    two runs it needs directly: a brief whose second page came from the first tree is the failure
    the launched route exists to avoid, and the case pins that the tool itself is not the thing
    carrying state between runs. The two trees differ in their standing intent, which is the
    artifact the page does read.
    """
    first = plant_brief_tree(tmp_path, name="first")
    second = plant_brief_tree(tmp_path, name="second")
    from brief_fixtures import write_order_entries
    from noni import orderschema

    write_order_entries(second, [
        orderschema.entry(issue=77, decision="2026-10-01-brief",
                          confirmed="2026-10-26T00:00:00Z")])
    run_brief_in_process(first, "--now", NOW)
    out = run_brief_in_process(second, "--now", NOW)[1]
    assert "1. #77" in out
    assert "1. #1" not in out


def test_brief_is_a_sibling_module_of_the_tool_and_read_by_it(tmp_path: Path) -> None:
    """The reader the tool split out for the size cap is the tool's own read.

    The seam the split made is only honest if the tool still asks it: a block that grew
    its own copy of a read would make the split a place for a second answer to live, which is the
    thing the split was meant to prevent.
    """
    from noni import brief_intent

    assert brief_intent.purpose_block.__module__ == "noni.brief_intent"
    root = plant_brief_tree(tmp_path)
    assert brief_intent.purpose_body(intent_path(root)) is not None
    assert run_brief(root, "--now", NOW)[1].splitlines()[1] == PURPOSE_LINES[0]


def test_brief_source_stays_within_the_size_cap() -> None:
    """The split was made for ``tests/test_file_size_limit.py``; it has to have worked."""
    for name in ("brief.py", "brief_intent.py", "brief_page.py"):
        source = (REPO / "src" / "noni" / name).read_text(encoding="utf-8")
        assert len(source.splitlines()) < 500, name
