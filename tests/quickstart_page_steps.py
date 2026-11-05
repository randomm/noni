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

from _harness import REPO
from docs_promises import STATE_DIR
from quickstart_topology import CLONE_URL, World, git

# The draft the page tells a reader to copy and fill: the shipped template, read
# from the skill rather than restated here, so the page can never promise a draft
# its own writer would refuse.
INTENT_TEMPLATE = REPO / "skills" / "direction" / "references" / "intent-template.md"

# The file the page's PR-only variant of the ignore rule appends to: git's own
# untracked per-repository exclude file, shared by every worktree of the repository.
GIT_INFO_EXCLUDE = ".git/info/exclude"

# The two ignore files the page may write a rule into, and the directory each lands in.
IGNORE_TARGETS: frozenset[str] = frozenset({".gitignore", GIT_INFO_EXCLUDE})

# The rule the page asks for, in the form a reader's ``git`` reads it off disk: a
# leading and trailing slash around the state directory the page sells. The ``printf``
# form prints the same rule with a trailing newline the shell hands over escaped
# (``\n``), and the ``%%`` form is how a shell prints a literal percent -- neither
# escape survives the write, which is what the launches below prove rather than assert.
RULE: str = f"/{STATE_DIR}/"


def append_ignore_rule(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One of the page's two ignore-rule lines, applied to the scratch tree.

    The payload is taken from the golden list and written to the ignore file the line
    names. The page prints the rule twice -- ``echo ... >> .gitignore`` for the
    ordinary project, ``printf ... >> .git/info/exclude`` for the PR-only one -- and
    one dispatch covers both because the promise under test is the same: the same rule
    text, into a file git reads.

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
    assert entry == RULE, (
        f"the ignore rule the reader's shell would write is {entry!r}, not the "
        f"page's {RULE!r}: {argv}")
    target = world.project / argv[3]
    target.parent.mkdir(parents=True, exist_ok=True)
    # Append, never truncate: the page tells a reader to add a line to a file that
    # already holds their other rules, so a step that rewrote the file would pass a
    # test that only looked for the rule and still destroy the reader's ignore list.
    with target.open("a", encoding="utf-8") as handle:
        handle.write(entry + "\n")
    return subprocess.CompletedProcess(argv, 0, "", "")


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
    """What each ignore file of the scratch project actually holds.

    The read-back a route walk makes of the two dispatch cases above: a caller that
    only asserted the launcher returned exit 0 would never learn whether the rule
    reached the file, whether it reached the *named* file, or whether writing it
    destroyed the lines that were already there.
    """
    rules: dict[str, list[str]] = {}
    for name in sorted(IGNORE_TARGETS):
        path = world.project / name
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
