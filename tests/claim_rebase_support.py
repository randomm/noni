"""The scripted git seam the claim push-rebase suite drives.

``claim.py`` runs every git call of the push loop through its own ``_git``, so a
test of a rebase verdict replaces that one name and answers each verb: the
fetch, the push, the rebase and the state probes each get their own scripted
answer, and a call the script does not name runs for real against the fixture
tree (a double that answered everything would pass while measuring nothing).

The helpers here build those answers; they live beside the suite that reads
them so the scripted shapes stay with the verdicts they drive.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _push_result(args: list[str], returncode: int = 0,
                 stdout: str = "",
                 stderr: str = "") -> subprocess.CompletedProcess[str]:
    """One scripted git answer in claim.py's own call shape.

    A fake that returns 1 for everything exits 3 on the fetch and tests nothing,
    so each verb gets the answer the verdict under test needs: 0 for the fetch,
    1 for the push (a rejection, which is what enters the retry path), the
    timeout sentinel for a killed rebase.
    """
    return subprocess.CompletedProcess(["git"] + args, returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _stopped_rebase_git(tmp_path: Path, shape: object,
                        calls: list[list[str]]) -> object:
    """A seam where the rebase answers ``shape`` and the clone is stopped mid-rebase.

    ``shape`` is the returncode the rebase carries: an int answers a measured
    call, ``None`` the shape of a call that was launched and never waited on, a
    str the sentinel that never parsed as an int. The state probe prints a
    well-formed ``rebase-merge`` directory (both files non-empty, the positive
    evidence a stopped rebase leaves), so the verdict's only path is to read the
    state, abort, and classify -- which is what distinguishes 'killed' from
    'refused' in the codes claim.py publishes.
    """
    state = tmp_path / f"stopped-{shape}"

    def fake_git(args: list[str], cwd: Path,
                 calls: list[list[str]] = calls) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["rev-parse", "--git-path"]:
            if args[2] == "rebase-merge":
                (state / "rebase-merge").mkdir(parents=True, exist_ok=True)
                (state / "rebase-merge" / "head-name").write_text(
                    "refs/heads/main\n", encoding="utf-8")
                (state / "rebase-merge" / "onto").write_text(
                    "0" * 40 + "\n", encoding="utf-8")
                return _push_result(args, 0, str(state / "rebase-merge") + "/")
            return _push_result(args, 0, str(state / args[2]) + "/")
        if args[:2] == ["rebase", "--abort"]:
            return _push_result(args)
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        if args[0] == "rebase":
            # The never-measured call, in the shape under test.
            return subprocess.CompletedProcess(["git"] + args, shape, "", "")
        return _push_result(args, 1)

    return fake_git
