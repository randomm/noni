"""Launching the census over a hygiene fixture tree that a hang would wedge.

The census's in-process runner (``census_run._run_census``) calls ``census.main``
in the pytest worker, which is right for every state that answers and wrong for
the one state that does not: a scan that blocks on a fifo raises nothing, so the
census's ``except Exception`` cannot turn it into a row and the worker never
reports anything at all. A regression of the hygiene scan's read guard is
therefore untestable in-process, and this module is the launcher that makes it a
failing test rather than a stalled suite (the shape
``tests/test_session_walk_bounded.py`` and ``tests/intent_child_runs.py`` use).

The census writes its ``--json`` report to the process's real stdout, so it
cannot be captured into a pipe the parent reads -- the child writes the report
to a file instead and the parent reads that back. The child's own stdout carries
only ``ROW::`` and ``RC::`` markers, which lets the parent tell "no rows" from
"no output yet".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# Twenty times what a scan of a handful of small files actually costs (tens of
# milliseconds). A run that reached this bound had hung, and the subprocess's
# own timeout is what stops it; the elapsed value the caller asserts on is what
# says the scan returned rather than merely that the child died in time.
BOUND_SECONDS = 20

# The committed files every hygiene fixture tree carries before the pipes are
# planted: a ledger record so the tree is a noni/ tree, and three regular files,
# one of which becomes the tracked pipe.
_LEDGER = "noni/decisions/2026-10-01-alpha.json"
_PLAIN = "plain.md"
_TRIVIAL = (("README.md", "# clean\n"), ("config.json", '{"mode": "default"}\n'),
            (_PLAIN, "a clean line\n"))

# The deny-list entry the fixture activates the class with, and the word in the
# violation planted beside the pipe. One pair, so the launcher's control (a
# regular tracked file whose finding must still be reported) and the entry that
# catches it cannot drift apart.
_DENYLIST_ENTRY = "synthetic-fixture-name"
_VIOLATION_BODY = f"ported from {_DENYLIST_ENTRY}\n"


def fifo_tree_census_run(tmp_path: Path, name: str = "fifo-tree",
                         ) -> tuple[int, list[dict], float]:
    """The census over a tree holding a tracked fifo and an untracked one, bounded.

    Returns ``(exit_code, rows, elapsed)`` where ``rows`` are the run's NDJSON
    rows. A hang fails on the subprocess timeout; a child that died rather than
    answered fails the returncode assertion, because a scan that could not run
    and a scan that was never launched are the two states this launcher exists to
    distinguish from a scan that answered.

    ``tree_dir(tmp_path, name)`` is the repo the child built, so a caller that
    wants the filesystem's answer (is the pipe still a pipe?) reads the same tree
    the census scanned rather than guessing at the child's layout.
    """
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    report = root / "report.ndjson"
    script = _child_script(str(root), name, str(report))
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
                          text=True, timeout=BOUND_SECONDS)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, (
        f"the census did not answer (rc={proc.returncode}):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    rc_lines = [line for line in proc.stdout.splitlines() if line.startswith("RC::")]
    assert rc_lines, f"the census printed no exit code: {proc.stdout!r}"
    assert report.is_file(), f"the census wrote no report: {proc.stdout!r}"
    rows = [json.loads(line) for line in
            report.read_text(encoding="utf-8").splitlines() if line.strip()]
    return int(rc_lines[0][len("RC::"):]), rows, elapsed


def tree_dir(tmp_path: Path, name: str = "fifo-tree") -> Path:
    """The repository the child built under ``tmp_path/name``."""
    return tmp_path / name / name


def _child_script(root: str, name: str, report: str) -> str:
    """The ``python -c`` body: build the tree, plant the pipes, run the census.

    The child imports the same harness the in-process tests import, so the tree
    has one builder and two launch routes rather than a fixture and a copy of it
    that could drift.
    """
    commits = "\n".join(f"_commit_file(repo, {rel!r}, {body!r})"
                        for rel, body in _TRIVIAL)
    return "\n".join((
        "import json, os, sys",
        "from pathlib import Path",
        f"sys.path[:0] = [{str(Path(__file__).resolve().parent)!r}, "
        f"{str(Path(__file__).resolve().parent.parent / 'src')!r}]",
        "import harness_module  # noqa: F401  (src/ on sys.path, package aliases)",
        "from _harness import _commit_file, _init_repo, _plant_fifo, _plant_untracked_fifo",
        "from census_fixtures import _valid_record",
        "import census",
        f"root, name = Path({root!r}), {name!r}",
        "repo = _init_repo(root / name)",
        f"_commit_file(repo, {_LEDGER!r}, json.dumps(_valid_record(), indent=2))",
        # The violation beside the pipe: the control that says the scan ran.
        f"_commit_file(repo, 'note.md', {_VIOLATION_BODY!r})",
        commits,
        # The tracked pipe: commit-then-swap, since git cannot stage one.
        f"_plant_fifo(repo, {_PLAIN!r})",
        # The untracked one, which the listing keeps off the scan altogether.
        "_plant_untracked_fifo(repo, 'stray.fifo')",
        # The deny-list class active, so the scan's own rows are the only rows.
        f"_dl = root / 'hygiene-denylist.txt'; _dl.write_text({_DENYLIST_ENTRY!r} + '\\n')",
        "os.environ['NONI_SCRUB_DENYLIST'] = str(_dl)",
        f"_report = Path({report!r})",
        "_out = sys.stdout",
        "sys.stdout = _report.open('w', encoding='utf-8')",
        "try:",
        "    _rc = census.main(['--repo', str(repo), '--json', '--only', 'hygiene'])",
        "finally:",
        "    sys.stdout.close(); sys.stdout = _out",
        "print('RC::%d' % _rc)",
    ))
