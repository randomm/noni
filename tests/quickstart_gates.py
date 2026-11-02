"""What the launcher will and will not exec, decided on one argv.

The allow-list is the page's command vocabulary; the guards beside it are the rules a
vocabulary cannot express -- which ``git config`` keys the page may set, which flag the
page's empty branch-creating commit must carry, and which remote the private state clone
may be pushed to. They live apart from the launcher because they are what a hostile line
meets, and a test has to be able to call them on one argv without building the whole
topology (which matters: a whole-route run cannot tell the project tree from the state
clone when both hold a branch called ``main``).

The ``git config`` rules themselves are a module of their own,
:mod:`quickstart_config_grammar`, because they are the largest of these decisions and
the most token-shaped; this module decides *when* to consult them.

Nothing here runs a page command; :func:`quickstart_runner.launch` does, and calls these
immediately before the exec.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from quickstart_config_grammar import screen_config_key

# The command vocabulary the page is allowed to print, as program-and-subcommand words.
# Every command the page prints is one of these; anything else is refused rather than
# exec'd, which is what keeps a rewritten block from running something the page never
# intended (a push on the project, say, or an ``rm``). Adding a form here is a decision
# about what the page may tell a reader to run, and has to be made on purpose.
LAUNCHABLE: frozenset[tuple[str, ...]] = frozenset({
    ("cd",),
    ("git", "commit"), ("git", "config"), ("git", "clone"), ("git", "push"),
    ("noni", "decide"), ("noni", "register"), ("noni", "claim"),
    ("noni", "order"), ("noni", "census"),
    ("python3", "-m"), ("echo",),
})

# The flag the page's branch-creating commit must carry: that commit holds no content,
# so without the flag the line is not the commit the section describes.
EMPTY_COMMIT_FLAG = "--allow-empty"



def gate_page_command(key: tuple[str, ...], argv: list[str]) -> None:
    """The per-command rules the allow-list alone cannot express.

    ``git config`` is refused for any key outside the identity pair -- the same
    list the README's reader gates on, read from there rather than copied, because
    the two pages make one promise about these commands. A key such as
    ``core.sshCommand``, ``url.<base>.insteadOf`` or ``remote.*.url`` would
    redirect the very commits and pushes this page's run makes, and what the page
    tells a reader to set is an identity, not the transport.

    The key is the first non-option word after the verb, reached by walking past
    the option tokens rather than read as "whatever sits one word after
    ``config``": that position is the first thing ``git`` itself re-interprets, so a
    line that carried ``--get`` or a value-taking option there would have the gate
    check a word git does not read as the key. Every option token, every value an
    option consumed, and every token past the key are screened too, so nothing can be
    smuggled in an option position or in a trailing word; an option the walk cannot
    model is refused rather than guessed at, a query that took its key inside the
    flag (``--get=<key>``, which leaves git no key to read) is refused, and
    ``--push`` -- the one option that writes a remote's push end -- is refused in any
    position. The page's branch-creating line must carry :data:`EMPTY_COMMIT_FLAG`.
    """
    if key == ("git", "config"):
        screen_config_key(argv, argv.index("config"))
    if key == ("git", "commit"):
        assert EMPTY_COMMIT_FLAG in argv, (
            f"the page's branch-creating line does not carry {EMPTY_COMMIT_FLAG}, "
            f"so it is not the empty commit the section describes: {argv}")


def config_value(repo: Path, key: str, *, env: dict[str, str]):
    """One ``git config --get`` on a tree, with its output kept for the message."""
    return subprocess.run(["git", "-C", str(repo), "config", "--get", key],
                          capture_output=True, text=True, env=env, timeout=120)


def _probe(env: dict[str, str], state_clone: Path, key: str, what: str,
           *, unset_ok: bool = False) -> str:
    """One config value of the state clone, as a probe that cannot lie quietly.

    ``git config --get`` has three outcomes and they are three different claims:
    **0** carries the value on stdout, **1** means the key is unset with nothing on
    either stream, and **anything else** means the read itself failed (no such tree,
    an unreadable config file, a git too old for the flag). Collapsing them into one
    comparison on stdout is the bug: a probe that never ran prints nothing, and a
    guard that read "nothing" as "unset" would compare an empty string against the
    value it expected -- which for a ``pushurl`` is exactly the answer that lets the
    private clone be pushed elsewhere.

    So: a non-0/1 code is an immediate failure, an unset key is accepted only where
    the caller said unset is meaningful (the fixture's clone has no ``pushurl``, and
    git then pushes to the url), and a 0 with empty stdout is its own failure. Both
    streams and the code appear in every message, so a failure says what git said.

    The probe is a module-level call to :func:`config_value` so a test can substitute
    a probe that cannot run and see the guard refuse the launch.
    """
    listed = config_value(state_clone, key, env=env)
    detail = (f"{what} probe ({key}) on {state_clone} exited {listed.returncode}\n"
              f"stdout: {listed.stdout}\nstderr: {listed.stderr}")
    if listed.returncode not in (0, 1):
        raise AssertionError(detail)
    if listed.returncode:
        assert unset_ok, (
            f"{what} probe ({key}) on {state_clone} found the key unset: the page's "
            f"clone records its origin when git clone makes it, so a clone with no "
            f"url is not the tree the fixture built\n"
            f"stdout: {listed.stdout}\nstderr: {listed.stderr}")
        return ""
    assert listed.returncode == 0, detail
    value = listed.stdout.strip()
    assert value, (
        f"{what} probe ({key}) on {state_clone} exited 0 with an empty value, which "
        f"is not the same as the key being unset: a remote that names nothing is "
        f"not a remote this guard can vouch for\n"
        f"stdout: {listed.stdout}\nstderr: {listed.stderr}")
    return value


def _guard_argv(argv: list[str]) -> list[str]:
    """The page's own push line: the words from ``push`` to the end of the argv.

    Everything right of the verb is what a reader would have typed -- the remote, the
    branch and any refspec -- and it is the shape the guard's assertions are about.
    A launcher that appended its own ``-C <tree>`` here is caught by
    :func:`_state_targets`, which reads the whole argv, not by this slice.
    """
    return argv[argv.index("push"):]


def _state_targets(argv: list[str]) -> list[str]:
    """Every absolute ``-C`` value in the argv, in order -- the trees git will run in.

    The launcher re-roots a clone-addressed line by replacing the value of **every**
    ``-C`` in it (:func:`quickstart_runner.reroot_state_git`), so an absolute
    directory anywhere in the argv is a tree the harness is about to hand to git --
    never a word a reader typed, because the page writes the clone by its path inside
    the project and cannot know where the project sits. All of them are collected,
    not the first or the last: git honours every ``-C`` it is given, so a line that
    names the private clone in one slot and somewhere else in another is a write to
    both, and a guard that looked at a single position would vouch for one of them
    and exec the other. A trailing ``-C`` with no value is refused here rather than
    read as "targets nothing", which is what a silent pass would mean.
    """
    targets: list[str] = []
    for position, token in enumerate(argv):
        if token != "-C":
            continue
        assert position + 1 < len(argv), (
            f"the page's push prints -C with no tree to run in: {argv}")
        value = argv[position + 1]
        if Path(value).is_absolute():
            targets.append(value)
    return targets


def guard_route_b_push(state_clone: Path, key: tuple[str, ...], argv: list[str],
                       state: bool, origin: Path, env: dict[str, str],
                       checked) -> None:
    """A push of the state clone may only ever name this fixture's origin and ``main``.

    The page's first push is the one command in the run that can write outside the
    scratch trees, so all three ends of it are read rather than assumed:

    - the argv must name ``origin`` and ``main`` as its remote and branch, so a
      line that addressed some other remote by name is refused rather than run;
    - ``remote.origin.url`` must still be the origin the fixture created;
    - ``remote.origin.pushurl`` must be either unset (git then pushes to the url
      above, which is why 1 is an acceptable probe code and not a failure) or the
      same fixture origin. git prefers ``pushurl`` over ``url`` for a push, so a
      clone whose pushurl was moved by ``remote set-url --push`` would send the
      state clone's commits elsewhere while the url the guard used to read still
      named this fixture.

    The gate is keyed on the **argv shape** -- a launched ``git push`` whose absolute
    ``-C`` target is the state clone -- and not on the caller's Route label, because
    the label is whatever the caller claims: a page line launched as Route A that
    ``-C``'s into the state clone is the same write and gets the same guard. Every
    absolute ``-C`` in the line is inspected, so a second one naming another tree is
    caught rather than exec'd unchecked, and the remote and branch are read from the
    page's own words, from ``push`` to the end of the argv.

    A green Route B run must not be able to push the private state clone anywhere
    else, and this is the check that makes that claim a checked one rather than an
    assumption about the clone the fixture built.
    """
    if key != ("git", "push") or "push" not in argv:
        return
    # Keyed on the argv, never on the caller's Route label: the label is an argument
    # the caller chooses, and a line launched as Route A that ``-C``'s into the
    # private clone is the same write. The test is on the absolute ``-C`` values the
    # launcher itself put in the line, which is also what separates the private clone
    # from the reader's clone of noni -- that one the fixture makes with ``git
    # clone`` and never pushes, so it never appears as an absolute ``-C`` target.
    if str(state_clone) not in _state_targets(argv):
        return
    command = _guard_argv(argv)
    assert command[-2:] == ["origin", "main"], (
        f"the page's first push must name 'origin main' as its last two words: {argv}")
    listed = _probe(env, state_clone, "remote.origin.url",
                    "the state clone's origin url")
    assert listed == str(origin), (
        f"the state clone's origin is {listed!r}, not the fixture "
        f"origin {str(origin)!r}: a green run must not be able to push the private "
        "state clone somewhere else")
    pushurl = _probe(env, state_clone, "remote.origin.pushurl",
                     "the state clone's origin pushurl", unset_ok=True)
    assert pushurl in ("", str(origin)), (
        f"the state clone's remote.origin.pushurl is {pushurl!r}, and git prefers "
        f"it over remote.origin.url for a push, so this push would leave the "
        f"fixture origin {str(origin)!r}: a green run must not be able to push the "
        "private state clone somewhere else")
