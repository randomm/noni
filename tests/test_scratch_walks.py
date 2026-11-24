"""The repo-rooted harness walks skip the scratch folders AGENTS.md sanctions (issue #205).

Three walks start at the repository root: the two ``shutil.copytree`` clones
(``quickstart_topology.materialise_clone`` and ``readme_support._materialise_clone``)
and the decide-skill page scan, which walks ``REPO.rglob("*.md")`` in
``tests/test_decide_skill.py``. All three copied or read ``tmp/`` and ``.worktrees/``,
which is exactly where a dev run keeps its per-issue scratch (AGENTS.md: one ignored
folder per issue, ``tmp/issue-N/``). The copies then walked into their own output and
never finished; the page scan read every Markdown file a venv or a whole worktree
happened to hold.

The rule has one owner: :func:`harness_paths.scratch_ignore` (the copytree callable)
and :func:`harness_paths.in_scratch` (the walk predicate), and the folder names come
from constants in ``tests/harness_paths.py`` that both shapes read. ``tmp`` is skipped
only directly under the root the walk started from, so a page nested below a directory
that happens to be named ``tmp`` is still read; ``.worktrees`` and ``.git`` are skipped
by name at any depth.

Every skip proven here is attributable to the scratch rule itself, and the evidence for
that is ``test_the_ignore_callable_and_the_predicate_agree``, not the absence of
ignore-list names from the plant. The plant now does carry a ``.git`` folder (the
regression case below), so the proof is that the two shapes of the one rule answer for
the same paths: whatever the predicate calls scratch is exactly what the copy is
missing, and nothing else.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import readme_support
from _harness import REPO
from quickstart_topology import materialise_clone

# ``harness_paths`` is imported inside the tests that exercise the rule: a baseline
# run (the pre-fix code, to watch these tests fail) must still be able to import this
# module and reach the two clone helpers.

# The scratch pages the plant puts under each ignored folder, and the tracked-shaped
# pages it puts outside them. One pair of dicts so the copy assertions and the walk
# assertions are answered by the same names. Nothing under ``tmp`` or ``.worktrees``
# reuses a name the clone ignore list already carried; the ``.git`` pair below is the
# exception and is answered for by the agreement test, which compares the two shapes of
# the rule against each other on this same tree.
SCRATCH_PAGES = {
    "tmp/issue-1/a/b/note.md": "# scratch note\n",
    "tmp/issue-1/venv/lib/x.py": "raise RuntimeError('scratch venv')\n",
    ".worktrees/wt/page.md": "# worktree page\n",
    "tmp/deep/caches/pip/index.md": "# cache page\n",
    # The copy a planning driver keeps of the docs, inside the checkout's own ``.git``
    # (issue #231): a stale page there was read as a tracked page of this repository.
    ".git/pi-plan-base/ab12cd34/skills/probe/SKILL.md": "# stale plan page\n",
    # The same name nested below the root, which is the case a root-only widening of
    # the rule would have missed.
    "docs/sub/.git/objects/page.md": "# stale nested page\n",
}
TRACKED_PAGES = {
    "README.md": "# top\n",
    "docs/deep/nested/page.md": "# deep\n",
    "docs/tmp/issue-7/page.md": "# a tracked page below a directory named tmp\n",
    "docs/sub/deeper/page.md": "# deeper\n",
    # The pairing control for the plant above: a page in the same ``docs/sub/`` that
    # carries no ``.git`` component, so a rule that skipped ``.git`` too widely (a
    # substring match, or a name match on the wrong segment) reddens this row.
    "docs/sub/paired/page.md": "# the neighbour of the nested .git page\n",
}
PLANTED = {**SCRATCH_PAGES, **TRACKED_PAGES}

# The page the clones must still carry: tracked, and under a name no ignore rule
# touches. It is the control that says a clone that skipped scratch copied something.
REPO_PAGE = "src/noni/_why.py"

# The scratch plant's path *inside a clone*: it is made at ``REPO/tmp/issue-205-plant``
# and the clone keeps the ``tmp`` segment when the rule is missing, so the clone-side
# name is what the assertions look for.
PLANT_PATH = "tmp/issue-205-plant"

# The droppings both clones dropped before issue #205. Pinned here because the fix
# moved them to one shared tuple: a name dropped from that tuple would start copying
# build garbage into every clone, and only this test would say so.
PREVIOUSLY_IGNORED = (".git", "__pycache__", ".venv", "*.pyc", ".pytest_cache",
                      ".coverage", ".coverage.*", "noni.egg-info",
                      "noni_noni.egg-info", ".worktrees")


def _plant_repo(root: Path) -> Path:
    """A throwaway repo-shaped tree holding the plant: scratch plus tracked pages.

    Built entirely under ``tmp_path`` with plain ``mkdir`` and ``write_text``: nothing
    here is made with ``git``, ``git worktree add`` or ``git init``, and nothing is
    written into the real checkout. The ``.worktrees`` and ``.git`` entries are plain
    directories, so the assertion that each is skipped cannot be explained by anything
    a real worktree or a real repository directory would have brought with it, and the
    ``.git`` plant cannot be answered by the folder the host happened to leave behind.
    """
    for rel, text in PLANTED.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _plant_real_scratch() -> Path:
    """Scratch planted in the real checkout, for the two clones to copy out of.

    The ``tmp_path`` plant proves the rule on a throwaway tree; it cannot prove the
    clones skip the scratch the harness actually meets, since both copies start at
    ``REPO``. So a scratch subtree is planted in the checkout for the duration of one
    test and removed in its ``finally``: scratch left behind would dirty the tree for
    the next cycle's status gate.
    """
    scratch = REPO / "tmp" / "issue-205-plant"
    (scratch / "a" / "b").mkdir(parents=True, exist_ok=True)
    (scratch / "a" / "b" / "note.md").write_text("# planted scratch\n", encoding="utf-8")
    (scratch / "venv" / "lib").mkdir(parents=True, exist_ok=True)
    (scratch / "venv" / "lib" / "x.py").write_text("pass\n", encoding="utf-8")
    return scratch


def _copied_paths(dest: Path) -> set[str]:
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}


def _assert_clone_skips_planted_scratch(dest: Path) -> None:
    """No path under the scratch planted in the real tree reached the clone.

    The plant lives at ``REPO/tmp/issue-205-plant``, so in the clone it sits at
    ``tmp/issue-205-plant``: the check is on the full clone-relative path, because a
    check on the bare plant name passes while the whole scratch subtree is present.
    """
    leaked = [rel for rel in _copied_paths(dest)
              if rel == PLANT_PATH or rel.startswith(PLANT_PATH + "/")]
    assert not leaked, (
        f"the clone copied scratch from the real tree: {sorted(leaked)[:5]} "
        f"({len(leaked)} paths)")


def _assert_real_repo_clone(dest: Path, copied: set[str]) -> None:
    """Common assertions for a clone made from the real ``REPO``.

    The scratch half is the point; the tracked half is the control that says the copy
    copied: a rule that skipped everything would satisfy a bare "no scratch" check.
    The bound is the one the real tree sets today (the suite runs with no ``tmp/``
    under it): a copy that recursed wrote the scratch into the clone, and a copy of
    this tree costs seconds, not minutes.
    """
    _assert_clone_skips_planted_scratch(dest)
    assert REPO_PAGE in copied, f"the clone lost the tracked page {REPO_PAGE}"
    tracked = _tracked_markdown()
    assert tracked, f"git listed no Markdown page under {REPO}"
    missing = sorted(p for p in tracked if p not in copied)
    assert not missing, f"the clone lost tracked pages: {missing[:5]}"
    assert len(copied) < 2000, (
        f"the clone copied {len(copied)} files from a tree whose tracked source is "
        "far smaller: the copy walked scratch, or its own output")


def _tracked_markdown() -> list[str]:
    """Every Markdown path git tracks under ``REPO``, as the product lists it."""
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.md"],
                            capture_output=True, text=True, timeout=120)
    assert listed.returncode == 0, listed.stderr
    return [line for line in listed.stdout.splitlines() if line]


def test_materialise_clone_skips_scratch_and_keeps_the_rest(tmp_path) -> None:
    """The quickstart clone holds no scratch and loses no tracked page.

    The copy is the first thing the session fixture does, and today it walks into its
    own output when the tree carries ``tmp/``. Asserting on contents (not on elapsed
    time) is what reddens on the old code: a copy that recursed left every scratch path
    in the destination.
    """
    from harness_paths import in_scratch  # noqa: F401  (imported here so a pre-fix baseline run can still import this module)

    _plant_repo(tmp_path / "repo")
    dest = tmp_path / "clone"
    _plant_real_scratch()
    try:
        materialise_clone(dest)
    finally:
        shutil.rmtree(REPO / "tmp" / "issue-205-plant", ignore_errors=True)
    _assert_real_repo_clone(dest, _copied_paths(dest))


def test_readme_support_clone_skips_scratch_and_keeps_the_rest(tmp_path) -> None:
    """The README try-it clone carries the same rule, not a second copy of it.

    The two clones held byte-identical ignore literals and nothing compared them, so a
    fix landed in one left the other broken and green.
    """
    from harness_paths import in_scratch  # noqa: F401  (imported here so a pre-fix baseline run can still import this module)

    _plant_repo(tmp_path / "repo")
    dest = tmp_path / "clone"
    _plant_real_scratch()
    try:
        readme_support._materialise_clone(dest)
    finally:
        shutil.rmtree(REPO / "tmp" / "issue-205-plant", ignore_errors=True)
    _assert_real_repo_clone(dest, _copied_paths(dest))


def test_the_page_walk_skips_scratch_and_keeps_every_page(tmp_path) -> None:
    """The predicate the page scan uses prunes both scratch folders and nothing else.

    The same planted tree as the two clones, walked the way the decide-skill test walks
    it. ``docs/tmp/issue-7/page.md`` is the over-pruning control: a basename glob at
    any depth would have skipped a directory named ``tmp`` wherever it appeared, and
    the rule is root-only.
    """
    from harness_paths import in_scratch

    root = _plant_repo(tmp_path / "repo")
    walked = {p.relative_to(root).as_posix() for p in sorted(root.rglob("*"))
              if p.is_file() and not in_scratch(root, p)}
    for rel in SCRATCH_PAGES:
        assert rel not in walked, f"the walk reached scratch: {rel}"
    for rel in TRACKED_PAGES:
        assert rel in walked, f"the walk pruned a planted page: {rel}"


def test_the_ignore_callable_and_the_predicate_agree(tmp_path) -> None:
    """One rule, two shapes: what the copytree hides, the predicate hides too.

    The copytree half takes basenames and the walk half takes paths, so the two
    representations can drift without either test noticing. ``shutil.copytree`` is what
    consumes the callable, so the comparison runs through a real copy: whatever the
    predicate calls scratch is exactly what the copy is missing, and nothing else.
    """
    from harness_paths import in_scratch, scratch_ignore

    root = _plant_repo(tmp_path / "repo")
    dest = tmp_path / "copy"
    shutil.copytree(root, dest, ignore=scratch_ignore(root))
    kept = {p.relative_to(root).as_posix() for p in sorted(root.rglob("*"))
            if p.is_file() and not in_scratch(root, p)}
    copied = _copied_paths(dest)
    assert copied == kept, (
        f"the copytree ignore and the walk predicate disagree; "
        f"only predicate: {sorted(kept - copied)}, "
        f"only ignore: {sorted(copied - kept)}")


def test_the_repo_page_walk_still_yields_every_tracked_markdown() -> None:
    """The control against over-pruning, run on the real repository.

    The page scan's walk must still reach every Markdown file git tracks. ``git
    ls-files '*.md'`` is the listing the product itself reads, so it is the standard
    the walk is measured against rather than a list this file maintains.
    """
    from harness_paths import in_scratch

    tracked = _tracked_markdown()
    assert tracked, f"git listed no Markdown page under {REPO}"
    walked = {p.relative_to(REPO).as_posix() for p in REPO.rglob("*.md")
              if not in_scratch(REPO, p)}
    missing = sorted(set(tracked) - walked)
    assert not missing, f"the scratch rule pruned tracked pages: {missing}"


def test_the_shared_clone_rule_still_drops_every_build_dropping(tmp_path) -> None:
    """The shared rule is a superset of the two lists it replaced, not a shorter one.

    Both clones carried the same ten literals; the fix folded them into one tuple with
    the scratch names added. A name quietly lost from that tuple copies build garbage
    into every clone, which is a bug of its own and invisible to the scratch assertions
    above, so it is asserted on its own terms.
    """
    from harness_paths import CLONE_IGNORE_NAMES, SCRATCH_DIR_NAME, scratch_ignore

    kept = set(CLONE_IGNORE_NAMES) | {SCRATCH_DIR_NAME}
    assert set(PREVIOUSLY_IGNORED) <= kept, (
        f"the shared clone rule lost a name the two lists dropped before: "
        f"{sorted(set(PREVIOUSLY_IGNORED) - kept)}")
    root = tmp_path / "droppings"
    for name in PREVIOUSLY_IGNORED:
        if "*" not in name:
            (root / name / "sub").mkdir(parents=True, exist_ok=True)
            (root / name / "sub" / "f").write_text("x\n", encoding="utf-8")
    (root / "keep.pyc").write_text("x\n", encoding="utf-8")
    (root / "tracked.md").write_text("# kept\n", encoding="utf-8")
    dest = tmp_path / "copy"
    shutil.copytree(root, dest, ignore=scratch_ignore(root))
    copied = _copied_paths(dest)
    assert copied == {"tracked.md"}, f"the clone copied a dropping or lost a page: {copied}"


def test_a_page_under_a_non_root_tmp_directory_is_still_walked(tmp_path) -> None:
    """A directory named ``tmp`` below the root is ordinary content, not scratch.

    The root-only half of the rule, stated on its own so a widening to a name match at
    any depth reddens one named test rather than a loop over a dict. ``.git`` is the
    opposite half and is asserted next to it, because the two names differ on purpose
    and a single test covering both would not say which half broke.
    """
    from harness_paths import in_scratch

    root = _plant_repo(tmp_path / "repo")
    nested = root / "docs" / "tmp" / "issue-2" / "page.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("# nested\n", encoding="utf-8")
    assert in_scratch(root, nested) is False
    assert in_scratch(root, root / "tmp" / "issue-1" / "a" / "b" / "note.md") is True
    assert in_scratch(root, root / "docs" / "x" / ".worktrees" / "y.md") is True
    # ``.git`` is matched by name at any depth, the way ``.worktrees`` is: the copy
    # that got walked was ``.git/pi-plan-base/<hash>/skills/...``, so a rule that
    # matched the name only as the first component would have skipped nothing at all
    # for a fixture tree or a sub-repository.
    assert in_scratch(root, root / ".git" / "pi-plan-base" / "ab12cd34"
                      / "skills" / "probe" / "SKILL.md") is True
    assert in_scratch(root, root / "docs" / "sub" / ".git" / "objects"
                      / "page.md") is True
    # The page planted beside the nested one is not scratch: the name is a path
    # component, not a substring, and not a property of the directory around it.
    assert in_scratch(root, root / "docs" / "sub" / "paired" / "page.md") is False


def test_the_page_walk_skips_a_git_copy_of_the_docs_and_keeps_the_pages(tmp_path) -> None:
    """Regression (issue #231): a docs copy under ``.git`` is never a tracked page.

    The failing scan is ``tests/test_decide_skill.py``'s page walk, which is
    ``REPO.rglob("*.md")`` filtered by :func:`harness_paths.in_scratch`. A planning
    driver keeps its base copy of the docs under the checkout's own ``.git``, so on the
    day that folder holds a copy the scan read its stale pages and reported them as
    pages of this repository. From a worktree ``.git`` is a pointer file and the walk
    never descends, which is why the failure was intermittent.

    Reproduced here on a throwaway tree so it fails first whatever the host holds:
    this is the same rglob-plus-predicate shape the scan uses, so the skip is proven by
    the rule and not by an empty ``.git``. The tracked rows are the pairing controls --
    ``docs/sub/paired/page.md`` sits beside the nested ``.git`` page, and
    ``docs/sub/deeper/page.md`` sits under the same ``docs/sub`` -- so a rule that
    skipped ``.git`` too widely could not pass this and the test above.
    """
    from harness_paths import in_scratch

    root = _plant_repo(tmp_path / "repo")
    git_pages = [rel for rel in SCRATCH_PAGES if ".git" in Path(rel).parts]
    assert len(git_pages) == 2, (
        f"the plant lost a .git page, so this test proves nothing: {git_pages}")

    walked = {p.relative_to(root).as_posix() for p in sorted(root.rglob("*.md"))
              if p.is_file() and not in_scratch(root, p)}
    for rel in git_pages:
        assert rel not in walked, (
            f"the page walk reached a page inside .git and would count it as tracked: "
            f"{rel}")
    for rel in TRACKED_PAGES:
        assert rel in walked, f"the page walk pruned a planted page: {rel}"


def test_the_clone_drops_a_git_copy_of_the_docs_too(tmp_path) -> None:
    """The copytree shape drops the ``.git`` copy the predicate calls scratch.

    The clone half had the ``.git`` name in its ignore list before the predicate had
    it, and that is precisely the drift issue #231 exposed: one shape of the rule
    skipped the folder and the other did not. Asserted on the same plant as the walk
    test above, so both shapes answer for the identical names.

    The nested page below is the half the ignore list alone does not carry: a rule that
    dropped only the root's own ``.git`` copied a ``.git`` that sat deeper in the tree.
    """
    from harness_paths import scratch_ignore

    root = _plant_repo(tmp_path / "repo")
    nested = root / "docs" / "sub" / ".git" / "hooks"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "page.md").write_text("# stale nested page\n", encoding="utf-8")
    nested_rel = "docs/sub/.git/hooks/page.md"

    dest = tmp_path / "copy"
    shutil.copytree(root, dest, ignore=scratch_ignore(root))
    copied = _copied_paths(dest)
    git_copied = sorted(rel for rel in copied if ".git" in Path(rel).parts)
    assert not git_copied, f"the clone copied a .git subtree: {git_copied}"
    assert nested_rel not in copied, f"the clone copied a nested .git page: {nested_rel}"
    for rel in TRACKED_PAGES:
        assert rel in copied, f"the clone lost a planted page: {rel}"


def test_a_path_outside_the_root_is_scratch_only_by_the_worktrees_name(tmp_path) -> None:
    """A path the root does not contain is judged by the one name that carries no claim.

    The predicate has a second arm for a path that is not under ``root`` at all. An
    ancestor outside the caller's root says nothing about what that caller treats as
    scratch, so only ``.worktrees`` applies there: it names a scratch layout wherever a
    path carries it, while ``.git`` and ``tmp`` are verdicts about the caller's own
    tree. Pinned because the two arms are the whole predicate and a widening that
    treated every ``.git`` component as scratch would answer for directories the root
    has no opinion about.
    """
    from harness_paths import in_scratch

    root = _plant_repo(tmp_path / "repo")
    elsewhere = root.parent / "elsewhere"
    assert in_scratch(root, elsewhere / ".git" / "x" / "page.md") is False
    assert in_scratch(root, elsewhere / "tmp" / "issue-9" / "page.md") is False
    assert in_scratch(root, elsewhere / ".worktrees" / "wt" / "page.md") is True
