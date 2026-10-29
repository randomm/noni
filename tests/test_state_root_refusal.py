"""The documented exit code for a --repo that is not a directory (issue #39).

docs/PRODUCT.md §7 names one code per tool for this one state: 2 for ``order``,
``register`` and the unified census, 4 for ``claim``, ``close`` and ``release``,
3 for ``decide``. The sentence is only worth writing if a test holds it, because
each tool reaches the state through its own existing refusal (a usage error for
most, decide.py's not-a-work-tree code for one) and nothing else in the suite
compares the seven against the prose.

One table, one run per row: the point is the code, so the assertion is the code
plus a message that names the argument the caller passed wrong. Each run is
launched from a cwd that is not the state root, so a refusal that arrived from
somewhere else would have to produce the number as well.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import (
    CENSUS,
    CLAIM,
    CLOSE,
    DECIDE,
    ORDER,
    REGISTER,
    RELEASE,
    REPO,
    subprocess_env,
)

# The refusal's code and the tool that owes it, exactly as §7 states them. This
# tuple is the prose transcribed: a change on either side breaks this test.
STATE_ROOT_REFUSAL = (
    (ORDER, 2),
    (REGISTER, 2),
    (DECIDE, 3),
    (CLAIM, 4),
    (CLOSE, 4),
    (RELEASE, 4),
)

# The tools §7 gives code 2, and the ones it gives 3 and 4: the prose test below
# reads the numbers off the page rather than trusting this table alone.
DOCUMENTED = {
    2: ("`order`", "`register`", "census"),
    3: ("`decide`",),
    4: ("`claim`", "`close`", "`release`"),
}

# One minimum argv beyond --repo per tool: enough to get past argparse to the
# state-root check, and values no assertion depends on, since the run is refused
# before any of them is read.
ARGV = {
    CLAIM: ("--session-id", "2026-10-01-aaaaaa", "--task", "#42"),
    CLOSE: ("--session-id", "2026-10-01-aaaaaa"),
    RELEASE: ("--session-id", "2026-10-01-aaaaaa", "--task", "#42"),
    REGISTER: ("--identity", "developer"),
    DECIDE: ("--slug", "state-root", "--scope", "release ordering",
             "--asked-by", "developer", "--question", "q1=Probe?",
             "--option", "q1=yes", "--option", "q1=no", "--answer", "q1=yes"),
    ORDER: ("add", "7", "--decision", "2026-10-01-absent", "--now",
            "2026-10-02T00:00:00Z"),
}


def _launch(script: Path, missing: Path, cwd: Path,
            *extra: str) -> subprocess.CompletedProcess[str]:
    """One entry point launched with --repo naming a path that is not a directory."""
    return subprocess.run(
        [sys.executable, str(script), "--repo", str(missing), *extra],
        capture_output=True, text=True, env=subprocess_env(), cwd=str(cwd),
        timeout=120,
    )


def test_each_writer_refuses_a_repo_that_is_not_a_directory_with_its_own_code(tmp_path):
    """Every writer named in §7 answers with the code §7 gives it."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    for script, expected in STATE_ROOT_REFUSAL:
        missing = tmp_path / f"no-such-root-{script.stem}"
        proc = _launch(script, missing, cwd, *ARGV[script])
        assert proc.returncode == expected, (
            f"{script.name}: docs/PRODUCT.md §7 documents exit {expected} for a "
            f"--repo that is not a directory, got {proc.returncode}: {proc.stderr}"
        )
        assert "--repo" in proc.stderr.lower() or "is not a git work tree" in proc.stderr, (
            f"{script.name}: the refusal must name the argument it refused "
            f"(decide.py names the tree, the others the flag): {proc.stderr}"
        )
        assert ("is not a directory" in proc.stderr
                or "is not a git work tree" in proc.stderr), (
            f"{script.name}: the refusal must name the state it found: {proc.stderr}"
        )
        assert not missing.exists(), f"{script.name}: the refused run created {missing}"


def test_the_unified_census_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """The census answers the same state with its own usage code (2).

    Its wording differs ("repo path does not exist") because the census takes a
    directory to audit rather than writing into one, so this asserts the code and
    that the path is named, which is what makes the refusal actionable.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    missing = tmp_path / "no-such-root-census"
    proc = _launch(CENSUS, missing, cwd)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "no-such-root-census" in proc.stderr, proc.stderr


def test_product_md_names_the_code_each_tool_owes():
    """The prose itself carries the codes, so the table above has a source.

    Read from docs/PRODUCT.md rather than restated here: a §7 that dropped a tool
    or changed a number fails this test instead of quietly disagreeing with the
    runs above.
    """
    text = (REPO / "docs" / "PRODUCT.md").read_text(encoding="utf-8")
    for code, names in DOCUMENTED.items():
        for name in names:
            assert name in text, f"docs/PRODUCT.md no longer names {name}"
        assert f"{code} for" in text, (
            f"docs/PRODUCT.md §7 must name the tools that answer exit {code} for a "
            "--repo that is not a directory"
        )
