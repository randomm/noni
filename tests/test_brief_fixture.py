"""The brief fixture's committed tar is the tree its builder claims to produce.

The fixture is the ground the whole brief suite stands on: eleven order entries, one intent
file, one decided record, and a last commit whose subject cites it. Every case in the six ``test_brief_*.py`` files asserts against it, and a
case that quietly ran against a different tree would be a green run about a fixture nobody
wrote.

The tar is the artifact (it is what travels, and what the purity suites read member by member)
and ``tests/fixtures/brief/generate.py`` is its specification. This module checks the two agree,
so neither can drift alone:

- :func:`test_brief_fixture_tar_matches_its_builder` regenerates the archive into a throwaway
  directory and compares the member names, modes and bytes to the committed one -- a hand edit
  to the tar, or an edit to the builder without a rebuild, fails here.
- :func:`test_brief_fixture_holds_the_shape_the_suite_asserts` counts what the spec names, read
  out of the tar's own members: eleven entries, one intent file, one record, and the
  ``intent: <record-id>`` commit that makes the census's ``intent`` class see a citation.
- :func:`test_brief_fixture_unpacks_as_a_repository_the_census_can_read` unpacks it and asks git,
  which is the only reader that matters: the census runs ``git -C <top>``, so a fixture that
  unpacks but does not open is not a fixture.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from _harness import REPO

FIXTURE_DIR = REPO / "tests" / "fixtures" / "brief"
GENERATE = FIXTURE_DIR / "generate.py"
ARCHIVE = REPO / "tests" / "fixtures" / "brief.tar"

# The committed fixture's shape, as the brief spec states it. Counted here rather than trusted
# from the tar: these are the numbers the six brief suites' assertions are built on, and a fixture
# that lost an entry would otherwise be discovered by ten unrelated failures instead of one.
ORDER_ENTRIES = 11
INTENT_SECTIONS = 4

# The member names the repository must carry. The work-tree paths are what the brief reads through
# ``--repo``; the ``.git`` ones are what makes the census able to answer a question about history.
WORK_TREE_MEMBERS = ("noni/direction/order.json", "noni/direction/intent.md",
                     "noni/decisions/2026-10-01-brief.json")
GIT_MEMBERS = (".git/HEAD", ".git/config", ".git/index", ".git/packed-refs",
               ".git/logs/HEAD")


def _members(path: Path) -> dict[str, tuple[int, bytes]]:
    """A tar as ``{name: (mode, bytes)}``, directories included.

    The comparison the drift check needs, in the one form that shows a difference rather than
    hiding one: a plain file's bytes, an archive's member list, both as a mapping keyed by name.
    """
    with tarfile.open(path) as archive:
        rows: dict[str, tuple[int, bytes]] = {}
        for member in archive.getmembers():
            handle = archive.extractfile(member)
            rows[member.name] = (member.mode, b"" if handle is None else handle.read())
    return rows


def _generate_into(target: Path) -> Path:
    """Run the builder and hand back the tar it wrote, under a throwaway directory.

    Run as a subprocess with the same interpreter rather than imported: the builder is a script a
    person runs by hand, and the check that means something is the one that runs it the way they
    would. Its own stdout is kept for the failure message, because a builder that died is a
    failure worth reading rather than one worth summarising.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    launched = subprocess.run([sys.executable, str(GENERATE), str(target)],
                              capture_output=True, text=True, timeout=120)
    assert launched.returncode == 0, (launched.stdout, launched.stderr)
    assert target.is_file(), f"the builder wrote no archive at {target}"
    return target


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git call against an unpacked fixture, with the host's config kept out of it."""
    return subprocess.run(["git", "-C", str(repo),
                           "-c", "core.hooksPath=" + os.devnull, *args],
                          capture_output=True, text=True)


def test_brief_fixture_tar_matches_its_builder(tmp_path: Path) -> None:
    """The committed tar is byte-for-byte what ``generate.py`` writes.

    The direction the drift matters in is both ways. Edit the tar by hand and the regenerated one
    differs; edit the builder and forget to rebuild, and the committed one differs. Either way the
    suite would otherwise keep passing against the bytes on disk while the file that claims to
    describe them said something else.
    """
    built = _generate_into(tmp_path / "brief.tar")
    committed, regenerated = _members(ARCHIVE), _members(built)
    assert set(committed) == set(regenerated), (
        f"member list drifted; only committed: {sorted(set(committed) - set(regenerated))}, "
        f"only built: {sorted(set(regenerated) - set(committed))}")
    for name in sorted(committed):
        assert committed[name] == regenerated[name], (
            f"{name}: committed {committed[name][0]}/{len(committed[name][1])} bytes, "
            f"built {regenerated[name][0]}/{len(regenerated[name][1])} bytes; "
            "re-run tests/fixtures/brief/generate.py")


def test_brief_fixture_holds_the_shape_the_suite_asserts() -> None:
    """The counts the brief spec names, read out of the committed tar's own members.

    Read from the archive rather than from a copy of the builder's tables, so this is evidence
    about the artifact and not an agreement between two source files.
    """
    members = _members(ARCHIVE)
    for name in (*WORK_TREE_MEMBERS, *GIT_MEMBERS):
        assert name in members, f"{name} missing from the committed fixture"

    order = json.loads(members["noni/direction/order.json"][1])
    assert order["schema"] == "noni.order/1"
    assert len(order["entries"]) == ORDER_ENTRIES, len(order["entries"])
    assert all("item" not in entry for entry in order["entries"]), \
        "the removed item store's key must not survive in the committed fixture"

    intent = members["noni/direction/intent.md"][1].decode("utf-8")
    headings = [line for line in intent.splitlines() if line.startswith("## ")]
    assert len(headings) == INTENT_SECTIONS, headings

    record = json.loads(members["noni/decisions/2026-10-01-brief.json"][1])
    assert record["status"] == "decided"
    assert all(entry["decision"] == record["id"] for entry in order["entries"]), (
        "every order entry must cite the one committed record")


def test_brief_fixture_unpacks_as_a_repository_the_census_can_read(tmp_path: Path) -> None:
    """git opens the unpacked fixture, and its history says the intent cites the record.

    The census reaches history through ``git -C <top>`` and nothing else, so this is the assertion
    that makes the fixture's ``.git`` worth carrying: ``fsck`` clean, ``status`` clean (an index
    that disagreed with HEAD would make a read-only case measure a dirty tree), and the log of the
    intent file ending in the ``intent: <record-id>`` subject the census's ``intent`` class reads.
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    with tarfile.open(ARCHIVE) as archive:
        archive.extractall(tree, filter="data")

    fsck = _git(tree, "fsck", "--no-dangling")
    assert fsck.returncode == 0, fsck.stderr
    status = _git(tree, "status", "--porcelain")
    assert status.returncode == 0, status.stderr
    assert status.stdout == "", f"the committed tree does not unpack clean: {status.stdout}"
    listed = _git(tree, "ls-files")
    assert listed.stdout.splitlines() and not listed.stderr, listed.stderr

    log = _git(tree, "log", "-1", "--format=%s", "--", "noni/direction/intent.md")
    record_id = json.loads(_members(ARCHIVE)["noni/decisions/2026-10-01-brief.json"][1])["id"]
    assert log.stdout.strip() == f"intent: {record_id}", (
        "the intent file's last commit must name the record the census is to find cited: "
        f"{log.stdout!r} {log.stderr!r}")


def test_brief_fixture_builder_describes_itself_without_writing(tmp_path: Path) -> None:
    """``generate.py`` with no output argument reports the tree and writes nothing.

    The mode a reader of the fixture uses first, and the one that must not touch the tree: the
    counts on stdout, no file created, and a zero exit code. Checked in a
    directory of its own because the suite's environment fixture puts a HOME sandbox in ``tmp_path``
    for every case -- an emptiness assertion made at the root would be a test of that fixture.
    """
    cwd = tmp_path / "describe"
    cwd.mkdir()
    launched = subprocess.run([sys.executable, str(GENERATE)],
                              capture_output=True, text=True, timeout=120,
                              cwd=cwd)
    assert launched.returncode == 0, launched.stderr
    assert "files" in launched.stdout and "commits" in launched.stdout, launched.stdout
    assert list(cwd.iterdir()) == [], f"the describe mode wrote into {cwd}"
