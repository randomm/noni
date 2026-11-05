"""Every tracked source file stays at or under the size one responsibility is worth.

The rule (AGENTS.md, Project conventions): a tracked Python file, shell file,
workflow YAML or shebang'd file is at or under 500 lines; a SKILL.md is at or
under 400. Suffix comparison is case-insensitive, so ``MODULE.PY`` is a source
file too. Markdown other than SKILL.md, JSON and data files are exempt: they
are prose and fixtures, not code. There is no exception list and no override
flag, so the only way past the limit is to split the file.

Issue #52: the repo previously carried a growth ratchet that applied to new
files in three directories only, and nothing enforced it. This is the check
that makes the rule a rule.

The checker takes a repository root, so the fixture tests below can run it
against a throwaway repo under ``tmp_path`` rather than against this one. The
hardened ``git ls-files`` listing it measures lives in ``file_size_support``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# The helper modules live in tests/ alongside this one, on the same bare import
# path as the harness facade, so they belong in the same block as it.
from _harness import _git, _init_repo
from file_size_hardening_support import (
    _arm_fsmonitor,
    _repo_with_planted_violations,
    _stale_index,
)
from file_size_support import tracked_files, tracked_files_unhardened

SOURCE_LIMIT = 500
SKILL_MD_LIMIT = 400

_MISSING = "tracked but missing"


def _line_count(path: Path) -> int:
    """Lines in a file: ``str.splitlines`` over its decoded text.

    Not ``wc -l``, which counts newlines and would call a 500-line file whose
    last line has no terminator 499. Counting split segments is the
    conservative direction: it never reports fewer lines than the text has.
    Undecodable bytes are replaced rather than raised, so an odd encoding
    cannot make the gate crash.
    """
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _limit_for(rel: str, path: Path) -> int | None:
    """The line cap for one tracked path, or None when the path is exempt.

    Markdown (except SKILL.md), JSON and data files have no cap: the rule is
    about source files. Everything else named by the rule is decided by suffix,
    case-insensitively (``.PY`` is Python, per AGENTS.md), and the skill file's
    name is matched the same way: ``path.name.lower() == "skill.md"``. Matching
    that name byte-for-byte instead exempts every skill file whose case differs
    from the canonical spelling, silently and for no reason, which is why both
    halves of the planted case pair are asserted in the proof test below. The
    shebang is the catch-all for an interpreter this list does not name, so a
    new kind of source file is covered the day it is added.
    """
    if path.name.lower() == "skill.md":
        return SKILL_MD_LIMIT
    suffix = path.suffix.lower()
    if suffix in (".py", ".sh", ".jq"):
        # .jq is the census's schema program: shipped, read by path from a shell
        # script, and load-bearing for every record the ledger holds, so it is
        # source by this rule's own reasoning even though no shebang names it.
        return SOURCE_LIMIT
    if suffix in (".yml", ".yaml") and rel.startswith(".github/workflows/"):
        return SOURCE_LIMIT
    with path.open("rb") as fh:
        first = fh.readline()
    if first.startswith(b"#!"):
        return SOURCE_LIMIT
    return None


def _violation(rel: str, path: Path) -> tuple[str, str, int] | None:
    """The offender entry for one tracked path, or None when it is within cap.

    A path git tracks but the working tree cannot offer is still a tracked
    source file the rule speaks for, so it is reported with its reason rather
    than skipped: "tracked but missing" for a deleted file or a dangling
    symlink, and the error class for anything else (an unreadable file). A
    tracked symlink is measured through the link, so a link onto an oversized
    file counts against the link's own path: tracking is the act the rule
    governs, and the target may not be tracked at all.
    """
    try:
        if not path.is_file():
            return (rel, _MISSING, 0)
        limit = _limit_for(rel, path)
        if limit is None:
            return None
        lines = _line_count(path)
    except OSError as exc:
        return (rel, f"unreadable: {type(exc).__name__}", 0)
    return None if lines <= limit else (rel, f"{lines} lines", limit)


def oversized_files(repo: Path) -> list[tuple[str, str, int]]:
    """Every tracked source file over its cap, as (path, reason, limit).

    ``reason`` is a line count for an oversized file and the reason for a path
    that could not be measured; ``limit`` is 0 in that second case.
    """
    offenders = []
    for rel in tracked_files(repo):
        violation = _violation(rel, repo / rel)
        if violation is not None:
            offenders.append(violation)
    return offenders


def test_tracked_source_files_are_within_the_line_limits() -> None:
    """No tracked source file in this repository is over its cap, and every
    tracked path can be measured.

    The listing itself is asserted non-empty first: a gate whose git call came
    back with nothing would have no offenders to report and would pass green
    while measuring nothing, so the emptiness check is what makes the green
    run mean "measured and clean" rather than "asked and got nothing".
    """
    repo = Path(__file__).resolve().parent.parent
    listed = tracked_files(repo)
    assert any(Path(rel).suffix.lower() == ".py" for rel in listed), (
        f"the hardened listing found no tracked Python file in {repo}; the gate "
        "is measuring nothing, so a green run here would prove nothing"
    )
    assert listed, f"the hardened listing returned no tracked paths at all for {repo}"
    offenders = oversized_files(repo)
    detail = "\n".join(f"  {rel}: {reason} (limit {limit})" for rel, reason, limit in offenders)
    assert not offenders, (
        "these tracked source files exceed the line limits in AGENTS.md, or are "
        "tracked and not measurable; split each one along a natural seam (no "
        f"exception list, no override):\n{detail}"
    )


def test_the_checker_reports_planted_oversized_files(tmp_path) -> None:
    """One small offender per branch of the rule is reported, and nothing else.

    The proof that the green run above means something: without this, a
    checker that silently matched no file would pass forever. Each branch of
    ``_limit_for`` gets its own file just over its cap, the case-insensitive
    suffix and the shebang catch-all included, the SKILL.md name in both case
    spellings, and a symlink onto an oversized file plus a dangling one (both
    measured through the link, so the link's own path is reported). Also
    present: a tracked file deleted from the working tree. Two controls run
    alongside: a 900-line Markdown note and a 900-line untracked note prove the
    exemptions and the tracked-only listing. The throwaway repo is built under
    tmp_path with git init, so the real tree is never written to.
    """
    repo = tmp_path / "planted"
    _init_repo(repo)  # creates the directory, inits, and makes one empty commit
    # ``git init`` sets core.ignorecase from the platform, and on a case-
    # insensitive filesystem it folds case and makes an upper/lower pair of
    # names one file. This gate is run on Linux, where it is false, and the
    # planted set below depends on that: pin it so the assertion is the same
    # everywhere rather than silently dropping an offender on macOS.
    _git(repo, "config", "core.ignorecase", "false")
    files = {
        # The .py, .sh and workflow files each carry one # comment line as
        # content, so every one of them is exactly 501 lines by splitlines.
        "long.py": "# x\n" + "# y\n" * 500,
        "CAPS.PY": "# x\n" + "# y\n" * 500,
        "run.sh": "# x\n" + "# y\n" * 500,
        # The census's schema program: a .jq file is source under the rule, so one
        # just over the cap must be reported and not skipped for its suffix.
        "schema.jq": "# x\n" + "# y\n" * 500,
        ".github/workflows/x.yml": "# x\n" + "# y\n" * 500,
        # The shebang catch-all file too, with a # comment rather than a second
        # #! line so the interpreter line does not make it 502.
        "hook": "#!/bin/sh\n# x\n" + "# y\n" * 499,
        "skills/demo/SKILL.md": "# skill\n" * 401,
        # The case-insensitive SKILL.md match, planted with the name in lower
        # case and the extension in upper case, so a regression to an exact-name
        # comparison (in either part) shows up here.
        "skills/other/skill.MD": "# skill\n" * 401,
        "skills/caps/SKILL.MD": "# skill\n" * 401,
        # A symlink onto an oversized file: measured through the link, so the
        # link's own path is the offender, not a skipped entry.
        "link-to-long.py": ("symlink", "long.py"),
        # A tracked symlink whose target does not exist: reported as missing,
        # not skipped, and not an OSError from the failed stat.
        "dangling.md": ("symlink", "nowhere.md"),
        "short.py": "print('ok')\n",
        "notes.md": "# heading\n" * 900,
        "gone.py": "# x\n" * 501,
    }
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, tuple):
            os.symlink(content[1], target)
        else:
            target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    # Tracked only, so the untracked scratch note proves the listing comes from
    # git and not from a walk of the working tree. The commit runs with the
    # harness identity: the host's git config is not this test's input.
    _git(repo, "commit", "-q", "-m", "planted")
    (repo / "scratch.md").write_text("# scratch\n" * 900, encoding="utf-8")
    # Deleted after being committed, so git still tracks it and the working
    # tree cannot offer it: the gate must name it, not skip it and not crash.
    (repo / "gone.py").unlink()

    offenders = oversized_files(repo)
    reported = {rel: (reason, limit) for rel, reason, limit in offenders}
    assert set(reported) == set(files) - {"short.py", "notes.md"}, (
        f"the checker reported {sorted(reported)}; expected the planted offenders "
        "only, with no exemption for the 900-line Markdown note to leak in and "
        "no untracked file in the listing"
    )
    assert reported["long.py"] == ("501 lines", SOURCE_LIMIT)
    assert reported["CAPS.PY"] == ("501 lines", SOURCE_LIMIT)
    assert reported["run.sh"] == ("501 lines", SOURCE_LIMIT)
    assert reported["schema.jq"] == ("501 lines", SOURCE_LIMIT)
    assert reported[".github/workflows/x.yml"] == ("501 lines", SOURCE_LIMIT)
    assert reported["hook"] == ("501 lines", SOURCE_LIMIT)
    assert reported["skills/demo/SKILL.md"] == ("401 lines", SKILL_MD_LIMIT)
    assert reported["skills/other/skill.MD"] == ("401 lines", SKILL_MD_LIMIT)
    assert reported["skills/caps/SKILL.MD"] == ("401 lines", SKILL_MD_LIMIT)
    # The symlink is reported against its own path, at the cap of its target's
    # suffix: a regression to skipping symlinks drops this key and fails here.
    assert reported["link-to-long.py"] == ("501 lines", SOURCE_LIMIT)
    # Both unmeasurable paths carry the missing reason and a 0 limit, not a
    # crash and not a silent drop: the dangling link is the same case as the
    # deleted file, reached through a failed stat rather than an absent path.
    assert reported["dangling.md"] == (_MISSING, 0)
    assert reported["gone.py"] == (_MISSING, 0)


def test_the_size_listing_does_not_run_a_repo_local_fsmonitor(tmp_path) -> None:
    """The gate's ``git ls-files`` is hardened against the tree it measures.

    ``core.fsmonitor`` names a program git execs to ask which files changed, so
    a config planted in the tree being measured turns a read-only listing into
    execution of that tree's code under the gate's privileges. The helper exits
    0 and writes a marker, so the marker's absence is the assertion; the
    offenders the gate still reports for the same tree are the control that the
    listing itself happened.

    The assertion needs a control of its own: on a git that never consults
    ``core.fsmonitor`` for a listing, the marker would be absent no matter what
    the gate passed. So the same armed repo is listed twice, first plain and
    then hardened, in the same ambient-free environment (only the ``-c``
    overrides differ), and the control must show the marker appearing. If it
    does not on this git version, the test skips rather than passes vacuously.
    """
    repo = _repo_with_planted_violations(tmp_path, "fsmonitor")
    marker = repo / "FSMONITOR_RAN"
    _arm_fsmonitor(repo, marker)

    _stale_index(repo)
    tracked_files_unhardened(repo)
    if not marker.exists():
        # Not a vacuous pass: this git did not exec the monitor for a plain
        # listing, so the hardened run below could not have been proved here.
        pytest.skip(
            "this git does not run core.fsmonitor for 'ls-files', so the "
            "unhardened control never fires and the hardening is untestable here"
        )
    marker.unlink()

    _stale_index(repo)
    offenders = oversized_files(repo)

    assert {rel for rel, _reason, _limit in offenders} == {"long.py", "gone.py"}
    assert not marker.exists(), "the size gate ran a core.fsmonitor helper it must not run"
