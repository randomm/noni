"""Every tracked source file stays at or under the size one responsibility is worth.

The rule (AGENTS.md, Project conventions): a tracked Python file, shell file,
workflow YAML or shebang'd file is at or under 500 lines; a SKILL.md is at or
under 400. Markdown other than SKILL.md, JSON and data files are exempt: they
are prose and fixtures, not code. There is no exception list and no override
flag, so the only way past the limit is to split the file.

Issue #52: the repo previously carried a growth ratchet that applied to new
files in three directories only, and nothing enforced it. This is the check
that makes the rule a rule.

The checker takes a repository root, so the fixture test below can run it
against a throwaway repo under ``tmp_path`` rather than against this one. The
hardened ``git ls-files`` listing it measures lives in ``file_size_support``.
"""

from __future__ import annotations

from pathlib import Path

from _harness import _git, _init_repo
from file_size_support import tracked_files

SOURCE_LIMIT = 500
SKILL_MD_LIMIT = 400


def _line_count(path: Path) -> int:
    """Lines in a file, counted the way ``wc -l`` counts them."""
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _limit_for(rel: str, path: Path) -> int | None:
    """The line cap for one tracked path, or None when the path is exempt.

    Markdown (except SKILL.md), JSON and data files have no cap: the rule is
    about source files. Everything else named by the rule is decided by suffix,
    with the shebang as the catch-all for an interpreter this list does not
    name, so a new kind of source file is covered the day it is added.
    """
    if Path(rel).name == "SKILL.md":
        return SKILL_MD_LIMIT
    suffix = path.suffix
    if suffix in (".py", ".sh"):
        return SOURCE_LIMIT
    if suffix in (".yml", ".yaml") and rel.startswith(".github/workflows/"):
        return SOURCE_LIMIT
    first = path.open(encoding="utf-8", errors="replace").readline()
    if first.startswith("#!"):
        return SOURCE_LIMIT
    return None


def oversized_files(repo: Path) -> list[tuple[str, int, int]]:
    """Every tracked source file over its cap, as (path, lines, limit)."""
    offenders = []
    for rel in tracked_files(repo):
        path = repo / rel
        if not path.is_file():
            continue  # a dangling symlink or a stale index entry: nothing to size
        limit = _limit_for(rel, path)
        if limit is None:
            continue
        lines = _line_count(path)
        if lines > limit:
            offenders.append((rel, lines, limit))
    return offenders


def test_tracked_source_files_are_within_the_line_limits() -> None:
    """No tracked source file in this repository is over its cap."""
    repo = Path(__file__).resolve().parent.parent
    offenders = oversized_files(repo)
    listed = "\n".join(f"  {rel}: {lines} lines (limit {limit})" for rel, lines, limit in offenders)
    assert not offenders, (
        "these tracked source files exceed the line limits in AGENTS.md; split "
        f"each one along a natural seam (no exception list, no override):\n{listed}"
    )


def test_the_checker_reports_planted_oversized_files(tmp_path) -> None:
    """A planted 501-line .py and a planted 401-line SKILL.md are both reported.

    The proof that the green run above means something: without this, a
    checker that silently matched no file would pass forever. The throwaway
    repo is built under tmp_path with git init, so the real tree is never
    written to.
    """
    repo = tmp_path / "planted"
    _init_repo(repo)  # creates the directory, inits, and makes one empty commit
    (repo / "long.py").write_text("# x\n" * 501, encoding="utf-8")
    skill = repo / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill\n" * 401, encoding="utf-8")
    (repo / "short.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "notes.md").write_text("# heading\n" * 900, encoding="utf-8")
    _git(repo, "add", "-A")
    # Tracked only, so the untracked scratch note proves the listing comes from
    # git and not from a walk of the working tree. The commit runs with the
    # harness identity: the host's git config is not this test's input.
    _git(repo, "commit", "-q", "-m", "planted")
    (repo / "scratch.md").write_text("# scratch\n" * 900, encoding="utf-8")

    offenders = oversized_files(repo)
    reported = {rel: (lines, limit) for rel, lines, limit in offenders}
    assert set(reported) == {"long.py", "skills/demo/SKILL.md"}, (
        f"the checker reported {sorted(reported)}; expected the two planted files, "
        "and no exemption for the 900-line Markdown note to leak in"
    )
    assert reported["long.py"] == (501, SOURCE_LIMIT)
    assert reported["skills/demo/SKILL.md"] == (401, SKILL_MD_LIMIT)
