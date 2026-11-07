"""The parent-directory link, shared by the direction writer suites (issue #104).

Every direction writer created its output directory with ``mkdir(parents=True)``
after an ``is_dir()`` probe, and both follow links: a ``noni/`` committed as a link
to a directory outside the state repository made the probe answer yes and the mkdir
a no-op, so the writer wrote its artifact into the outside tree and exited 0. The
tests that pin that route as refused live beside the file-level link cases in each
writer's own suite; the planting and the verdict are here, so one shape is planted
one way for ``order``, ``intent`` and ``decide`` rather than three times under three
names.

Two builders, two questions:

- :func:`plant_parent_link` answers "how does a committed directory become a link
  without leaving the fixture's own deletion in the porcelain a refused run is
  measured against";
- :func:`assert_outside_untouched` answers "what had the run not done", which needs
  the decoy body the fixture wrote, not merely a directory listing.

The three verbs and the three codes are deliberately NOT here: they belong to the
test that names the writer, and a shared table would let a suite assert another
writer's code.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from _harness import _git

# The body an outside directory holds before a run, at the name the writer would
# have used. Deliberately not bytes any writer produces: the comparison after a
# refused run is what says the run never reached this file.
OUTSIDE_DECOY = "decoy written by the fixture, never by a writer\n"


def plant_parent_link(repo: Path, outside: Path, rel: str) -> Path:
    """Move the committed directory ``repo/rel`` to ``outside/rel`` and link it back.

    The content is MOVED, not copied, so the outside tree holds the bytes the
    fixture committed -- the record, in the ledger's case -- that a writer following
    the link would have read, and the byte comparison after the run is what says
    nobody did. An absent position simply gets a link to an empty outside directory,
    which is the state a first run would have created.

    ``rel`` is spelled under the repo (``noni``, ``noni/direction`` or
    ``noni/decisions``) and the outside tree mirrors it component for component,
    because the link's target is the directory the writer believes it is writing
    into: an outside tree with the level above it flattened away would itself look
    like a ``noni/`` to a following reader, and the fixture's own content would then
    read as "the run wrote outside".

    The committed path is untracked first. A link standing where a tracked directory
    was is a work-tree deletion git reports as `` D``, and a refused run is compared
    against the porcelain the fixture itself produced -- so the fixture removes its
    path from the index and commits that. The bytes stay where they are (now under
    ``outside``) and the tree the run sees is clean, which is the precondition every
    refusal assertion in the writer suites states.
    """
    target = repo / rel
    inner = outside / rel
    inner.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        _git(repo, "rm", "-r", "--cached", "--quiet", "--", rel)
        _git(repo, "commit", "-q", "-m", f"fixture: move {rel} out of the tree")
        shutil.move(str(target), str(inner))
    else:
        inner.mkdir()
    target.symlink_to(inner)
    return target


def assert_outside_untouched(outside: Path, rel: str, name: str) -> None:
    """The decoy the fixture wrote at ``outside/rel/name`` still holds its own bytes.

    The tree is deliberately NOT asserted empty: the fixture's own committed content
    -- the record a citation needs, in the ledger's case, or the whole ``noni`` for a
    link above it -- moved out here too, so a refusal is owed the file it would have
    written, not a bare directory. A run that wrote through the link leaves that
    position holding artifact bytes instead of the decoy, and a run that read through
    it leaves the decoy's bytes changed; both are caught by reading the position and
    comparing, rather than by a listing a reader has to eyeball.
    """
    planted = outside / rel / name
    assert planted.is_file(), (
        f"the decoy a refused writer would have replaced is not there: "
        f"{sorted(str(p.relative_to(outside)) for p in outside.rglob('*'))}")
    assert planted.read_text(encoding="utf-8") == OUTSIDE_DECOY, (
        "a refused run wrote through the link and replaced the bytes the fixture "
        "wrote outside the repository")


def write_outside_decoy(outside: Path, rel: str, name: str) -> Path:
    """The decoy body, at ``outside/rel/name``: what a following writer would replace.

    The caller passes the writer's own artifact name (``order.json``, ``intent.md``
    or a record id), so the assertion in :func:`assert_outside_untouched` is about
    the file that run composes and not about some file next to it.
    """
    planted = outside / rel / name
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(OUTSIDE_DECOY, encoding="utf-8")
    return planted
