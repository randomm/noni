"""The environment every shipped writer hands to its git calls.

``--repo`` is the only thing that names the state root (§7 of the product doc),
but a git child process also reads its environment, and several variables
override what ``--repo`` named. Four relocate the repository outright:
``GIT_DIR`` and ``GIT_COMMON_DIR`` say which repository directory to use,
``GIT_WORK_TREE`` which working tree it belongs to, and ``GIT_INDEX_FILE`` which
index to stage and commit through. Four more change what the child writes
without moving the repository, so clearing only those four leaves the hole open:
``GIT_OBJECT_DIRECTORY`` and ``GIT_ALTERNATE_OBJECT_DIRECTORIES`` relocate the
object store, so the objects a commit needs are written elsewhere while the
state root's refs still look untouched; ``GIT_TRACE``, ``GIT_TRACE2`` and
``GIT_TRACE2_EVENT`` make the child append its trace to a file the caller names;
``GIT_NAMESPACE`` silently redirects every ref name, and
``GIT_CEILING_DIRECTORIES`` can make the tree unresolvable. A caller who
exported one (a shell left set by a worktree, a wrapper that scripted an
alternate index or object store) silently retargets every writer while the tool
still reports success for the tree ``--repo`` named.

``child_env`` is the one answer, and it is fail-closed rather than a list of
known hazards: the process environment minus every variable whose name begins
with ``GIT_``, except those in ``CHILD_ENV_GIT_ALLOWLIST``. Naming a hazard is
therefore not required to be safe against it — a variable nobody thought of is
dropped by default, and only the names the writers genuinely rely on travel to
the child: the identity variables, the config pins the test harness applies
(``GIT_CONFIG_GLOBAL``), and the transport variables a caller legitimately sets.
It removes and never sets, so every non-git variable still travels. Unlike the
read-only census, which pins the config files and leaves the location variables
alone because it must answer for whatever tree the ambient environment resolves
to, a writer commits, and a commit must go where the caller pointed.

This is why every writer builds its state paths as literal paths from
``--repo`` instead of asking git where the git directory is: a path resolved
through ``git rev-parse`` would follow an inherited ``GIT_DIR`` to another
repository's state and answer the writer's questions about the wrong tree.

The module carries no other responsibility and imports nothing but ``os``.
"""

from __future__ import annotations

import os

# The prefix that marks a variable as git's own. Anything carrying it is
# dropped unless named below, because the set of variables that change what a
# git child does is larger than any list this module could keep current.
_GIT_PREFIX = "GIT_"

# The GIT_* variables a writer's child still needs, and the reason each is
# here: identity, config, and how the child reaches a remote. Nothing on this
# list chooses which repository, index or object store the child uses.
#
#   GIT_AUTHOR_* / GIT_COMMITTER_*  the writer commits under the caller's
#                                   identity; without these git refuses the
#                                   commit outright.
#   GIT_CONFIG_GLOBAL / _SYSTEM /
#   _NOSYSTEM                       which config files the child reads. The
#                                   test harness pins these to a null device so
#                                   a host ~/.gitconfig cannot reach a run, and
#                                   a caller may pin them for the same reason.
#   GIT_SSH / GIT_SSH_COMMAND /
#   GIT_ASKPASS / GIT_TERMINAL_PROMPT
#                                   how a pushing writer authenticates to its
#                                   remote and whether it may prompt. Writers
#                                   push (claim, release), so a caller's
#                                   transport must survive the filter. The
#                                   suite pins this tuple name for name, so a
#                                   name cannot leave it silently.
CHILD_ENV_GIT_ALLOWLIST: tuple[str, ...] = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_SSH",
    "GIT_SSH_COMMAND",
    "GIT_ASKPASS",
    "GIT_TERMINAL_PROMPT",
)

# The four that relocate the repository, kept as documentation of the original
# hazard: each is dropped by the prefix rule above and none is on the allowlist.
# The tests pin this tuple alongside the allowlist, so the two documented
# classes stay the two classes the suite proves.
GIT_LOCATION_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
)

_ALLOWLIST = frozenset(CHILD_ENV_GIT_ALLOWLIST)


def child_env() -> dict[str, str]:
    """A copy of ``os.environ`` minus every GIT_* variable but the allowlist.

    Pass the result as the ``env`` of every git subprocess a writer runs, so
    ``--repo`` alone decides the repository, its working tree, its index and its
    object store. The comparison is case-sensitive on purpose: git reads these
    names in upper case, and a lower-case lookalike is not one of them.
    """
    return {name: value for name, value in os.environ.items()
            if not name.startswith(_GIT_PREFIX) or name in _ALLOWLIST}
