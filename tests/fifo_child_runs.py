"""Bounded child-process runners for the issue #91 FIFO tests.

The bug was a hang, so no test for it may run the faulting call in-process: an
unbounded read of a named pipe takes the pytest worker with it and reports nothing
at all, which is the product's failure mode one layer up. Every scan, read and
deny-list load that could block therefore runs in a child under
``subprocess.run(timeout=...)`` plus an elapsed assertion -- the bounded-child
shape this suite reuses wherever a read could block. Each runner prints its verdict on a
marker line so the parent can tell "no violations" from "no answer": the second is
the hang, and it is the finding, not an artefact.

Split out of ``tests/test_public_safety_fifo.py`` along that seam (the child-runners
versus the verdicts) to stay under the 500-line source cap; the mutation checks that
matter -- a dropped ``O_NONBLOCK`` or ``S_ISREG`` -- are unchanged by it, since they
turn on the behaviour these return, not on where the runner is defined.

A helper module, never named ``test_*``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import public_safety

# A second's worth of margin over what a skipped path actually costs
# (sub-millisecond), so a regression that hangs fails the test in seconds instead
# of inheriting the suite's absence of any timeout at all (there is no
# pytest-timeout in this project).
BOUND_SECONDS = 15


def _src_dir() -> str:
    """The ``src/`` the child imports the package from.

    Derived from the imported module rather than a path the caller builds, so a
    child cannot be handed a copy of the checker no scan runs.
    """
    return str(Path(public_safety.__file__).resolve().parent.parent)


def _run(script: str, marker: str, what: str) -> str:
    """One child under the bound, returning the payload of its ``marker`` line.

    A non-zero exit means the call raised rather than hung -- a different
    regression than the one these tests exist for, so it is reported with the
    child's stderr rather than retried.
    """
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True, timeout=BOUND_SECONDS)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"{what} faulted: {proc.stderr}"
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(marker)), "")
    assert line, f"{what} returned no verdict: {proc.stdout!r} {proc.stderr!r}"
    # Reaching the bound would have tripped the timeout above, so this is the
    # assertion that says the call finished on its own, promptly.
    assert elapsed < BOUND_SECONDS, f"{what} took {elapsed:.1f}s"
    return line[len(marker):]


def scrub_in_time(repo: Path) -> list[str]:
    """``scrub_tracked_files`` over ``repo`` in a child, or a failure if it stalled."""
    script = (
        "import json, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "found, _source, _dl, _al = public_safety.scrub_tracked_files(Path({repo!r}))\n"
        "print('FOUND::' + json.dumps(found))\n"
    ).format(src=_src_dir(), repo=str(repo))
    return json.loads(_run(script, "FOUND::", "the scan"))


def read_in_time(path: Path) -> object:
    """``_read_text_lenient`` on ``path`` in a child, or a failure if it stalled."""
    script = (
        "import json, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "value = public_safety._read_text_lenient(Path({path!r}))\n"
        "print('KIND::' + json.dumps(value))\n"
    ).format(src=_src_dir(), path=str(path))
    return json.loads(_run(script, "KIND::", "the read"))


def scan_with_short_reads(repo: Path) -> list[str]:
    """The scan over ``repo`` with ``os.read`` bent to one byte per call.

    One byte per call is the most a short read can cut a body down to, so a reader
    that kept only the first call's worth reports a clean tree.
    """
    script = (
        "import json, os, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "real = os.read\n"
        "def bent(fd, size):\n"
        "    return real(fd, 1)\n"
        "public_safety.os.read = bent\n"
        "found, _s, _d, _a = public_safety.scrub_tracked_files(Path({repo!r}))\n"
        "public_safety.os.read = real\n"
        "print('FOUND::' + json.dumps(found))\n"
    ).format(src=_src_dir(), repo=str(repo))
    return json.loads(_run(script, "FOUND::", "the bent scan"))


def run_bent_scan(repo: Path, bends: str) -> list:
    """The scan over ``repo`` with the ``os`` calls in ``bends`` replaced.

    ``bends`` is child source defining the replacements (``read``, ``close``, an
    ``open`` wrapper) and a ``payload()`` returning the JSON of what the run should
    report -- a function, because the payload reads locals that only exist once the
    call has run. Bending in a child keeps a fault seam out of the next test.
    """
    script = (
        "import json, os, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        + bends +
        "found, _s, _d, _a = public_safety.scrub_tracked_files(Path({repo!r}))\n"
        "print('FOUND::' + payload())\n"
    ).format(src=_src_dir(), repo=str(repo))
    return json.loads(_run(script, "FOUND::", "the bent scan"))


def load_denylist_in_time(repo: Path, *, default: Path | None,
                          env: str | None) -> dict:
    """``load_denylist`` in a child under the bound, with the seams it needs.

    The default-path seam is patched in the child because a pipe there hangs the
    parent's own import path the same way; the env var is handed over as a value.
    """
    script = (
        "import json, os, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "public_safety._default_denylist_file = lambda repo: Path({default!r})\n"
        "{envset}"
        "result = public_safety.load_denylist(Path({repo!r}))\n"
        "print('DL::' + json.dumps([result.entries, result.source, result.status]))\n"
    ).format(
        src=_src_dir(),
        default=str(default) if default else None,
        envset=((f"os.environ[public_safety.DENYLIST_ENV_VAR] = {env!r}\n"
                 if env else "os.environ.pop(public_safety.DENYLIST_ENV_VAR, None)\n")),
        repo=str(repo),
    )
    entries, source, status = json.loads(_run(script, "DL::", "the deny-list read"))
    return {"entries": entries, "source": source, "status": status}


def read_lenient_bent(path: Path, bends: str, marker: str = "KIND::") -> list:
    """``_read_text_lenient`` on ``path`` with the ``os`` calls in ``bends`` bent.

    ``bends`` is child source defining the replacements (``fstat``, ``close``) and a
    ``payload()`` returning the JSON the run should report, which reads the ``value``
    the call assigns. For the states no filesystem can produce -- an ``fstat`` that
    faults, a descriptor revoked underneath the scan -- bent in a child so the seam
    cannot leak into the next test.
    """
    script = (
        "import json, os, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        + bends +
        "value = public_safety._read_text_lenient(Path({path!r}))\n"
        "print('KIND::' + payload())\n"
    ).format(src=_src_dir(), path=str(path))
    return json.loads(_run(script, marker, "the bent read"))
