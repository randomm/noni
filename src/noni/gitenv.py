"""The environment every shipped writer hands to its git calls.

``--repo`` is the only thing that names the state root (§7 of the product doc),
but a git child process also reads four variables from the environment, and
each of them overrides what ``--repo`` named: ``GIT_DIR`` and ``GIT_COMMON_DIR``
say which repository directory to use, ``GIT_WORK_TREE`` which working tree it
belongs to, and ``GIT_INDEX_FILE`` which index to stage and commit through. A
caller who exported one (a shell left set by a worktree, a wrapper that scripted
an alternate index) silently retargets every writer: the record lands in another
repository, or is staged and committed through a stray index, while the tool
still reports success for the tree ``--repo`` named.

``child_env`` is the one answer: the process environment minus those four, so a
writer's ``git -C <repo>`` resolves the repository from ``<repo>`` alone. It
removes and never sets, so every other variable a writer relies on still
travels to the child — the identity variables (``GIT_AUTHOR_*``,
``GIT_COMMITTER_*``) and the config pins the test harness applies
(``GIT_CONFIG_GLOBAL``) among them. Unlike the read-only census, which pins the
config files and leaves the location variables alone because it must answer for
whatever tree the ambient environment resolves to, a writer commits, and a
commit must go where the caller pointed.

This is why ``register.py`` builds its reuse marker as a literal path from
``--repo`` instead of asking git where the git directory is: a marker resolved
through ``git rev-parse`` would follow an inherited ``GIT_DIR`` to another
repository's state and answer the reuse question about the wrong session.

The module carries no other responsibility and imports nothing but ``os``.
"""

from __future__ import annotations

import os

# The four variables that relocate a git child process away from the ``-C``
# path the writer passes. Each is removed, not pinned: none of them is a value a
# writer supplies, so leaving any of them set would let the caller's shell
# decide which repository the writer commits to.
GIT_LOCATION_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
)


def child_env() -> dict[str, str]:
    """A copy of ``os.environ`` with the git location variables removed.

    Pass the result as the ``env`` of every git subprocess a writer runs, so
    ``--repo`` alone decides the repository, its working tree and its index.
    """
    env = dict(os.environ)
    for name in GIT_LOCATION_VARS:
        env.pop(name, None)
    return env
