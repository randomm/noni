"""What the launcher will and will not exec, decided on one argv.

The allow-list is the page's command vocabulary; the guards beside it are the rules
a vocabulary cannot express -- which ``git config`` keys the page may set, which
flag the page's empty branch-creating commit must carry, and which remote the
private state clone may be pushed to. They live apart from the launcher because
they are what a hostile line meets, and a test has to be able to call them on one
argv without building the whole topology (which matters: a whole-route run cannot
tell the project tree from the state clone when both hold a branch called
``main``).

Nothing here runs a page command; :func:`quickstart_runner.launch` does, and calls
these immediately before the exec.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from readme_support import _ALLOWED_GIT_CONFIG_KEYS

# The command vocabulary the page is allowed to print, as program-and-subcommand
# words. Every command the page prints is one of these; anything else is refused
# rather than exec'd, which is what keeps a rewritten block from running something
# the page never intended (a push on the project, say, or an ``rm``). Adding a form
# here is a decision about what the page may tell a reader to run, and has to be
# made on purpose.
LAUNCHABLE: frozenset[tuple[str, ...]] = frozenset({
    ("cd",),
    ("git", "commit"), ("git", "config"), ("git", "clone"), ("git", "push"),
    ("noni", "decide"), ("noni", "register"), ("noni", "claim"),
    ("noni", "order"), ("noni", "census"),
    ("python3", "-m"), ("echo",),
})

# The flag the page's branch-creating commit must carry: that commit holds no
# content, so without the flag the line is not the commit the section describes.
EMPTY_COMMIT_FLAG = "--allow-empty"


def gate_page_command(key: tuple[str, ...], argv: list[str]) -> None:
    """The per-command rules the allow-list alone cannot express.

    ``git config`` is refused for any key outside the identity pair -- the same
    list the README's reader gates on, read from there rather than copied, because
    the two pages make one promise about these commands. A key such as
    ``core.sshCommand``, ``url.<base>.insteadOf`` or ``remote.*.url`` would
    redirect the very commits and pushes this page's run makes, and what the page
    tells a reader to set is an identity, not the transport. The key is the word
    after the verb, read at its position rather than as a substring of the line, so
    a value that happens to contain a permitted word cannot satisfy it. The page's
    branch-creating line must carry :data:`EMPTY_COMMIT_FLAG`.
    """
    if key == ("git", "config"):
        position = argv.index("config") + 1
        assert position < len(argv), f"the page's git config names no key: {argv}"
        assert argv[position] in _ALLOWED_GIT_CONFIG_KEYS, (
            f"the page sets git config {argv[position]!r}, which is not an "
            f"identity key ({sorted(_ALLOWED_GIT_CONFIG_KEYS)}), so this harness "
            f"will not run it: {argv}")
    if key == ("git", "commit"):
        assert EMPTY_COMMIT_FLAG in argv, (
            f"the page's branch-creating line does not carry {EMPTY_COMMIT_FLAG}, "
            f"so it is not the empty commit the section describes: {argv}")


def config_value(repo: Path, key: str, *, env: dict[str, str]):
    """One ``git config --get`` on a tree, with its output kept for the message."""
    return subprocess.run(["git", "-C", str(repo), "config", "--get", key],
                          capture_output=True, text=True, env=env, timeout=120)


def guard_route_b_push(state_clone: Path, key: tuple[str, ...], argv: list[str],
                       state: bool, origin: Path, env: dict[str, str],
                       checked) -> None:
    """A Route B push may only ever name this fixture's origin and its ``main``.

    The page's first push is the one command in the run that can write outside the
    scratch trees, so both ends of it are read rather than assumed:

    - the argv must name ``origin`` and ``main`` as its remote and branch, so a
      line that addressed some other remote by name is refused rather than run;
    - the clone's ``remote.origin.url`` must still be the origin the fixture
      created (a remote ``set-url`` or ``--pushurl``, or a ``url.*.insteadOf``
      rewrite that reached this argv by another route, would otherwise send the
      state clone's commits to a remote this run never made).

    A green Route B run must not be able to push the private state clone anywhere
    else, and this is the check that makes that claim a checked one rather than an
    assumption about the clone the fixture built.
    """
    if key != ("git", "push") or not state:
        return
    assert argv[-2:] == ["origin", "main"], (
        f"the page's first push must name 'origin main' as its last two words: {argv}")
    listed = config_value(state_clone, "remote.origin.url", env=env)
    checked(listed, "the state clone's origin url")
    assert listed.stdout.strip() == str(origin), (
        f"the state clone's origin is {listed.stdout.strip()!r}, not the fixture "
        f"origin {str(origin)!r}: a green run must not be able to push the private "
        "state clone somewhere else")
