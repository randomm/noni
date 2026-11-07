"""Planting the allowlist the hygiene scan reads.

``_with_committed_allowlist`` writes the tree's own tracked allowlist holding the
entries a test wants honoured; ``_write_committed_allowlist`` puts a file at the same
path without committing it, for the states git cannot carry there. ``_allowlist_line``
formats one entry and ``_entry_fixture`` writes a file for the tests that use the
loader's seam. Beside ``census_denylist.py`` for the same reason: both the scrub tests
and the census's hygiene tests plant it, and a third copy in a third file is how the
format and the tests drift.

The allowlist is a *committed* file and there is no other route to it: an exemption
widens what the gate accepts, so it has to be reviewable, and the file git has never seen
is not reviewable. That is why every helper here commits, and why planting a tracked file
costs a commit per case -- the price of the guarantee, paid in the fixture rather than
argued about in the product.
"""

from __future__ import annotations

from pathlib import Path


def _allowlist_line(path: str, label: str, reason: str = "test fixture") -> str:
    """One allowlist line in the product's format: ``path | label | reason``."""
    return f"{path} | {label} | {reason}"


def _committed_allowlist_path(repo: Path) -> Path:
    """The name a committed allowlist carries: the product's constant, not a literal.

    A fixture that typed the filename would keep committing nothing after a rename,
    which is half of AC1 a test could otherwise hide.
    """
    from noni import public_safety

    return repo / public_safety.ALLOWLIST_FILENAME


def _with_committed_allowlist(repo: Path, *lines: str, commit_only: bool = False) -> Path:
    """Write the tree's own tracked allowlist, and commit it.

    The committed route is the only route the product has, and the one a test about
    tracked-ness, staleness or the file's own exemption needs: a claim about a committed
    file must rest on a file git has actually seen.

    Everything in the working tree is added, not only the file: a test that planted a
    fixture and then called this helper must not lose the fixture from the listing,
    since the scan answers for exactly what ``git ls-files`` holds. ``commit_only``
    skips the blanket add for the one test that needs a working-tree file to stay out
    of the listing.
    """
    from _harness import _git

    path = _committed_allowlist_path(repo)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if commit_only:
        _git(repo, "add", "--", path.name)
    else:
        _git(repo, "add", "--", ".")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "allowlist fixture")
    return path


def _write_committed_allowlist(repo: Path, *lines: str) -> Path:
    """Write the tree's allowlist path and commit nothing.

    For the states git cannot carry at a tracked path: a directory, a fifo or a body of
    raw bytes planted by the caller after this returns. The scan asks ``git ls-files``,
    so the tree's other files still answer and the verdict is about the object standing
    at the allowlist path, not about a listing that went empty.
    """
    path = _committed_allowlist_path(repo)
    if lines:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif path.exists() or path.is_symlink():
        path.unlink()
    return path


def _entry_fixture(tmp_path: Path, *lines: str) -> Path:
    """Write an allowlist file for the seam.

    For the tests that hand the path to the loader's seam (``_default_allowlist_file``)
    rather than planting it in a tree, so the loader's one candidate can be pointed at a
    file the tree does not hold.
    """
    path = tmp_path / "committed-allowlist.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
