"""Injected readdir faults and synthetic hygiene fixtures for the harness.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every ``from _harness import`` keeps resolving.
A helper module: never named ``test_*``. Its product imports are function-local
(``import census`` inside the guard and its three installers): a module-level
product import here would be a cycle back through the ``_harness`` facade into
this file, which is loaded before ``harness_module`` finishes.

"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from harness_git import _git
from harness_module import HOME_PATH_PATTERNS, SECRET_PATTERNS

# --- Injected ledger-listing faults -------------------------------------------
#
# One builder for both groups' faulted readdirs. The seam is the census's own
# ``Path.iterdir`` and never a mode bit: a root-equivalent runner reads a
# 000-mode directory, so a chmod fixture would read as listable and the test
# would pass vacuously. It is never ``Path.glob`` either -- ``glob`` swallows
# the ``OSError`` a readdir raises and yields nothing, which is the very
# dishonesty the census no longer has, so patching it would fault nothing at all.


def _permission_fault_guard(target: Path, *, text: str = "input/output error",
                            filename: str | None = None):
    """The ``Path.iterdir`` replacement that faults one directory's readdir.

    The census is imported only inside this function and the three installers
    below, never at module level: a module-level product import here would be a
    cycle through the facade back into this file.

    The guard on the receiver keeps every other listing of the run honest, so
    only the named directory's readdir faults. The exception is built inside the
    guard, so each raise hands the census a fresh ``OSError`` and nothing a
    handler does to it can leak into a later raise.

    With ``filename`` the fault is the errno-pair form that puts the words in
    ``strerror`` and the path it failed on in ``filename``, so ``str()`` holds
    both and a row built from it must print one of them and not the other; that
    is the shape the row's path-leak rule is tested against. Without it the
    fault is a plain ``OSError(text)``, whose ``str()`` is the words alone.

    Returns the replacement; the callers below install it, and a test that needs
    to install it itself (to fault a path the census does not reach by default)
    gets the same builder. In-process callers only -- a subprocess would not see
    the patch.
    """
    import census

    target = Path(target)
    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == target:
            raise (OSError(13, text, filename) if filename is not None
                   else OSError(text))
        return real_iterdir(self)

    return boom


def _fault_the_ledger_listing(monkeypatch, ledger: Path) -> None:
    """Fault the census's listing of ``ledger`` for an in-process run.

    One install over :func:`_permission_fault_guard`, so the ledger and sessions
    sides of the seam are the same fixture and cannot drift into two conventions
    for it (see the block comment for why the seam is ``iterdir``).
    """
    import census

    monkeypatch.setattr(census.Path, "iterdir",
                        _permission_fault_guard(ledger, text="readdir denied"))


def _fault_the_sessions_listing(monkeypatch, sessions: Path,
                                text: str = "input/output error") -> None:
    """Fault the census's listing of ``sessions`` for an in-process run.

    The sessions-side twin of :func:`_fault_the_ledger_listing`: same builder,
    same seam, same in-process-only caveat. ``text`` defaults to the slash-free
    errno words an unmounted device reports, so a test can quote the fault back
    out of the row unchanged -- the scrubber replaces every ``/segment`` run with
    its marker, and a message carrying a separator could not be.
    """
    import census

    monkeypatch.setattr(census.Path, "iterdir",
                        _permission_fault_guard(sessions, text=text))


def _permission_fault_on(sessions: Path, leaked: str):
    """The installable fixture of a fault that carries a path in ``filename``.

    Thin over :func:`_permission_fault_guard`, and named for what it tests: the
    one shape that carries both halves of the row's rule in a single exception,
    so the row must print the words and not the path. Returns the replacement for
    the caller to install with ``monkeypatch.setattr(census.Path, "iterdir", ...)``.
    """
    return _permission_fault_guard(sessions,
                                   text="Permission denied - input/output error",
                                   filename=leaked)


# --- Synthetic hygiene fixtures ------------------------------------------------
#
# One home for the violation strings the census hygiene tests plant. They are
# built from public_safety's OWN pattern components rather than written out:
# a copy-pasted literal silently stops matching the moment a pattern is added
# or reworded, and a fixture that no longer trips the scanner makes the tests
# that depend on it pass for the wrong reason (the same reason
# tests/test_skill_scrub.py and tests/test_purity.py build their fixtures from
# the imported tables).
#
# They must not appear as literals either: these files are git-tracked, and the
# census's own hygiene class — and tests/test_public_safety.py's repo-clean
# check — flag a literal /home/<known identity> path or token shape in a
# Tracked-file literals that would trip the census's own hygiene class (and
# tests/test_public_safety.py's repo-clean check) are never written as literals:
# only the three self files are exempted (src/noni/public_safety.py,
# scripts/public_safety.py and tests/test_public_safety.py), hence the runtime
# assembly.

_HOME_PATH_KNOWN_IDENTITY = "admin"
_SECRET_TOKEN_PREFIX = "ghp_"


def _home_path_violation() -> str:
    """A machine-local home path that HOME_PATH_PATTERNS matches: built from
    the same identity list the pattern itself interpolates."""
    _patterns, label = HOME_PATH_PATTERNS[1]
    assert label.startswith("machine-local absolute home path (/home/"), (
        f"HOME_PATH_PATTERNS[1] is no longer the /home/<known identity> pattern: {label}"
    )
    return f"/home/{_HOME_PATH_KNOWN_IDENTITY}/.ssh/id_ed25519"


def _secret_violation() -> str:
    """A token that SECRET_PATTERNS matches, assembled from the pattern's own
    prefix so a prefix change here cannot quietly un-pin the fixture."""
    prefix = _SECRET_TOKEN_PREFIX
    assert any(p.pattern.startswith("\\b" + prefix) for p, _l in SECRET_PATTERNS), (
        f"{prefix!r} is no longer a SECRET_PATTERNS prefix"
    )
    return prefix + "synthsynth" * 3


# --- The planted FIFO ---------------------------------------------------------
#
# The one fixture that puts a named pipe where a scan expects a file, and its
# sibling for a regular file the scan may not open. The scrub, the census-level
# and the gate-CLI FIFO tests all plant the pipe through this builder: three
# copies of the recipe drift, and the usual drift is the one that quietly
# stops producing a tracked pipe (see ``_plant_fifo``) so the test scans an
# ordinary file and passes green while the hang is still in the product.


def _mkfifo_available() -> bool:
    """Whether this host can create a named pipe at all (the skipif condition).

    ``os.mkfifo`` is POSIX-only, so on a non-POSIX host the FIFO tests skip rather
    than error; the repo's offline-determinism rule is the reason a bare skip is
    enough here, and CI is Linux-only. Probing the attribute rather than the
    platform name because the question the tests actually ask is this one."""
    return hasattr(os, "mkfifo")


def _plant_fifo(repo: Path, rel: str, *, content: str = "placeholder\n") -> Path:
    """Commit ``repo/rel`` as an ordinary file, then swap it for a named pipe.

    The commit-then-swap is the only recipe that yields a TRACKED pipe. ``git add``
    on a fresh pipe exits 0 and never lists the path -- git has no index mode for
    one -- so a fixture that mkfifo's first and adds second leaves git blind to the
    path and the scan never reaches it: the test would pass with the hang in place.
    Committing a regular file first puts the path in ``git ls-files``, and the
    ``os.mkfifo`` on the same path afterwards is the stray pipe a real work tree
    can hold, which is the state that blocked the scan of #91 in ``read_text``.

    No writer is started and none is needed: an unbounded ``open`` of a pipe with
    no writer is what never returns, which is the hang itself. Unlinking a FIFO is
    safe, so ``tmp_path`` cleanup never blocks either.

    Returns the path, so a caller can assert it is still a pipe on disk after the
    scan (a scan that consumed it would be a scan that read it).
    """
    if not _mkfifo_available():  # pragma: no cover - non-POSIX host only
        raise RuntimeError("this host cannot create a named pipe")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "-m", f"track {rel} as a regular file")
    assert rel in _git_ls_files(repo), (
        f"the fixture's {rel} is not tracked, so the scan would never reach the "
        "planted pipe and the test would prove nothing"
    )
    target.unlink()
    os.mkfifo(target)
    assert not target.is_file(), f"{rel} is not a named pipe: a fixture that plants " \
        "nothing leaves the FIFO tests scanning an ordinary file"
    return target


def _plant_unreadable_tracked_file(repo: Path, rel: str, *,
                                   content: str = "placeholder\n") -> Path:
    """Commit ``repo/rel`` as an ordinary file, then revoke every permission on it.

    The sibling of :func:`_plant_fifo` for the other fault a scan meets at a
    tracked path: a regular file the scan may not open (EACCES), which #91 made a
    silent skip. The commit-then-chmod recipe mirrors the pipe's because the
    assertion is the same one -- git must still list the path, or the scan never
    reaches the fault and the test reports a clean tree it never looked at.

    Skips when the host's euid can read anything: root ignores the mode bits, so
    the 000 file would open and the test would assert nothing about unreadability.
    The skip is the repo's standing answer for a fixture a host cannot plant.

    The mode is restored before the skip returns, so ``tmp_path`` cleanup on a
    root-equivalent host never meets a path it cannot remove.

    Returns the path, so a caller can assert the violation row names it.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "-m", f"track {rel} as a regular file")
    assert rel in _git_ls_files(repo), (
        f"the fixture's {rel} is not tracked, so the scan would never reach the "
        "sealed file and the test would prove nothing"
    )
    target.chmod(0o000)
    if os.access(target, os.R_OK):
        target.chmod(0o644)
        pytest.skip("root reads anything, so the 000-mode file cannot be planted")
    return target


def _plant_untracked_fifo(repo: Path, rel: str) -> Path:
    """A named pipe in the working tree that git has never been told about.

    The control for the tracked case: ``git ls-files`` lists index entries only, so
    the scan must never reach this path at all -- it is the listing, not the guard,
    that keeps the scan off it. A test asserts the absence here and the skip on the
    tracked one, or an untracked pipe proves nothing about either.
    """
    if not _mkfifo_available():  # pragma: no cover - non-POSIX host only
        raise RuntimeError("this host cannot create a named pipe")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(target)
    assert rel not in _git_ls_files(repo), (
        f"git lists the untracked {rel}, so the control case is not the control"
    )
    return target


def _plant_fifo_symlink(repo: Path, rel: str, target_rel: str) -> Path:
    """Commit ``repo/rel`` as a regular file, then link it to the pipe at ``target_rel``.

    The case a top-level ``lstat`` pre-check cannot cover: ``lstat`` of the link
    answers ``S_ISLNK`` and a pre-open regular check skips the path, while the
    scan's own ``read_text`` follows the link and blocks on the pipe. Only the
    ``S_ISREG`` check on the descriptor the scan opened refuses it, so this is the
    fixture that separates the two designs AC2 offers.
    """
    if not _mkfifo_available():  # pragma: no cover - non-POSIX host only
        raise RuntimeError("this host cannot create a named pipe")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("placeholder\n", encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "-m", f"track {rel} as a regular file")
    target.unlink()
    target.symlink_to(Path(target_rel).name if "/" not in target_rel else Path(target_rel))
    assert rel in _git_ls_files(repo), f"the link {rel} is not tracked"
    return target


def _git_ls_files(repo: Path) -> list[str]:
    """``git ls-files`` as a list, for the fixture's own precondition assertions."""
    return _git(repo, "ls-files").stdout.split()


# --- Leaked-descriptor probes -------------------------------------------------
#
# The other half of the FIFO bug: a guard that refuses a pipe but never closes the
# descriptor it opened leaks one fd per odd path, and the census scans in-process,
# so a tree of pipes exhausts the descriptor table. No filesystem state shows this
# and no behavioural assertion can: the scan still returns promptly and still
# reports nothing, so the tests that bound the hang all pass with the leak in
# place. What catches it is counting the descriptors the process holds across the
# call, which is the whole point of the pair below.


def _open_fd_count() -> int:
    """How many descriptors this process currently holds.

    ``/proc/self/fd`` rather than a bookkeeping list a bent ``os.close`` fills in:
    the seam tests append to a list before delegating, so a never-called
    ``os.close`` and a swallowed ``os.close(-1)`` both look like correct closure to
    them. The kernel's own table cannot be bent that way.

    ``/proc/self/fd`` is Linux-only, so a host without it raises ``_NoFdTable``
    rather than counting: ``os.mkfifo`` exists on macOS, and a bare ``listdir``
    there would turn the descriptor tests into a ``FileNotFoundError`` instead of
    a skip. The sentinel is defined below, where its one reader lives.
    """
    entries = Path("/proc/self/fd")
    if not entries.is_dir():  # pragma: no cover - non-Linux host only
        raise _NoFdTable("no /proc/self/fd on this host")
    return len(os.listdir(entries))


class _NoFdTable(RuntimeError):
    """This host has no ``/proc/self/fd``, so no descriptor count exists."""


def _leaked_fds_across(callable_, *args) -> int:
    """Descriptors ``callable_(*args)`` leaves open in this process.

    Positive means a leak; zero means the call gave back every descriptor it took.
    The count is the difference rather than an absolute so the baseline a warm
    interpreter happens to hold cannot move the verdict, and a leak of one fd per
    planted pipe is what the FIFO tests assert against a known pipe count.

    Skips where the kernel's table is absent: the caller's only platform guard is
    ``_mkfifo_available``, which is true on hosts that lack ``/proc/self/fd``. Both
    counts are taken under the same guard, so a table that vanished mid-call skips
    rather than raising past an already-passing scan.
    """
    try:
        before = _open_fd_count()
        callable_(*args)
        return _open_fd_count() - before
    except _NoFdTable:  # pragma: no cover - non-Linux host only
        pytest.skip("no /proc/self/fd on this host, so descriptors cannot be counted")
