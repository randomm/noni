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

# --- The planted non-regular paths ---------------------------------------------
#
# A fifo is the one path shape that turns the hygiene scan into a process that
# never returns: a plain ``open`` of a pipe with no writer blocks forever and
# raises nothing, so no handler downstream can report it (issue #91). Every FIFO
# case in the suite plants one of these three ways and runs under a bound.
#
# The swap is the ONLY way a TRACKED path can hold a pipe. ``git add`` of a fifo
# exits 0 and then never lists the path -- git indexes blobs, not pipes -- so a
# fixture that staged one would scan an ordinary file and pass for the wrong
# reason. Committing a regular file and replacing it is the shape a stray pipe
# left in a real work tree has, which is the state this guard exists for.


def _plant_fifo(repo: Path, rel: str) -> Path:
    """A fifo at ``repo/rel``, replacing a committed regular file of that name.

    The caller must have committed ``rel`` first (``_commit_file`` does).
    Returns the path, which the caller may hand to a scan: the fixture is
    removable (unlinking a fifo is always safe), so ``tmp_path`` cleanup never
    blocks on it, and no writer process is started -- a scan that opens the pipe
    blocking hangs against the test's own ``timeout=``, which IS the finding.
    """
    return _plant_non_regular(repo, rel, os.mkfifo)


def _plant_untracked_fifo(repo: Path, rel: str) -> Path:
    """A fifo at ``repo/rel`` that git has never seen: the untracked control.

    ``git ls-files`` lists index entries only, so a path never added never
    reaches the scan whatever the scanner does. A test that asserts this one is
    asserting the LISTING is what keeps the scan off it, not a guard: pair it
    with a violation planted in a regular tracked file beside the pipe and
    require that violation to still be reported.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    os.mkfifo(target)
    return target


def _plant_fifo_link(repo: Path, rel: str, name: str = "outside") -> Path:
    """A tracked symlink at ``repo/rel`` whose target is a fifo outside the tree.

    The case a top-level ``lstat`` pre-check alone does not cover: the link
    itself is neither regular nor a pipe, and following it leads to a read that
    blocks. Only the ``S_ISREG`` check on the descriptor that was actually opened
    refuses it, so this is the fixture that pins that check rather than the
    flags.

    The pipe is created OUTSIDE the tree and linked in, so the tree holds a link
    rather than a second pipe: a fixture that planted both could pass with a
    guard that only ever looked at the link itself.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        target.unlink()
    pipe = target.parent.parent / f".{name}-fifo"
    if not pipe.exists():
        os.mkfifo(pipe)
    target.symlink_to(pipe)
    return target


def _plant_non_regular(repo: Path, rel: str, make) -> Path:
    """Commit-then-replace: ``make`` builds the non-regular node at ``repo/rel``.

    One builder for the swap so the tracked-fifo fixture cannot drift into two
    recipes for the same state. The pre-existing path is unlinked first: git
    will not stage a pipe, so the replacement is always post-commit.
    """
    target = repo / rel
    if not target.exists() and not target.is_symlink():
        raise AssertionError(
            f"{rel} was never committed: a tracked non-regular path is planted by "
            "replacing a committed regular file, since git cannot stage a pipe")
    target.unlink()
    make(target)
    return target



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
