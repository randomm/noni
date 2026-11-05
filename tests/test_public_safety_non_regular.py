"""The hygiene scan's non-regular-path guard (issue #91).

A fifo is the one tracked path that turns the scan into a process that never
returns: a plain ``open`` of a pipe with no writer blocks forever and raises
nothing, so neither ``public_safety``'s own ``except`` nor the census's
``except Exception`` can report it. Every case here plants one and asserts
behaviour under a subprocess bound, because a regression is a hang and an
in-process hang takes the pytest worker with it.

Split out of ``tests/test_public_safety.py`` for the size rule (AGENTS.md,
Source file size): the scrub's own pattern and deny-list cases stay there, and
this file owns the guard that keeps the scan off a path it cannot read.

The two structural pins at the end exist because no fixture can plant the swap
between a separate classification and the open, which is the interval the
same-descriptor check exists to close. The census-level case is in
``tests/test_census_hygiene.py`` and the gate-CLI case in
``tests/test_quickstart.py``.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The package module is the only importable home of the checker; the bare alias
# is registered by _harness from the same package object.
import public_safety  # noqa: E402
from _harness import (  # noqa: E402
    _git,
    _home_path_violation,
    _plant_fifo,
    _plant_fifo_link,
    _plant_untracked_fifo,
)
from test_public_safety import _clean_repo  # noqa: E402

# A refusal costs milliseconds; this is seconds of margin over that, and it is
# the bound the subprocess's own timeout enforces.
BOUND_SECONDS = 5

# Planted violations are built from public_safety's own tables, never written as
# literals: this file is tracked and is not one of the exempted self files.
_HOME_PATH = _home_path_violation()

# The FIFO cases need os.mkfifo, which is POSIX only.
needs_mkfifo = pytest.mark.skipif(not hasattr(os, "mkfifo"),
                                  reason="os.mkfifo is not available on this host")


@pytest.fixture
def clean_repo(tmp_path, monkeypatch):
    """The clean tree both scrub suites share (``test_public_safety._clean_repo``)."""
    return _clean_repo(tmp_path, monkeypatch)


def _scan_in_child(repo: Path, extra: dict[str, str] | None = None):
    """``scrub_tracked_files(repo)`` in a child that cannot stall the suite.

    A regression here is a hang, and an in-process hang takes the pytest worker
    with it, so the call is launched and bounded (the shape
    tests/test_session_walk_bounded.py uses). Returns the violation lines and the
    elapsed seconds; the elapsed assertion is what says the scan returned rather
    than merely that the child died in time.
    """
    script = "\n".join((
        "import sys",
        "sys.path.insert(0, {src!r})",
        "from pathlib import Path",
        "from noni import public_safety",
        "_v, _s, _d = public_safety.scrub_tracked_files(Path({repo!r}))",
        "for _line in _v:",
        "    print('VIOLATION::' + _line)",
    )).format(src=str(REPO / "src"), repo=str(repo))
    env = dict(os.environ)
    env.pop(public_safety.DENYLIST_ENV_VAR, None)
    env.update(extra or {})
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
                          text=True, timeout=BOUND_SECONDS, env=env)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"the scan crashed: {proc.stderr}"
    assert elapsed < BOUND_SECONDS, f"the scan took {elapsed:.1f}s"
    return [line[len("VIOLATION::"):] for line in proc.stdout.splitlines()
            if line.startswith("VIOLATION::")]


@needs_mkfifo
def test_scrub_skips_a_tracked_fifo_without_reading_or_hanging(clean_repo):
    """A tracked fifo is skipped, reported, and never read (AC1, AC2).

    The fixture commits a regular file, unlinks it and mkfifos the same path:
    git cannot stage a pipe, so a fixture that staged one would scan an ordinary
    file and pass for the wrong reason. The scan must return in bounded time,
    emit no violation for the pipe, and say that it skipped a path it did not
    read -- a fifo opened O_NONBLOCK alone reads as EOF, which would be a false
    clean rather than a skip.
    """
    (clean_repo / "plain.md").write_text("clean text\n", encoding="utf-8")
    _git(clean_repo, "add", "plain.md")
    _git(clean_repo, "commit", "-q", "-m", "tracked plain")
    _plant_fifo(clean_repo, "plain.md")

    violations = _scan_in_child(clean_repo)
    assert not any(v.startswith("plain.md") for v in violations), (
        f"the scan read a fifo and called it clean: {violations}")
    assert any(v.startswith(public_safety.NONI_SKIP_NOTE_MARKER) for v in violations), (
        f"a path the scan refused to open was reported as clean: {violations}")


@needs_mkfifo
def test_scrub_reports_a_violation_beside_a_fifo(clean_repo):
    """The guard does not blind the scan: a violation in a regular file beside a
    pipe is still reported, with its path, line and label.

    Without this control the skip case above could pass because the scan gave up
    on the whole tree.
    """
    (clean_repo / "note.md").write_text(_HOME_PATH + "\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant path")
    _plant_fifo(clean_repo, "README.md")

    violations = _scan_in_child(clean_repo)
    assert any(v.startswith("note.md:1:") and "home path" in v for v in violations), (
        f"a violation beside a fifo was lost: {violations}")


@needs_mkfifo
def test_an_untracked_fifo_is_never_listed_and_never_scanned(clean_repo):
    """The untracked control: git ls-files omits it, so it never reaches the scan.

    The criterion's "tracked or untracked" half is only falsifiable through the
    listing -- no guard is what keeps the scan off an untracked path. So this
    asserts the listing, and pairs it with a violation in a regular tracked file
    that must still be reported, which is what proves the scan ran at all.
    """
    (clean_repo / "note.md").write_text(_HOME_PATH + "\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant path")
    _plant_untracked_fifo(clean_repo, "stray.fifo")

    listed = _git(clean_repo, "ls-files").stdout.split()
    assert "stray.fifo" not in listed, f"git listed an untracked pipe: {listed}"
    violations = _scan_in_child(clean_repo)
    assert any(v.startswith("note.md:1:") for v in violations), (
        f"the scan did not run against the regular files: {violations}")
    assert not any(public_safety.NONI_SKIP_NOTE_MARKER in v for v in violations), (
        f"an untracked pipe reached the scan's skip report: {violations}")


@needs_mkfifo
def test_a_tracked_symlink_to_a_fifo_is_skipped_not_followed(clean_repo):
    """A link to a pipe is refused by the descriptor check, not followed into a
    read that blocks (AC2).

    A pre-open lstat of the top-level path alone does not cover this: the link
    is neither regular nor a pipe, and following it is exactly what the guard
    must prevent.
    """
    _plant_fifo_link(clean_repo, "linked.md")
    _git(clean_repo, "add", "linked.md")
    _git(clean_repo, "commit", "-q", "-m", "tracked link to a pipe")

    violations = _scan_in_child(clean_repo)
    assert not any(v.startswith("linked.md") for v in violations), (
        f"a link to a fifo was read as a file: {violations}")
    assert any(v.startswith(public_safety.NONI_SKIP_NOTE_MARKER) for v in violations), (
        f"a path the scan refused to open was reported as clean: {violations}")


@needs_mkfifo
def test_a_fifo_at_the_denylist_path_does_not_hang_the_scan(clean_repo, tmp_path):
    """The deny-list read carries the same guard: is_file() is not one.

    ``Path.is_file()`` follows links and answers True for a fifo, so a deny-list
    path that holds a pipe blocked the scan before the tracked loop ever began.
    The candidate is then treated like one that was never there: the class
    reports itself inactive rather than hanging.
    """
    denylist = tmp_path / "denylist.fifo"
    os.mkfifo(denylist)
    _plant_untracked_fifo(clean_repo, "stray2.fifo")  # keeps tmp_path cleanup honest

    script = "\n".join((
        "import sys",
        "sys.path.insert(0, {src!r})",
        "from pathlib import Path",
        "from noni import public_safety",
        "_r = public_safety.load_denylist(Path({repo!r}))",
        "print('STATUS::' + _r.status)",
    )).format(src=str(REPO / "src"), repo=str(clean_repo))
    env = dict(os.environ)
    env[public_safety.DENYLIST_ENV_VAR] = str(denylist)
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
                          text=True, timeout=BOUND_SECONDS, env=env)
    assert proc.returncode == 0, f"load_denylist crashed: {proc.stderr}"
    assert proc.stdout.strip() == "STATUS::absent", (
        f"a fifo deny-list was not treated as absent: {proc.stdout!r}")
    assert time.monotonic() - started < BOUND_SECONDS


def test_the_guard_opens_nonblocking_and_checks_the_same_descriptor():
    """The two flags and the ordering are pinned at the syntax tree.

    No fixture can plant the swap between a separate classification and the
    open, which is the interval the same-descriptor check exists to close, and
    an fcntl after the open is too late -- the open itself is what blocks on a
    pipe. So the shape is read off the tree: opening before inspecting, and
    both the non-blocking flag and the regular-file test present. Mirrors
    tests/test_census_intent_record_reader.py.
    """
    text = (REPO / "src" / "noni" / "public_safety.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    body = next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "open_regular"),
                None)
    assert body, "public_safety no longer defines open_regular"
    lines = {name: min(node.lineno for node in ast.walk(body)
                       if isinstance(node, ast.Call)
                       and getattr(node.func, "attr", node.func.id if hasattr(node.func, "id") else None) == name)
             for name in ("open", "fstat")}
    assert lines["open"] < lines["fstat"], (
        "the guard no longer inspects the descriptor it opened, so a path that "
        "became a pipe after the classification is read")
    source = ast.get_source_segment(text, body)
    assert source, "open_regular has no readable source segment"
    # The flags are read from the expressions the function evaluates, not from
    # its prose: the docstring names O_NOFOLLOW to say it is deliberately
    # absent, and a sentence about intent must not satisfy (or veto) a pin about
    # the code.
    names = {node.attr for node in ast.walk(body) if isinstance(node, ast.Attribute)}
    # The flags reach the open as ``getattr(os, "O_NONBLOCK", 0)``, so their
    # names are string arguments too. Reading the flags out of every expression
    # the function evaluates (rather than out of the function's prose) is what
    # makes this a pin about the code: the docstring names O_NOFOLLOW to say it
    # is deliberately absent, and a sentence about intent must not satisfy a pin
    # about a flag -- nor veto one.
    literals = {node.value for node in ast.walk(body)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    flags = names | literals
    assert "O_NONBLOCK" in flags, (
        "the guard no longer opens O_NONBLOCK, so a tracked fifo blocks the scan forever")
    assert "S_ISREG" in flags, (
        "the guard no longer tests S_ISREG, so a fifo opens and reads as an empty "
        "file: a false clean instead of a reported skip")
    assert "O_NOFOLLOW" not in flags, (
        "the guard gained O_NOFOLLOW, which drops a tracked symlink to a regular "
        "file instead of scanning it")
