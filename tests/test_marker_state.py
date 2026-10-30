"""``_marker``: where the marker lives, what it reads back, and undoing one.

The marker is the uncommitted half of a registration, so the properties that
matter are the ones about the tree it leaves behind: the path is built from
``--repo`` alone (so an inherited environment cannot move it), a linked worktree
marks itself and not its shared repository, and a failed commit puts the bytes
back exactly as they were -- or says plainly that it could not.
"""

from __future__ import annotations

import os
from pathlib import Path

from _harness import _git_ok

from noni import _marker


def _plain_clone(tmp_path: Path) -> Path:
    """A git repo whose ``.git`` is a directory (the plain-clone case)."""
    repo = tmp_path / "clone"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    return repo


def test_marker_path_is_built_from_the_repo_and_its_own_dot_git(tmp_path):
    """The path is a literal off ``--repo``: no rev-parse, no GIT_DIR, no work tree.

    The plain clone's marker sits in ``<repo>/.git``, and a tree with no ``.git``
    at all resolves to None -- the caller mints a session, writes no marker and
    says so, rather than marking some directory an inherited variable named.
    """
    repo = _plain_clone(tmp_path)
    assert _marker.marker_path(repo) == repo / ".git" / _marker.MARKER_NAME

    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert _marker.marker_path(plain) is None


def test_marker_path_follows_a_linked_worktrees_gitdir_line(tmp_path):
    """A linked worktree marks itself, so two worktrees never share a session.

    ``<repo>/.git`` is a file whose ``gitdir:`` line names the directory holding
    this worktree's own state, and that is where the marker belongs. The three
    shapes that name no such directory -- a blank line, a malformed line, and a
    line pointing at a directory that does not exist -- all answer None, which is
    the caller's cue to register without marking.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    gitdir = tmp_path / "repo-git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert _marker.marker_path(worktree) == gitdir / _marker.MARKER_NAME

    # A relative gitdir: is joined to the worktree, not to the process's cwd.
    relative = tmp_path / "relative"
    relative.mkdir()
    (tmp_path / "relative-git").mkdir()
    (relative / ".git").write_text("gitdir: ../relative-git\n", encoding="utf-8")
    resolved = _marker.marker_path(relative)
    assert resolved is not None
    assert os.path.realpath(str(resolved)) == os.path.realpath(
        str(tmp_path / "relative-git" / _marker.MARKER_NAME))
    assert resolved.is_file() or resolved.parent.is_dir()

    for body in ("gitdir:\n", "gitdir:   \n", "not a gitdir line\n",
                 "gitdir: /no/such/directory\n"):
        broken = tmp_path / f"broken-{abs(hash(body))}"
        broken.mkdir()
        (broken / ".git").write_text(body, encoding="utf-8")
        assert _marker.marker_path(broken) is None, body


def test_read_marker_raw_keeps_bytes_the_reader_reports_nothing_for(tmp_path, monkeypatch):
    """The restore's source of truth is the marker's bytes, not its parsed value.

    An empty marker somebody left standing is a fact about the tree, so it reads
    back as ``""`` (and restores as an empty file) rather than as absence; a
    marker that exists but cannot be read is likewise not this run's creation, so
    it reads back ``""`` too and is restored rather than deleted. A marker this
    run never saw (absent, or no path at all) is the only case that answers None.

    The unreadable case is driven by making the read itself fail rather than by
    chmod: a suite running as root reads a 000 file happily, and a test that
    passed because of that would be pinning nothing.
    """
    assert _marker.read_marker_raw(None) is None

    missing = tmp_path / "missing"
    missing.mkdir()
    assert _marker.read_marker_raw(missing / _marker.MARKER_NAME) is None

    empty = tmp_path / "empty"
    empty.mkdir()
    empty_marker = empty / _marker.MARKER_NAME
    empty_marker.write_text("", encoding="utf-8")
    assert _marker.read_marker_raw(empty_marker) == ""

    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    stuck = unreadable / _marker.MARKER_NAME
    stuck.write_text("2026-10-01-abcdef\n", encoding="utf-8")

    def refusing_read(self, *args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", refusing_read)
    assert _marker.read_marker_raw(stuck) == ""
    # The parsed reader answers nothing for the same file, which is the point of
    # the two being different functions.
    assert _marker.read_marker(stuck) is None


def test_restore_marker_reports_a_restore_that_could_not_land(tmp_path, monkeypatch):
    """A restore that cannot write is told about, not swallowed.

    The commit refusal is still the headline the operator reads, so a failed
    restore never raises out of the failure path -- but it comes back False,
    which is what lets the writer name the marker that may still be standing.
    The two shapes here are the ones the real writer can hit: a parent directory
    that refuses the write, and a marker whose previous bytes were not UTF-8
    (read with surrogateescape, so the UTF-8 write cannot encode them).
    """
    marked = tmp_path / "marked"
    marked.mkdir()
    target = marked / _marker.MARKER_NAME

    assert _marker.restore_marker(None, None) is True
    assert _marker.restore_marker(target, None) is True  # nothing to undo

    target.write_text("2026-10-01-abcdef\n", encoding="utf-8")
    assert _marker.restore_marker(target, None) is True
    assert not target.exists()

    assert _marker.restore_marker(target, "2026-10-01-111111\n") is True
    assert target.read_text(encoding="utf-8") == "2026-10-01-111111\n"

    # A byte-exact restore: the odd bytes an earlier run left come back as they
    # were, not as the one value read_marker would have reported.
    target.write_text("2026-10-01-222222\nsecond line\n", encoding="utf-8")
    assert _marker.restore_marker(target, "2026-10-01-222222\nsecond line\n") is True
    assert target.read_text(encoding="utf-8") == "2026-10-01-222222\nsecond line\n"

    # Not UTF-8: read_marker_raw hands back lone surrogates, and the UTF-8 write
    # cannot encode them. That is a restore that cannot land, not a traceback.
    weird = tmp_path / "weird"
    weird.mkdir()
    weird_marker = weird / _marker.MARKER_NAME
    assert _marker.restore_marker(weird_marker, "abc\udcffdef\n") is False

    # A parent directory that cannot be written into, driven by making the write
    # itself fail (a suite running as root would write into a 0500 directory).
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked_marker = blocked / _marker.MARKER_NAME
    blocked_marker.write_text("x\n", encoding="utf-8")

    def refusing_replace(src, dst, *args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", refusing_replace)
    assert _marker.restore_marker(blocked_marker, "y\n") is False
    monkeypatch.undo()
    assert blocked_marker.read_text(encoding="utf-8") == "x\n"
