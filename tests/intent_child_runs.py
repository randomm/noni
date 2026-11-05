"""A test's only handle on states the test process itself cannot survive.

Two of the cited record's states cannot be planted in the process that runs the
census. A path that turns into a pipe during the run hangs the process that blunders
into the blocking ``open`` -- the test's own process among them, which is why the run
happens in a child under a hard ``timeout=``: the hang fails the test instead of
stalling the suite. And a reader that keeps only the first chunk of a short
``os.read`` is a property of one function's own ``os``, not of the tree, so the seam
is put on the reader's module in a process that reports its rows and exits.

Both children run the census's own entry point over a repo the fixtures build, so the
history view, the classifier and the row factory are the run's and not hand-composed
stand-ins. The child sources are strings here because ``-c`` is the only shape that
needs no scratch file written into the tree; the two paths the package and the
fixtures live on are named on the command line for the same reason.

A helper module, never named ``test_*``, so pytest never collects it. Mirrors
``tests/intent_class_ast.py``, which exists for the same reason on the pin side.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _harness import REPO, subprocess_env

# The bound on a child that is expected to come back. Comfortably above what the
# census takes over a fixture repo, and far below a suite run: a reader that blocks
# on a pipe is killed here and the test that launched it says so.
_CHILD_TIMEOUT_SECONDS = 30

# ``-c`` puts nothing importable on sys.path, so the package and the fixture module
# are named explicitly rather than left to whatever the calling shell exported.
_CHILD_PYTHONPATH = f"{REPO / 'src'}{os.pathsep}{REPO / 'tests'}"

# The census's own invocation over a fixture repo, shared by both children: the
# runner pins the clock, and the filter keeps the report to this one class.
_CENSUS_ARGV = """sys.exit(census.main(["--repo", str(repo), "--now", "2026-10-27T12:00:00Z",
                      "--only", "intent", "--json"]))
"""

# The cited record became a fifo on the way out of the classifier call that called it
# an ordinary file. That is the interval a check-then-read cannot close, and it is the
# same seam the in-process link-swap test bends -- so both planted states are planted
# the same way, and neither depends on a race.
_SWAP_CHILD = """
import json, os, sys
from pathlib import Path
import noni.census as census
from intent_fixtures import RECORD_ID, planted_record_link
root, name = Path(sys.argv[1]), Path(sys.argv[2])
repo = planted_record_link(root, name)
record_path = repo / "noni" / "decisions" / (RECORD_ID + ".json")
fifo = root / f"{name}-fifo"
real_kind = census._file_kind
swapped = []
def classify_then_swap(path, kind="file"):
    answer = real_kind(path, kind)
    if answer[0] == "regular" and Path(path).samefile(record_path):
        swapped.append(1)
        record_path.unlink()
        os.mkfifo(fifo)
        os.link(fifo, record_path)
    return answer
census._file_kind = classify_then_swap
""" + _CENSUS_ARGV

# The reader's own ``os`` bent to answer in two chunks. The body is the superseded
# record the class calls a verdict, and half of it is not valid JSON, so a reader that
# kept only the first chunk answers ``uncited ... is not readable JSON`` where the
# whole body answers ``the record is superseded``.
_READ_CHILD = """
import json, os, sys
from pathlib import Path
import noni.census as census
import noni.census_intent as intent
from intent_fixtures import RECORD_ID, planted_record_link, record
BODY = json.dumps(record(status="superseded", supersedes="2026-09-01-beta"),
                  indent=2)
root, name, split = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
repo = planted_record_link(root, name)
record_path = repo / "noni" / "decisions" / (RECORD_ID + ".json")
record_path.write_text(BODY, encoding="utf-8")
real_read = os.read
hits, queue = [], []
def read(fd, size):
    if queue:
        return queue.pop(0)
    whole = real_read(fd, size)
    if whole:
        hits.append(1)
        if split and whole == BODY.encode("utf-8"):
            queue.append(whole[len(whole) // 2:])
            return whole[:len(whole) // 2]
    return whole
class Bent:
    O_RDONLY, O_NOFOLLOW = os.O_RDONLY, getattr(os, "O_NOFOLLOW", 0)
    O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
    fstat = staticmethod(os.fstat)
    open = staticmethod(os.open)
    close = staticmethod(os.close)
    read = staticmethod(read)
intent.os = Bent
""" + _CENSUS_ARGV


def _child(script: str, *args: str) -> list[dict]:
    """Run ``script`` as ``python -c`` in a child that cannot stall the suite.

    The child prints the census's NDJSON report and exits with its code; 0 (clean)
    and 51 (a verdict) are both answers, and anything else means the run never
    reported -- which for the fifo state is the finding, not an artefact.
    """
    proc = subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=REPO, capture_output=True, text=True,
        env=subprocess_env({**os.environ, "PYTHONPATH": _CHILD_PYTHONPATH}),
        timeout=_CHILD_TIMEOUT_SECONDS)
    assert proc.returncode in (0, 51), (
        f"the child run did not report at all (rc={proc.returncode}), so "
        f"the census blocked on a path it was never told to read: {proc.stdout}\n"
        f"{proc.stderr}")
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    findings = [row for row in rows
                if row.get("kind") == "finding" and row["check"] == "intent"]
    summary = [row for row in rows if row.get("kind") == "summary"]
    assert summary and summary[0]["counts"]["intent"] == 1, (
        f"the child run owed the intent class exactly one row: {rows}")
    return findings


def child_rows_after_fifo_swap(tmp_path: Path, name: str) -> list[dict]:
    """The intent rows of a run whose cited record became a fifo before it was read."""
    return _child(_SWAP_CHILD, str(tmp_path), name)


def child_rows_through_split_read(tmp_path: Path, name: str, *,
                                  split: bool) -> list[dict]:
    """The intent rows of a run whose cited record was read in one chunk or two."""
    return _child(_READ_CHILD, str(tmp_path), name, "1" if split else "")
