"""The install gate's page walk skips a ``.git`` inside the tree it walks (issue #231).

Split out of ``tests/test_docs_install_promises.py`` for the 500-line cap in
``tests/test_file_size_limit.py``. The gate itself, its wording and its other claims
stay there, and this module imports ``_verdicts``, ``_quickstart_tree``,
``_install_link_from`` and the precondition sentence from it rather than carrying a
second copy: the assertion is about that gate's walk and has to run through it.

The claim: ``_verdicts`` walks a whole tree root, and every tree it is handed comes from
``_init_repo``, so the root carries a real ``.git`` directory. A page in there (a
planning driver's stale copy of the docs, or one of git's own ``lost-found`` objects)
was read as a page of the tree, which made the gate's verdict depend on what the
enclosing host happened to hold rather than on the plant. The walk now asks the shared
scratch rule (:func:`harness_paths.in_scratch`) with that tree as its root -- the same
rule the real gate's scan over ``REPO`` uses.

Three rows, so none of them can be satisfied by a walk that read nothing:

- a stale page inside ``.git`` is not an offender;
- the identical page outside ``.git`` is still an offender;
- a compliant page beside a stale ``.git`` page keeps both lists empty, so the walk is
  shown to reach the real page and to skip the other.

The pages are written after the tree is committed. A page inside ``.git`` could not be
committed at all -- git refuses to add a path through its own metadata directory, which
is the same reason the real offender was never tracked and never should have been read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _harness import _init_repo
from test_docs_install_promises import (
    PRECONDITION_SENTENCE,
    _install_link_from,
    _quickstart_tree,
    _verdicts,
)

# A script in command position and no word about the install: the shape the gate
# refuses, planted on both sides of .git so one component is the only difference.
_COMMAND_FENCE = "```\nscripts/order.py --repo REPO add ISSUE --decision ID\n```\n"

# The stale page's path, the shape the planning driver's copy of the docs has.
_STALE = ".git/pi-plan-base/ab12cd34/skills/stale/SKILL.md"
# The same page one directory away from .git, which the gate must still refuse.
_OUTSIDE = "skills/probe-skill/SKILL.md"


def _offender() -> str:
    """A page that prints a script command and states nothing about the install."""
    return "# Claiming\n\n" + _COMMAND_FENCE + "\nThe writer appends one row.\n"


def _compliant() -> str:
    """The same page with the sentence and the link a page two directories deep owes.

    ``PRECONDITION_SENTENCE`` carries the root form of the href; the gate resolves a
    relative href against the linking page's own directory, so a page in
    ``skills/probe-skill/`` has to write the two-deep form. The replace is the swap
    from one to the other, and it changes bytes: leaving both sides identical would
    plant the root form and the gate would refuse a page that states the promise.
    """
    return ("# Claiming\n\n" + _COMMAND_FENCE + "\n"
            + PRECONDITION_SENTENCE.replace(_install_link_from(0),
                                            _install_link_from(2)))


def _tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway repo with the quickstart the install links resolve to.

    ``_init_repo`` is what makes the ``.git`` real here, so the plant below is a plain
    directory inside a fresh repository's own metadata folder: nothing is read from or
    written to the checkout the suite runs from.

    The tree is committed by ``_init_repo`` (its own empty initial commit) and the pages
    are written after this returns. ``_commit_tree`` cannot run here: the quickstart and
    the planted pages are the only files, the quickstart is what every row below needs,
    and the planted page under ``.git`` cannot be committed at all -- git refuses to
    ``add`` a path through its own metadata directory, which is the same reason the real
    offender was never tracked and never should have been read. The size gate reads
    ``git ls-files``, so an uncommitted plant costs that gate nothing.
    """
    repo = _init_repo(tmp_path / "probe")
    _quickstart_tree(repo, monkeypatch)
    return repo


def _write(root: Path, rel: str, text: str | None = None) -> None:
    """One planted page, after the commit, since a ``.git`` path cannot be committed."""
    page = root / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text if text is not None else _offender(), encoding="utf-8")


def test_a_page_inside_the_trees_git_dir_is_not_an_offender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (issue #231): ``git init`` made a real ``.git``, and the walk read it.

    On the pre-fix rule this plant was reported as an offender -- observed as
    ``['.git/pi-plan-base/ab12cd34/skills/stale/SKILL.md']`` -- which is the failure the
    shared scratch rule removes. The same bytes outside ``.git`` are asserted as an
    offender below, so passing here cannot come from the plant's shape, its depth or the
    fence it uses.
    """
    repo = _tree(tmp_path, monkeypatch)
    _write(repo, _STALE)
    verdict = _verdicts(repo)
    assert verdict == ([], []), (
        "the gate judged a page inside the tree's own .git as a page of the tree: "
        f"{verdict}")


def test_the_same_page_outside_the_git_dir_is_still_an_offender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The skip is about the ``.git`` component and nothing else about the plant.

    One page per tree, so the two rows differ in exactly one path component. A rule that
    pruned the whole tree, or keyed on the plant's name or its depth, would fail this
    row and pass the one above.
    """
    repo = _tree(tmp_path, monkeypatch)
    _write(repo, _OUTSIDE)
    offenders, unlinked = _verdicts(repo)
    assert offenders == [_OUTSIDE], (
        f"a page outside .git escaped the install gate: {offenders}")
    assert unlinked == [], (
        f"the link assertion reported something other than the planted page: {unlinked}")


def test_a_compliant_page_beside_a_git_page_keeps_the_gate_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pairing control in one tree: the skipped stale page and a real page.

    The state a real checkout reaches on the day the planning driver's copy exists: the
    stale page under ``.git`` and a compliant page outside it. Both lists are empty, so
    the walk is shown to reach the real page (its sentence and link are what keep it out
    of them) and never to open the one under ``.git``. A walk that skipped everything
    would satisfy a bare "no offenders" check, which is why the row above keeps the
    offender shape alive in the same module.
    """
    repo = _tree(tmp_path, monkeypatch)
    _write(repo, _STALE)
    _write(repo, _OUTSIDE, _compliant())
    verdict = _verdicts(repo)
    assert verdict == ([], []), (
        f"the gate refused a compliant page, or read the stale one: {verdict}")
