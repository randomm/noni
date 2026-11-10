"""The brief suite, part 5 of 6: the tree is left exactly as it was.

Nothing under the state root changes, in the working tree or in its history, and no
state root is created where none existed.
"""


from __future__ import annotations

import shutil
from pathlib import Path

from _harness import _git
from brief_fixtures import (
    NOT_READ,
    NOW,
    intent_path,
    order_path,
    plant_brief_tree,
    porcelain,
    porcelain_of,
    restore_history,
    run_brief,
    tree_paths,
)
from brief_support import (
    HEADERS,
    sections,
    summary_line,
)

from noni import brief as brief_module


def test_brief_leaves_the_tree_and_its_git_status_untouched(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    with restore_history(root):
        before_status = porcelain(root)
        before_paths = tree_paths(root)
        code, _out, _err = run_brief(root, "--now", NOW)
        assert code == 0
        assert porcelain(root) == before_status
        assert tree_paths(root) == before_paths


def test_brief_creates_no_state_root_where_none_existed(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    assert run_brief(root, "--now", NOW)[0] == 0
    assert tree_paths(root) == set()


def test_brief_does_not_rewrite_the_order_artifact_it_reads(tmp_path: Path) -> None:
    """The order's arbiter canonicalises in memory; a page must not put those bytes on disk.

    The fixture's artifact is committed straight out of the writer's renderer, so a writer in the
    read path could rewrite it into identical bytes and be invisible to a content comparison. The
    modification time is watched beside the bytes for that reason.
    """
    root = plant_brief_tree(tmp_path)
    path = order_path(root)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert run_brief(root, "--now", NOW)[0] == 0
    after = (path.read_bytes(), path.stat().st_mtime_ns)
    assert after[0] == before[0]
    assert after[1] == before[1]


def test_brief_does_not_write_an_intent_it_could_not_read(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    raw = path.read_bytes()
    path.unlink()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert NOT_READ in out
    assert not path.exists()
    path.write_bytes(raw)


def test_brief_runs_against_a_state_root_without_any_git(tmp_path: Path) -> None:
    """A tree with no history is a page, not a crash, and it leaves nothing behind.

    The fixture's ``.git`` is renamed away, so no repository is reachable from the copy at all:
    the census reports what it cannot read and the brief still prints its parts.
    """
    root = plant_brief_tree(tmp_path)
    shutil.rmtree(root / ".git-brief")
    before = tree_paths(root)
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    assert tree_paths(root) == before
    assert list(sections(out)) == HEADERS
    assert summary_line(out).startswith(brief_module.SUMMARY_PREFIX)


def test_brief_a_state_root_inside_a_larger_repository_leaves_it_alone(tmp_path: Path) -> None:
    """The outer tree is not the state root, and nothing about it moves.

    A copy planted inside a repository that does not track it is the shape that would catch a tool
    reaching for the enclosing tree: the census resolves its ``--repo`` to a git top-level, so a
    page that wrote anything at all would show it in the outer status.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    _git(outer, "init", "-q")
    root = plant_brief_tree(outer, name="noni-work")
    before = porcelain_of(outer, root)
    assert before.strip(), "the copy has to be untracked for this case to mean anything"
    assert run_brief(root, "--now", NOW)[0] == 0
    assert porcelain_of(outer, root) == before
