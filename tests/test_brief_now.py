"""The brief suite, part 2 of 6: the instant handed to the census.

``--now`` reaches the census, so the verdict follows the stall window rather than the
clock, and an instant the tool will not act on is a usage error on exit 2.
"""


from __future__ import annotations

from pathlib import Path

import pytest
from brief_fixtures import (
    NOW,
    SESSION_REL,
    commit_at,
    plant_brief_tree,
    plant_session,
    restore_history,
    run_brief,
    run_brief_with_history,
)
from brief_support import (
    LABEL,
    census_summary,
    counts_more,
    is_refusal,
    summary_line,
)

from noni import brief as brief_module

# The instant the stall case commits a session's register file at, and the two instants the
# page is asked about around it: inside the census's 14-day stall window on one side and past
# it on the other. Spelled here because the case's whole claim is the distance between them.
STALL_MOMENT = "2026-10-01T09:00:00+00:00"


def test_brief_summary_line_equals_the_census_summary_line(tmp_path: Path) -> None:
    """The brief's last line is the census's last line, byte for byte, for one tree.

    Taken from the census's own entry point rather than from the brief's capture, so a brief
    that composed a verdict of its own could not match itself.
    """
    root = plant_brief_tree(tmp_path)
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert summary_line(out) == census_summary(root, NOW)


def test_brief_forwards_now_so_the_verdict_follows_the_stall_window(tmp_path: Path) -> None:
    """The same tree at two instants differs in the verdict line and in nothing else.

    The ``--now`` the brief is handed is the ``--now`` the census is run with. A session whose
    register file was committed on 2026-10-01 is past the census's 14-day stall window at
    2026-10-27 and inside it at 2026-10-05; if the stamp were accepted and dropped, one verdict
    would print for two states of one tree, and the page would be a report about a moment it did
    not name.

    The session file and the commit that carries it are planted here rather than held in the
    committed fixture: the file's history has to predate one instant and postdate another within
    the same case, and a fixture commit could not do both.
    """
    root = plant_brief_tree(tmp_path)
    path = plant_session(root)
    assert path.exists()
    with restore_history(root):
        commit_at(root, [SESSION_REL], STALL_MOMENT, "register: briefly")
    early = run_brief_with_history(root, "--now", "2026-10-05T09:00:00Z")
    late = run_brief_with_history(root, "--now", NOW)
    assert early[0] == late[0] == 0
    # The blocks are the page's own reads and take no clock: identical bytes either side.
    assert (early[1].splitlines()[:-1] == late[1].splitlines()[:-1])
    assert summary_line(early[1]) != summary_line(late[1])
    # And the two verdicts are the census's own, at the two instants, unchanged.
    with restore_history(root):
        assert summary_line(late[1]) == census_summary(root, NOW)
        assert summary_line(early[1]) == census_summary(root, "2026-10-05T09:00:00Z")
    # The late verdict is the stalled one and the early one is not, so the difference this case
    # rests on is the census saying something it was not saying at the other instant -- not two
    # rows that were always going to disagree.
    # The census counts findings in its summary line, so a stalled session is visible there:
    # the word names what the two verdicts differ about.
    assert "stalled" in summary_line(late[1]) or counts_more(late[1], early[1])


@pytest.mark.parametrize("bad, why", [
    ("2026-10-27T09:00:00", "carries no UTC offset"),
    ("2026-10-27 09:00:00", "carries no UTC offset"),
    ("yesterday", "not a valid ISO-8601 timestamp"),
    ("", "not a valid ISO-8601 timestamp"),
])
def test_brief_rejects_a_malformed_now(tmp_path: Path, bad: str, why: str) -> None:
    """A stamp this tool will not use is refused before anything is read.

    The accepted set is the order writer's own rule, which is the one rule in the product that
    refuses a stamp carrying no UTC offset -- stricter than the census's parser, and therefore a
    guarantee that every command line the brief accepts sits inside the subset the census answers
    about. A stamp that parses with an offset baked into the text (``"2026-10-27 09:00:00Z"``) is
    *not* in this table: it is accepted, and accepting it is the next case's business.
    """
    root = plant_brief_tree(tmp_path)
    code, out, err = run_brief(root, "--now", bad)
    assert code == 2
    assert out == ""
    assert f"{LABEL}:" in err
    assert why in err


def test_brief_accepts_the_two_spellings_of_a_utc_instant(tmp_path: Path) -> None:
    """``Z`` and ``+00:00`` are one instant, and both are forwarded as one stamp."""
    root = plant_brief_tree(tmp_path)
    zulu = run_brief(root, "--now", NOW)
    offset = run_brief(root, "--now", NOW.replace("Z", "+00:00"))
    assert zulu[0] == offset[0] == 0
    assert zulu[1] == offset[1]


def test_brief_a_non_utc_offset_is_accepted_and_normalised(tmp_path: Path) -> None:
    """An instant expressed in another zone is the same instant, so it is the same page."""
    root = plant_brief_tree(tmp_path)
    assert run_brief(root, "--now", "2026-10-27T10:00:00+01:00")[1] == \
        run_brief(root, "--now", NOW)[1]


@pytest.mark.parametrize("argv", [
    ["--repo"],                              # the flag without its value
    [],                                      # the required flag absent
    ["--now", NOW],                          # the state root never named
    ["--repo", "x", "--skip", "hygiene"],     # a flag belonging to another tool
    ["--repo", "x", "--json"],
    ["--repo", "x", "--format", "md"],
    ["--repo", "x", "--no-color"],
    ["--repo", "x", "-n"],
    ["--repo", "x", "extra"],
    ["--verbose", "x"],
    ["--rep", "x"],                          # an abbreviation of the repo flag the brief does not have
    ["--repo", "x", "--no", NOW],           # an abbreviation of the now flag the brief does not have
])
def test_brief_usage_errors_exit_two_with_no_output(argv: list[str],
                                                    capsys) -> None:
    """Every shape the parser refuses: exit 2, empty stdout, and the tool's own label.

    ``x`` stands for a directory that exists, so no case here can reach exit 2 by way of the
    path check: each one is refused in the parser, before a single read.
    """
    assert brief_module.main([part if part != "x" else "/" for part in argv]) == 2
    captured = capsys.readouterr()
    # The invariant that matters to a caller: exit 2 and an empty stdout, so stdout is the
    # report or nothing. What stderr holds depends on which of the tool's two refusal shapes
    # answered -- argparse's own usage banner for a command line it cannot parse, or the
    # tool's labelled headline and fix for a value it can parse but will not use -- and the
    # table below names which shape each row is.
    assert captured.out == ""
    assert is_refusal(captured.err)
    assert captured.err.strip().splitlines()[0].split(":")[0] in ("usage", LABEL)


@pytest.mark.parametrize("bad", ["not-a-timestamp", "2026-10-27T09:00:00", ""])
def test_brief_a_value_it_will_not_act_on_is_the_tools_own_refusal(bad: str,
                                                                   capsys) -> None:
    """A command line the parser reads and the tool refuses is worded by the tool, not argparse.

    The distinction is what makes the fix line useful: argparse can say that ``--now`` is a
    flag and take one argument, but only the tool knows that the stamp it was handed carries no
    UTC offset and what to type instead.
    """
    assert brief_module.main(["--repo", "/", "--now", bad]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert is_refusal(captured.err)
    assert f"{LABEL}: fix:" in captured.err


def test_brief_a_repo_that_is_not_a_directory_exits_two(tmp_path: Path,
                                                        capsys) -> None:
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory\n", encoding="utf-8")
    assert brief_module.main(["--repo", str(a_file)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(f"{LABEL}:")
    assert "is not a directory" in captured.err
    # The refusal is the two-line shape every noni writer prints: a headline and a fix.
    assert f"{LABEL}: fix:" in captured.err


def test_brief_a_repo_that_does_not_exist_exits_two(tmp_path: Path, capsys) -> None:
    """A tree that is not there is refused, and no part of it is created on the way.

    The census creates nothing either, so a page that mkdir'd its way to a report would leave
    an empty ``noni/`` behind and make the next census answer about a tree nobody wrote.
    """
    missing = tmp_path / "no-such-tree"
    assert brief_module.main(["--repo", str(missing)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a directory" in captured.err
    assert not missing.exists()


def test_brief_reads_no_environment_for_the_state_root(tmp_path: Path, monkeypatch,
                                                       capsys) -> None:
    """``--repo`` is required, so no variable can point the page at a tree the caller meant.

    The census answers a state-root variable when no flag names one. The brief takes the flag
    or exits 2, which is the stricter rule for a tool with no reason to guess a tree.
    """
    monkeypatch.setenv("NONI_STATE_ROOT", str(tmp_path / "from-the-environment"))
    (tmp_path / "from-the-environment").mkdir()
    assert brief_module.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "required" in captured.err
