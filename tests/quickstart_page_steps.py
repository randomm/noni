"""The page steps the harness stands in for, instead of replaying them in a shell.

Three of the quickstart's printed steps are not commands this suite can hand to an
``exec`` in the tree the tests run from, and the launcher
(:func:`quickstart_runner.launch`) dispatches each here rather than in its own body,
so the launcher stays the single reading of what a golden command means:

- **The ignore rules** (``echo ... >> .gitignore`` and the PR-only
  ``printf ... >> .git/info/exclude``): this repository's own ``.gitignore`` is a
  gate file no test may modify, so the payload is written into the scratch project's
  ignore file instead. The rule text still comes from the golden list, so a change to
  the page's rule is still a golden failure, and the target of each line is asserted
  rather than trusted: a golden line that retargeted the rule at some other path of
  the project would otherwise launch a step no reader was told to run.
- **The intent draft** (``noni intent --from ./intent-draft.md``): the page tells the
  reader to copy the skill's template and fill it, so the harness writes exactly that
  file at exactly the path the page's own line names. The writer still reads the path
  off argv, and a golden line that dropped ``--from`` or pointed it elsewhere fails
  here rather than launching a run whose input nobody reviewed.
- **The two clones.** The install section's clone of noni is the fixture's
  materialised copy (its URL is the OWNER placeholder and the run stays offline); the
  state section's clone of the private repository is launched for real against the
  bare origin the fixture seeded, so the branch, the upstream and the pushed commits
  the tests read afterwards are the product of the line the page prints.

Each case returns a :class:`subprocess.CompletedProcess` shaped like the one a launch
would have produced, so the caller's exit-code check cannot tell a stand-in from a
run -- which is the point: the assertions a route walk makes stay the same for all
four kinds of step.

The one place where a stand-in could hide a page that is wrong is the rewriting step:
a harness that only *compares* a printed payload never learns what the reader's shell
would have written. So the payload here goes through the real ``printf`` rather than a
string comparison of the token, and :func:`ignore_rules_written` is the read-back the
Route B tests make of what those steps put on disk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import REPO
from docs_promises import STATE_DIR
from quickstart_topology import CLONE_URL, World, git

from noni import public_safety

# The draft the page tells a reader to copy and fill: the shipped template, read
# from the skill rather than restated here, so the page can never promise a draft
# its own writer would refuse.
INTENT_TEMPLATE = REPO / "skills" / "direction" / "references" / "intent-template.md"

# The file the page's PR-only variant of the ignore rule appends to: git's own
# untracked per-repository exclude file, shared by every worktree of the repository.
GIT_INFO_EXCLUDE = ".git/info/exclude"

# The rule the page asks for, in the form a reader's ``git`` reads it off disk: a
# leading and trailing slash around the name being hidden. The ``printf`` form
# prints the same rule with a trailing newline the shell hands over escaped
# (``\n``), and the ``%%`` form is how a shell prints a literal percent -- neither
# escape survives the write, which is what the launches below prove rather than assert.
RULE: str = f"/{STATE_DIR}/"

# The Route B deny-list rule: the same leading slash, anchored to the clone's root,
# with the file's name read from the product's own constant rather than typed -- a
# rename of the deny-list changes this rule and the page's line together, or the
# Route B step fails. No trailing slash: git reads ``/name/`` as a *directory*, so
# the rule for a file names it the way the page writes it.
DENYLIST_RULE: str = f"/{public_safety.DENYLIST_FILENAME}"

# What the page's Route B line puts in the deny-list file itself: the comment form
# the deny-list section shows, and one usable entry. Read from the page by
# :func:`write_denylist_file` and required here, so the file the reader is told to
# create is one the product's ``load_denylist`` counts as active rather than a
# placeholder that leaves the hygiene class in ``present but empty``.
DENYLIST_ENTRY: str = "example-corp"

# The page's Route B deny-list write, as the harness resolves it: a redirection to
# the file at the root of the state clone, which is the tree the census audits on
# that route.
DENYLIST_TARGET: str = f"{STATE_DIR}/{public_safety.DENYLIST_FILENAME}"

# The path of the clone's own ``.gitignore`` as the page writes it -- a path *inside*
# the clone, so :func:`_ignore_target` resolves it under the world's real clone and
# not by stripping the directory's name off the front.
CLONE_GITIGNORE: str = f"{STATE_DIR}/.gitignore"

# The one name the product's ``load_denylist`` reads at the audited tree's root;
# :func:`denylist_file` resolves it under the world's real clone with the product's
# own helper, so the harness writes where the census reads.
DENYLIST_BASENAME: str = public_safety.default_denylist_file(Path(STATE_DIR)).name

# The ignore files the page may write a rule into, each with the rule it must come to
# hold. The third entry is the state clone's own ``.gitignore``, which the Route B
# deny-list step appends to: the rule there hides the clone's untracked deny-list
# from the clone's own git, and it has to be written through the clone's path
# because that repository is not the one the command's cwd belongs to. Keying the
# rule to the target is what stops the deny-list line passing a test that only
# looked for "some rule in some ignore file".
IGNORE_RULES: dict[str, str] = {
    ".gitignore": RULE,
    GIT_INFO_EXCLUDE: RULE,
    f"{STATE_DIR}/.gitignore": DENYLIST_RULE,
}

IGNORE_TARGETS: frozenset[str] = frozenset(IGNORE_RULES)


def append_ignore_rule(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One of the page's write-a-line-into-a-file steps, applied to the scratch tree.

    The payload is taken from the golden list and written to the ignore file the line
    names. The page prints three of them -- ``echo ... >> .gitignore`` for the
    ordinary project, ``printf ... >> .git/info/exclude`` for the PR-only one, and
    ``echo ... >> .noni-state/.gitignore`` for the state clone's own deny-list --
    and one dispatch covers all three because the promise under test is the same: the
    rule the reader's shell renders, into the file the line names. Each target's own
    rule is read from :data:`IGNORE_RULES`, so the deny-list line cannot clear the
    assertion written for the state-directory line. The step that writes the
    deny-list file itself is not an ignore rule and leaves this dispatch to
    :func:`_write_denylist_file`.

    Both forms are *rendered* by the program the page names rather than by a string
    comparison against a literal here. The reader's shell interprets the escapes a
    ``printf`` payload carries, and the two ways this step could be quietly wrong are
    both invisible to a comparison: a payload no ``printf`` can render (a lone ``%``
    is an invalid conversion specification, which exits 1 on the reader's machine and
    writes nothing) and a payload carrying an escape that renders to something other
    than the rule (``%s`` swallows its own argument, ``\\t`` writes a tab). So the
    payload goes through a real ``printf``, its exit code is checked the way a
    reader's would be, and the text it printed must be the rule the ``echo`` form
    carries byte for byte.
    """
    assert argv[0] in ("echo", "printf"), f"not an ignore-rule line: {argv}"
    assert argv[2:] == [">>", argv[3]] and argv[3] in IGNORE_TARGETS, (
        f"the ignore-rule line writes somewhere other than one of "
        f"{sorted(IGNORE_TARGETS)}: {argv}")
    entry = _rendered_rule(argv)
    expected = IGNORE_RULES[argv[3]]
    assert entry == expected, (
        f"the ignore rule the reader's shell would write is {entry!r}, not the "
        f"page's {expected!r} for {argv[3]}: {argv}")
    target = _ignore_target(world, argv[3])
    # The clone-relative target of the Route B deny-list line is reached through
    # the world's real clone path; the two project-level targets sit under the
    # project's root, which is where the page's line is typed from.
    target.parent.mkdir(parents=True, exist_ok=True)
    # Append, never truncate: the page tells a reader to add a line to a file that
    # already holds their other rules, so a step that rewrote the file would pass a
    # test that only looked for the rule and still destroy the reader's ignore list.
    with target.open("a", encoding="utf-8") as handle:
        handle.write(entry + "\n")
    return subprocess.CompletedProcess(argv, 0, "", "")


def denylist_file(world: World) -> Path:
    """Where the product reads the clone's deny-list: its root, by its own helper."""
    return public_safety.default_denylist_file(world.state)


def plant_denylist(world: World) -> Path:
    """Write the clone's deny-list with one usable entry, as the page tells the reader.

    The page cannot print the names a team must not commit, and on Route B it points
    at the example the deny-list section shows rather than echoing the file, so the
    harness puts the file there for the two promises that matter to be testable at
    all: that it sits where ``load_denylist`` reads it, and that the clone does not
    track it. A file of comments alone is the ``present but empty`` state the page
    names, which is why the entry is the one the page shows.
    """
    target = denylist_file(world)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# an operator name, an external project or tool name, or a"
                      f" hostname\n{DENYLIST_ENTRY}\n", encoding="utf-8")
    return target


def _ignore_target(world: World, target: str) -> Path:
    """The file on disk that one ignore-rule line writes into.

    The page's own path, resolved against the tree the command runs in. Two of the
    three targets are paths of the project; the Route B deny-list rule names a path
    inside the state clone, which the harness knows by its real location and the
    page cannot, so that one resolves under :attr:`World.state` — the same re-rooting
    the launcher applies to every ``-C`` and ``--repo`` value.
    """
    # The clone is a repository of its own, so a path the page writes under it is
    # relative to the clone: the directory's own name is the anchor the page's line
    # carries, and it is dropped rather than resolved a second time under the
    # clone's path. The two project-level targets keep the project as their root --
    # that is where the page's line is typed from.
    relative = Path(target)
    if relative.parts[:1] == (STATE_DIR,):
        return world.state / Path(*relative.parts[1:])
    return world.project / relative


def _rendered_rule(argv: list[str]) -> str:
    """The text one ignore-rule line puts on disk, as the page's own program renders it.

    The ``printf`` form is handed to the real program with its exit code checked -- a
    payload git would refuse to write is the reader's failing step, not a harness
    string to compare. The ``echo`` form has no escape to interpret, so it is taken
    from the golden token directly.
    """
    entry = argv[1]
    if argv[0] == "echo":
        return entry.strip()
    proc = subprocess.run(["printf", entry], capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, (
        f"the page's printf line exits {proc.returncode} on a reader's shell "
        f"({proc.stderr.strip()}), so the ignore rule is never written: {argv}")
    return proc.stdout.rstrip("\n")


def ignore_rules_written(world: World) -> dict[str, list[str]]:
    """What each ignore file the page writes into actually holds.

    The read-back a route walk makes of the dispatch cases above: a caller that
    only asserted the launcher returned exit 0 would never learn whether the rule
    reached the file, whether it reached the *named* file, or whether writing it
    destroyed the lines that were already there. Each name is read where
    :func:`_ignore_target` writes it, so the read-back cannot look at a file the
    page's line never named.
    """
    rules: dict[str, list[str]] = {}
    for name in sorted(IGNORE_TARGETS):
        path = _ignore_target(world, name)
        rules[name] = (path.read_text(encoding="utf-8").splitlines()
                       if path.is_file() else [])
    return rules


def write_intent_draft(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Put the draft the page's intent line reads onto the reader's disk."""
    position = argv.index("--from")
    draft = argv[position + 1]
    assert not draft.startswith("-"), (
        f"the page's intent line passes --from {draft!r}, which is a flag and not "
        f"a draft path: {argv}")
    target = cwd_draft(world, draft)
    assert not target.exists(), (
        f"the page's draft path {draft} already exists in the scratch tree, so the "
        "run could not be attributed to the file this harness wrote")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(INTENT_TEMPLATE.read_text(encoding="utf-8"),
                      encoding="utf-8")
    return subprocess.CompletedProcess(argv, 0, "", "")


def cwd_draft(world: World, draft: str):
    """Resolve the page's draft path against the directory that command runs in.

    The page's line runs in the reader's own repository (the ``cd`` step), so a
    relative path means a file of the project, not of the state clone: the intent
    draft is the reader's own document, and only the artifact the writer commits
    lands under ``--repo``.
    """
    from pathlib import Path

    relative = Path(draft)
    assert not relative.is_absolute(), (
        f"the page's --from names an absolute path {draft!r}, which the harness "
        "would have to trust rather than resolve")
    return world.project / relative


def state_clone(world: World, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's state-repository clone, run for real against the fixture's origin.

    The page prints two clones and they stand for different things: see the module
    docstring. The install clone's assertion of the placeholder URL lives here too, so
    a changed install block touches this module along with the golden list.
    """
    if CLONE_URL in " ".join(argv):
        assert argv[2] == "https://github.com/OWNER/noni" and argv[3] == "noni", (
            f"the install clone must name the page's placeholder URL: {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert argv[2].endswith(".git") and argv[3] == STATE_DIR, (
        f"the page's state clone must name the {STATE_DIR} target: {argv}")
    return git(world.project, "clone", "-q", str(world.origin), STATE_DIR,
               env=world.env)
