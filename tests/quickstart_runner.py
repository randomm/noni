"""Launching the quickstart's golden commands in the topology its page describes.

Three layers, each readable on its own: ``docs_commands`` / ``docs_promises`` parse
the page, :mod:`quickstart_golden` states what the page must print, and
:mod:`quickstart_topology` builds the trees. This module is the dispatch between a
golden command and an ``exec``: it checks the page against the golden list, then
applies the two moves the harness must make because it cannot be the reader's
machine, and nothing else.

The two moves, and why each is a plain mapping rather than a rule with a defence
beside it:

- **Placeholder substitution.** ``<record-id>`` is the id the reader reads off the
  ``decide`` line's own output and ``<session-id>`` is the id ``register`` printed,
  so the harness reads each off the file that line committed (see
  :meth:`quickstart_topology.World.collect_record_id` and
  :meth:`quickstart_topology.World.collect_session_id`). Applied token by token,
  never by rejoining the line: one argv entry holds spaces the reader quoted
  (``q1=Wait a week``), and a join-and-resplit would hand the program those words
  separately -- a different command from the one on the page.
- **Re-rooting.** The page names the state clone by its path *inside* the project
  (``.noni-state``) and the scratch project lives at a generated path, so the value
  of ``-C`` / ``--repo`` becomes the clone's real path. Only that value moves;
  every other token stays as printed, so a wrong verb or flag still fails the way a
  reader would see it.

Both moves are applied **after** the golden comparison, and only to commands the
comparison accepted. That ordering is the whole simplification: a move cannot be
tricked into addressing the wrong tree, because the argv it may touch is one of the
literal lists in :mod:`quickstart_golden`.

Two page steps are not commands a reader's shell ran, so the launcher asserts them
instead of exec'ing them: the ``cd`` into a directory the page cannot name (every
launched command already carries the cwd the harness chose), and the ``echo ... >>
.gitignore`` line, whose payload is written to the scratch project's ignore file --
this repository's own ``.gitignore`` is a gate file no test may modify. The install
section's ``git clone`` and ``pip install`` are the fixture's materialised clone and
its venv install (see :mod:`quickstart_topology`); the ``gh`` recipe is run through
``jq`` by the issue-state test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _harness import REPO
from docs_promises import STATE_DIR
from quickstart_golden import GOLDEN
from quickstart_topology import (
    CLONE_URL,
    READER_DIR,
    World,
    build_installed_world,
    checked,
    fresh_scratch,
    git,
    run_env,
)

# The draft the page tells a reader to copy and fill: the shipped template, read
# from the skill rather than restated here, so the page can never promise a draft
# its own writer would refuse.
INTENT_TEMPLATE = REPO / "skills" / "direction" / "references" / "intent-template.md"

__all__ = [
    "ORDERING_NOW",
    "World",
    "build_installed_world",
    "checked",
    "date_arg",
    "fresh_scratch",
    "git",
    "golden",
    "launch",
    "recipe_gh_argv",
    "reroot",
    "route_commands",
    "run_env",
    "run_route_b",
    "state_dir_commands",
    "substitute",
]

# A fixed clock for the ordering runs the quickstart's tests make: the ordering
# group's stale class is time-based, and a run without --now would let the host
# clock decide whether a fixture's confirmed stamps read as stale. One owner for
# both quickstart test modules, so the pair cannot drift to different instants.
ORDERING_NOW = "2026-10-27T12:00:00Z"

# Both placeholders the page asks the reader to fill take their value from the
# running tree (see ``World.collect_record_id`` and ``World.collect_session_id``):
# each names a file a writer committed, so a fixed value would name one no run can
# have made. There is deliberately no fallback mapping for them, and no such name in
# this module. ``<record-id>`` used to carry the literal
# ``2026-11-02-release-scope`` (#70): decide dates the id it writes by the day it
# ran, so that literal named a real record on one day only and the page's ordering
# line exited 4 ever after. A literal cannot be caught by a walk that collects,
# either -- the collector overwrites it -- so the two names being absent is the
# defence, together with the launcher's refusal of an unfilled placeholder (see
# :func:`substitute`): with nothing to plant, a stale id stops the run at the
# launcher instead of reaching a writer where it would be reported as a record that
# does not exist.

# Every command of the golden list, flattened: the literal set :func:`launch`
# compares its argv against before the two moves below touch it, so a command no
# section prints never reaches an exec.
_ALL_GOLDEN: list[list[str]] = [argv for label in GOLDEN for argv in GOLDEN[label]]


def golden(label: tuple[str, ...]) -> list[list[str]]:
    """The literal commands the golden list pins for one page section."""
    commands = GOLDEN[label]
    assert commands, f"the golden list pins no commands for the '{label[0]}' section"
    return commands


def route_commands(label: tuple[str, ...]) -> list[list[str]]:
    """The page's commands for one section, checked against the golden list.

    Parsed from the page's own fences and compared to the literal list before
    anything is returned, so every caller of this helper runs the page it reviewed:
    a command added, dropped, reordered or reworded fails here, naming the section,
    rather than launching something nobody read.
    """
    from docs_commands import block_commands
    from docs_promises import QUICKSTART, bash_blocks_text, section_body

    body = section_body(QUICKSTART.read_text(encoding="utf-8"), label[0])
    commands = [argv for block in bash_blocks_text(body)
                for argv in block_commands(block)]
    expected = golden(label)
    assert commands == expected, (
        f"docs/QUICKSTART.md no longer prints the '{label[0]}' commands the harness "
        f"pins, in this order:\n  page: {commands}\n  golden: {expected}\n"
        "A page change is reviewed by updating tests/quickstart_golden.py.")
    return commands


def substitute(argv: list[str], extra: dict[str, str] | None = None,
               *, fill: bool = True) -> list[str]:
    """Fill the page's placeholders with the values the reader would supply.

    The only values are the ones a running tree produced, handed in as ``extra``
    (``world.placeholders``). ``fill`` is the two readings of one mapping: the
    launcher's, which refuses a placeholder with no value (a writer handed the page's
    own ``<record-id>`` reports a record that does not exist, which is the misleading
    half of #70), and a test's, which leaves the token visible so the page's shape
    can be asserted. One mapping, two honest readings, and no caller silently
    substituting a value it invented: the launched token is always the value the
    collector wrote under the page's own key.
    """
    values = dict(extra or {})
    filled = [values.get(token, token) for token in argv]
    if fill:
        _assert_filled(filled)
    return filled


def _assert_filled(filled: list[str]) -> None:
    """Refuse a filled argv that still carries one of the page's ``<...>`` words.

    A value read off disk can be absent -- a collector that did not run, a walk that
    skipped the writer -- and passing the page's literal word to ``noni order``
    produces a refusal about a record that "matches no record file", pointing the
    reader at the wrong sentence. Naming the command and the word here is the honest
    failure. The caller is :func:`substitute` with ``fill`` on, which is the
    launcher's reading; only the commands the launcher execs reach it, since the
    dispatch cases return before any substitution.
    """
    from docs_commands import placeholder_words

    left = [token for token in filled if placeholder_words(token)]
    assert not left, (
        f"the harness would launch {' '.join(filled[:2])} with the unfilled "
        f"placeholder {left}: the collector that fills it did not run")


def date_arg(world: World, argv: list[str]) -> list[str]:
    """The decide line's argv with the harness's ``--date`` appended, if it names one.

    The page's decide line prints no ``--date``, so decide takes the date part of
    the record id from today's UTC clock. That is right for the reader and wrong for
    the suite: a test wants the record under a date it chose, so it says so on the
    world (``World.decide_date``) and the argument is appended here -- **after** the
    golden comparison in :func:`launch`, which is the same place the two other moves
    are applied. The page's printed line and the golden list therefore stay as
    reviewed, and the date control reaches the child on its argv (in-process
    monkeypatching cannot: the writers run as subprocesses).
    """
    if world.decide_date is None or argv[:2] != ["noni", "decide"]:
        return list(argv)
    assert "--date" not in argv, f"a golden decide line already names --date: {argv}"
    return [*argv, "--date", world.decide_date]


def reroot(argv: list[str], state: Path) -> list[str]:
    """Point one golden command's state path at the real clone.

    The page writes ``git -C .noni-state <verb> ...`` and ``noni ... --repo
    .noni-state ...`` from the project's root, which is what a reader types; the
    harness knows where the project sits and the page cannot. Only the value of the
    anchor moves.

    The preconditions the mapping is defined over are asserted here rather than
    assumed from the list it happens to run on: a command that names the state
    directory as a whole token must name it exactly once, and exactly as the value of
    the one ``-C`` / ``--repo`` anchor being moved. A golden line that broke either
    shape would leave the mapping guessing which of two tokens to move, so it raises
    instead. The page's ``git clone`` of the state repository is the one golden
    command exempted: it names the directory as its target and the launcher handles
    it before this mapping, in :func:`state_clone`.
    """
    anchors = [position for position, token in enumerate(argv)
               if token in ("-C", "--repo") and position + 1 < len(argv)
               and argv[position + 1] == STATE_DIR]
    if STATE_DIR in argv and argv[1:2] != ["clone"]:
        # The page's state ``git clone`` is the one golden command that names the
        # directory as its own target rather than as an anchor value; the launcher
        # dispatches it before it ever reaches this mapping (see ``state_clone``).
        assert argv.count(STATE_DIR) == 1, (
            f"a command names the state directory more than once, so the re-rooting "
            f"has no single value to move: {argv}")
        assert len(anchors) == 1, (
            f"the command names the state directory outside a -C/--repo value, so "
            f"there is no anchor to move: {argv}")
    elif any(token in ("-C", "--repo") for token in argv):
        assert not anchors, f"an anchor names the state directory: {argv}"
    if not anchors:
        return list(argv)
    position = anchors[0]
    return [*argv[:position + 1], str(state), *argv[position + 2:]]


def state_dir_commands() -> list[list[str]]:
    """Every golden command that names the state clone as the tree itself.

    A whole-token mention, so the page's two other references to the directory (the
    ignore-rule payload ``/.noni-state/`` and nothing else) are not confused with a
    path the writer opens. These are the commands the re-rooting is defined over,
    and the ones the test over the golden list checks: each names the clone exactly
    once, and the ones the launcher moves name it exactly as the value of one of the
    two anchors it understands (``git -C <clone>``, ``noni ... --repo <clone>``).
    The clone line carries the directory as its target and is asserted where it is
    dispatched, in :func:`state_clone`.
    """
    return [argv for label in GOLDEN for argv in GOLDEN[label]
            if STATE_DIR in argv]


def recipe_gh_argv() -> list[str]:
    """The page's ``gh issue list`` recipe line, as the golden list prints it."""
    from quickstart_golden import ISSUE_STATE

    argv = [command for command in golden(ISSUE_STATE) if command[0] == "gh"]
    assert len(argv) == 1, f"the page must print exactly one gh recipe: {argv}"
    return argv[0]


def run_route_b(world: World) -> list[list[str]]:
    """Every Route B command the page prints, launched in order and checked.

    The one walk every Route B test drives: the project's git identity comes from the
    page's own Route A config lines (Route B's ignore-rule line writes into the
    project, and ``git status`` there reports an untracked ``.gitignore`` unless the
    tree has an identity), the register line's session id has to be read off disk
    *after* that line and *before* the claim line that names it, and the snapshot
    that makes that read mean "this run added one" has to be taken before register
    ran. Two copies of that sequence drift -- one drops the snapshot, the other gains
    a config call the page never printed -- and then the two modules stop running the
    same route.

    The two collector pairs are hooked the same way, around the line that produces
    the id, and each line that *consumes* an id is checked against the token the
    launcher filled for it. That is the only place a stale id can be seen for what it
    is: a collector overwrites whatever value a mapping held, so a comparison of argv
    against the collected id is true of a planted literal and a correct one alike,
    while the writer's own refusal -- exit 4, "no decision record ... is in the
    ledger" -- is the reader's actual symptom (#70).
    """
    _checked_identity(world)
    commands = route_commands(("Route B",))
    for argv in commands:
        if argv[:2] == ["noni", "register"]:
            world.mark_sessions()
        if argv[:2] == ["noni", "decide"]:
            world.mark_decisions()
        proc = launch(world, argv, world.project)
        checked(proc, f"Route B command {argv}")
        if argv[:2] == ["noni", "register"]:
            world.collect_session_id()
        if argv[:2] == ["noni", "decide"]:
            world.collect_record_id()
        if argv[:2] in _ID_CONSUMERS:
            _assert_consumed_id(argv, substitute(argv, world.placeholders))
    return commands


# The three lines that carry an id a collector produced rather than one the reader
# typed: both direction writers' ``--decision`` and the claim writer's
# ``--session-id``. The intent writer is here because it asks the same question of
# the ledger as the ordering writer does, so it earns the same two refusals: a
# golden line pre-filled with a value, and a token no writer could have produced.
_ID_CONSUMERS: tuple[tuple[str, ...], ...] = (
    ("noni", "intent"), ("noni", "order"), ("noni", "claim"))

# The flag each consumer carries its id in, keyed by the command pair.
_ID_FLAGS = {("noni", "intent"): "--decision", ("noni", "order"): "--decision",
             ("noni", "claim"): "--session-id"}


def _assert_consumed_id(argv: list[str], filled: list[str]) -> None:
    """Pin the exact token a writer was launched with for the id it must name.

    The caller has already checked the exit code and already built ``filled`` with
    :func:`substitute`, the launcher's own filling -- so what is asserted here is
    the very token that reached ``exec``, not a re-derivation that could agree with
    a planted value. Two refusals, both of them #70's shapes: a golden line whose id
    token was filled in at the source (the golden list must carry the page's
    placeholder, never a value), and a filled token that is no id a writer could have
    produced. The second is the one a plain "argv equals collected id" comparison
    cannot see -- a collector overwrites whatever a mapping held, so a planted
    literal satisfies that comparison and still names a record that does not exist.
    """
    from docs_commands import placeholder_words

    flag = _ID_FLAGS[tuple(argv[:2])]
    position = argv.index(flag)
    assert placeholder_words(argv[position + 1]) == [argv[position + 1]], (
        f"{argv[1]} names {flag} {argv[position + 1]!r}, which is not the page's "
        f"placeholder token: the golden line has been filled in at the source")
    launched = filled[position + 1]
    assert placeholder_words(launched) == [], (
        f"{argv[1]} would be launched with {flag} {launched!r}, which is no id a "
        f"writer can have produced")


def _checked_identity(world: World) -> None:
    """The project's git identity, from the page's own Route A config lines.

    Not a fixture identity: the page sets the identity in the section this walk does
    not run, and a harness identity would hide a page that forgot to set one.
    """
    for argv in route_commands(("Route A",)):
        if argv[:2] == ["git", "config"]:
            checked(run_git_config(world, argv, world.project),
                    f"Route A identity line {argv}")


def run_git_config(world: World, argv: list[str],
                   cwd: Path) -> subprocess.CompletedProcess[str]:
    """One ``git config`` line of the page, addressed at ``cwd``.

    The page types these from the project root, where bare ``git config`` reads the
    project's config; the harness's cwd is the scratch project, so the line runs with
    an explicit ``-C`` for that tree and its words otherwise verbatim.
    """
    return git(cwd, *argv[1:], env=world.env)


def launch(world: World, argv: list[str],
           cwd: Path) -> subprocess.CompletedProcess[str]:
    """One golden command, in the topology the page describes.

    Order matters: the argv is a golden one (the caller got it from
    :func:`route_commands`, which compared it), so the moves below are applied to a
    known list, and the program a ``noni`` line names is the console script the
    fixture's install produced.
    """
    assert argv in _ALL_GOLDEN, (
        f"launch() was handed an argv no golden list prints: {argv}")
    if argv[0] == "cd":
        # The one step into a directory the page cannot name: every launched command
        # already runs with the cwd the page's cd would have landed in.
        assert argv == ["cd", READER_DIR], (
            f"the page's cd must name the placeholder for the reader's own "
            f"repository ({READER_DIR}): {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if argv[:2] == ["noni", "intent"]:
        return write_intent_draft(world, argv)
    if argv[0] == "echo":
        return append_ignore_rule(world, argv)
    if argv[0] == "git" and argv[1] == "clone":
        return state_clone(world, argv)
    argv = reroot(substitute(date_arg(world, argv), world.placeholders),
                  world.state)
    program = str(world.noni) if argv[0] == "noni" else argv[0]
    return _exec(program, argv, cwd, world.env)


def _exec(program: str, argv: list[str], cwd: Path,
          env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """One page command under the launch env, with a hang named as the command."""
    try:
        return subprocess.run([program, *argv[1:]], cwd=cwd, capture_output=True,
                              text=True, env=env, timeout=180)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - a hung command
        pytest.fail(f"page command hung: {argv}\n{exc}")


def write_intent_draft(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Put the draft the page's intent line reads onto the reader's disk.

    The page tells the reader to copy the skill's template, fill its four sections
    and hand it over with ``--from``: the harness supplies the file the reader's
    copy step would have produced, at the path the page's own line names, and hands
    the launch the *page's* argv untouched. Two things that leaves honest: the
    writer still reads the path from argv rather than from anything the harness
    chose, and a golden line that drops ``--from`` or points it elsewhere fails
    here rather than launching a run whose input nobody reviewed.

    The draft is the shipped template, not a fixture of this test module: a page
    that installs a draft the writer refuses, or a template that stopped validating,
    fails here -- which is the promise the page makes to a first-time reader.
    """
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


def cwd_draft(world: World, draft: str) -> Path:
    """Resolve the page's draft path against the directory that command runs in.

    The page's line runs in the reader's own repository (the ``cd`` step), so a
    relative path means a file of the project, not of the state clone: the intent
    draft is the reader's own document, and only the artifact the writer commits
    lands under ``--repo``.
    """
    relative = Path(draft)
    assert not relative.is_absolute(), (
        f"the page's --from names an absolute path {draft!r}, which the harness "
        "would have to trust rather than resolve")
    return world.project / relative


def append_ignore_rule(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's ``echo ... >> .gitignore`` line, applied to the scratch tree.

    The payload is taken from the golden list and written to the scratch project's
    ignore file: this repository's own ``.gitignore`` is a gate file, so the line
    cannot be replayed by a shell in the tree the tests run from.
    """
    entry = argv[1].strip()
    assert entry.startswith("/") and entry.endswith("/"), (
        f"the ignore rule is not a rule for a directory: {argv}")
    assert STATE_DIR in entry, f"the ignore rule does not name the state directory: {argv}"
    assert argv[2:] == [">>", ".gitignore"], (
        f"the ignore-rule line writes somewhere other than .gitignore: {argv}")
    (world.project / ".gitignore").write_text(entry + "\n", encoding="utf-8")
    return subprocess.CompletedProcess(argv, 0, "", "")


def state_clone(world: World, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's state-repository clone, run for real against the fixture's origin.

    The page prints two clones and they stand for different things. The install
    section's clone of noni is the fixture's materialised copy (its URL is the
    OWNER placeholder, and the run stays offline); the state section's clone of the
    private repository is launched against the bare origin the fixture seeded, so
    the branch, the upstream and the pushed commits the tests read afterwards are
    the product of the line the page prints.
    """
    if CLONE_URL in " ".join(argv):
        assert argv[2] == "https://github.com/OWNER/noni" and argv[3] == "noni", (
            f"the install clone must name the page's placeholder URL: {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert argv[2].endswith(".git") and argv[3] == STATE_DIR, (
        f"the page's state clone must name the {STATE_DIR} target: {argv}")
    return git(world.project, "clone", "-q", str(world.origin), STATE_DIR,
               env=world.env)
