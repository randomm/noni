"""The quickstart's promises, run for real.

``docs/QUICKSTART.md`` is the page a new team follows when the README's five
minutes are not enough: it carries the install forms (there is no package index
to install from), both state-root routes, the ignore rule, the one-time first
push, the deny-list file and the ``--issue-state`` recipe. The enforcement rule
of ``docs/PRODUCT.md`` §6 says prose is convention, not enforcement, so this
module reads the page as data and runs it. Its prose-only claims -- the install
toolchain, the route-choice clause, the deny-list and prerequisite wording -- are
in ``tests/test_quickstart_promises.py``, which reads the same page through
:mod:`quickstart_page`; the split is the 500-line cap in
``tests/test_file_size_limit.py``, and the seam is the one this module already
drew between reviewing the page and running it.

The harness has two halves, and each answers a different question:

- **Is this the page we reviewed?** :mod:`quickstart_golden` holds a literal list
  of the commands the page prints, per section, in order, and
  :func:`quickstart_runner.route_commands` compares the parsed page against it
  before anything runs. A change to the page is reviewed by updating that list,
  which puts a human on the diff. Placeholders (``<record-id>``,
  ``<session-id>``) and the OWNER URL stay literal tokens in the list, because
  they are what the page prints.
- **Does the page do what it says?** Each test below runs the golden commands in
  the topology the page describes and checks the outcome the page claims: exit 0
  everywhere, one committed record, a census that ends on its verdict line, a
  state clone whose upstream the page's ``-u`` push set, and an origin holding the
  writers' commits.

The page is this repository's own reviewed file, so nothing here defends against
the page: no allow-list of launchable words, no ``git config`` grammar, no push
guard. Those defended against a hostile page and each review round found a new
bypass in them; the golden list makes the question they asked impossible to ask,
because a command that is not in the list is never launched.

The launches run in throwaway trees under ``tmp_path`` with no ambient git state,
exactly like the README try-it harness, and never touch this repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from _harness import REPO
from docs_commands import comment_lines, fenced_blocks, placeholder_words, read
from docs_promises import (
    DENYLIST_STATES,
    QUICKSTART,
    STATE_DIR,
)
from harness_runners import run_noni
from quickstart_gate import (
    GATE_DENYLIST_INACTIVE_EXIT,
    gate_page_sentences,
    run_gate_on_tree_with_no_denylist,
)
from quickstart_golden import COVERED_SECTIONS, GOLDEN
from quickstart_page import ordering_note_from_product, page_text
from quickstart_page_steps import GIT_INFO_EXCLUDE, ignore_rules_written
from quickstart_page_steps import RULE as IGNORE_RULE
from quickstart_runner import (
    World,
    checked,
    git,
    launch,
    route_commands,
    run_route_b,
)

# The harness's must-succeed wrapper, under the short name the assertions below use.
_checked = checked


def _page() -> str:
    return page_text()


# --- Is this the page we reviewed? ------------------------------------------

def test_the_page_prints_exactly_the_golden_commands():
    """The whole page, section by section, equals the literal list in the harness.

    This is the gate that replaced the sandbox defence: the page is our own
    reviewed file, so what the suite enforces is that it has not changed out from
    under the review. The comparison covers every section the harness claims, in
    the order the page prints them, and the fence census below covers the case the
    section list cannot -- a new bash fence under a heading no key selects.
    """
    for label in COVERED_SECTIONS:
        route_commands(label)


def test_no_bash_fence_lives_outside_the_sections_the_golden_list_covers():
    """Every command-bearing fence on the page belongs to a section that is pinned.

    Without this, a fence added under an unlisted heading would be neither compared
    nor launched, and the page could grow a step the suite never runs while every
    test above stayed green.
    """
    from docs_commands import block_commands, fenced_pairs

    printed = [argv for info, lines in fenced_pairs(_page()) if info == "bash"
               for argv in block_commands(lines)]
    listed = [argv for label in GOLDEN for argv in GOLDEN[label]]
    assert printed == listed, (
        f"the page prints {len(printed)} fenced commands and the golden list covers "
        f"{len(listed)}; the difference is a fence no test runs:\n"
        f"  page:   {printed}\n  golden: {listed}")


def test_the_quickstart_page_is_linked_and_within_its_size():
    """The page exists, the README names it by exact path, and it stays short.

    The README's own gate caps that page at 150 lines, so the quickstart earns
    its keep only by being short enough to read after the README: 400 is the
    cap ``tests/test_skill_scrub.py`` sets on a SKILL.md, and this is a page a
    reader is meant to finish.
    """
    assert QUICKSTART.is_file(), "docs/QUICKSTART.md is missing"
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/QUICKSTART.md" in readme, "README does not link the quickstart"
    lines = _page().count("\n")
    assert lines <= 400, f"docs/QUICKSTART.md is {lines} lines; the cap is 400"



def test_no_comment_line_is_a_command_the_page_means_to_run():
    """The comment exemption cannot hide a real command.

    The reader drops lines beginning ``#`` because a shell never runs those. If a
    placeholder of the page's own ever landed inside such a line, the substitution
    would silently stop covering it, so the shape of the block is checked rather
    than trusted.
    """
    for block in fenced_blocks(_page(), info="bash"):
        for line in comment_lines(block):
            assert not placeholder_words(line), (
                f"a placeholder sits in a comment line, which the reader skips: {line!r}"
            )


def test_the_page_names_no_other_interpreter_for_a_shell_wrapper():
    """The bash shims are never shown under ``python3`` on this page.

    ``skills/*/scripts/census.sh`` and ``census-sessions.sh`` are bash scripts;
    the interpreter they exec is their own business. A page that showed
    ``python3 <path>.sh`` would hand the reader a traceback, and the README's
    python3 launches are all ``.py`` entry points. The same rule over every page
    in scope is ``tests/test_docs_invocation.py``; this one is the page whose
    commands are launched here.
    """
    offenders = [line for block in fenced_blocks(_page(), info=None) for line in block
                 if re.search(r"python3?\s+\S*\.sh\b", line)]
    assert not offenders, f"the page runs a shell script under python3: {offenders}"


# --- The page's commands, run ------------------------------------------------

def test_route_a_commands_all_exit_zero(world: World) -> None:
    """Every command of the in-project route runs and exits 0, and the outcome
    the page claims for it is there: one committed record, a census that ends
    with its verdict line, and a project tree the census left clean."""
    commands = route_commands(("Route A",))
    census_lines: list[str] = []
    for argv in commands:
        proc = launch(world, argv, world.project)
        _checked(proc, f"Route A command {argv}")
        if argv[:2] == ["noni", "census"]:
            census_lines = proc.stdout.splitlines()
    assert census_lines, "the Route A block never runs the census"
    assert census_lines[-1].startswith("summary: ") and census_lines[-1].endswith(
        "verdict ok"), f"the census did not end with its verdict line: {census_lines[-1:]!r}"
    records = sorted((world.project / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, f"expected one record, got {[p.name for p in records]}"
    head = git(world.project, "log", "--oneline", env=world.env).stdout
    assert records[0].stem in head, f"the record is not committed: {head!r}"
    dirty = git(world.project, "status", "--porcelain", env=world.env).stdout.splitlines()
    assert dirty == [], f"the documented path left the tree dirty: {dirty}"


def test_route_b_commands_all_exit_zero(world: World) -> None:
    """Every command of the private-state-repo route runs and exits 0.

    This is the route the README cannot carry: a second clone inside the
    project, an ignore rule, a first push, and then the same writers with
    ``--repo .noni-state``. Each of those steps is a place the page can be
    subtly wrong -- a push before the branch exists, an ignore rule that ignores
    the wrong path, a writer pointed at the project instead of the state clone --
    and each is observed here rather than assumed. The two ignore lines are the one
    pair whose effect is not visible in any exit code, so they get a walk of their own
    in :func:`test_the_page_s_pr_only_ignore_rule_actually_hides_the_state_clone`.
    """
    run_route_b(world)

    records = sorted((world.state / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, (
        f"the state route wrote {len(records)} records, not the one the page's "
        f"decide line commits: {[p.name for p in records]}")
    collected = world.placeholders.get("<record-id>")
    assert collected == records[0].stem, (
        f"the id the collector put on the ordering line is not the record the "
        f"decide line wrote: collected {collected!r}, on disk {records[0].name!r}")
    assert (world.project / ".gitignore").is_file(), "the ignore rule was never written"
    assert STATE_DIR + "/" in (world.project / ".gitignore").read_text(encoding="utf-8"), \
        "the ignore rule does not name the state directory"
    status = git(world.project, "status", "--porcelain", env=world.env)
    _checked(status, "project status")
    assert STATE_DIR not in status.stdout, (
        f"the state clone is visible to the project's git, so the ignore rule "
        f"is not doing its job: {status.stdout!r}"
    )
    _checked(git(world.origin, "rev-parse", "--verify", "main", env=world.env),
             "the state branch on the origin")
    # The page promises the first push makes every later push and pull work
    # "without naming the remote again", and `-u` is the whole of that promise.
    # An exit-0 push proves nothing about the tracking branch, so the upstream
    # the clone itself reports is read here: a push that lost its -u would leave
    # the writers' later ``--push`` with no branch to name.
    upstream = git(world.state, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                   "@{u}", env=world.env)
    _checked(upstream, "the state clone's upstream after the page's first push")
    assert upstream.stdout.strip() == "origin/main", (
        f"the page's first push did not set the branch's upstream to origin/main, "
        f"so the later --push runs have no remote-tracking branch: "
        f"{upstream.stdout!r} {upstream.stderr!r}")
    assert [a for a in route_commands(("Route B",))
            if a[:2] == ["noni", "census"]], "the Route B block never runs the census"


def test_the_state_route_leaves_the_origin_holding_the_writers_commits(world: World) -> None:
    """The record the state route writes is reachable on the origin once pushed.

    The page's first-push promise is only worth anything if a later clone of that
    branch sees the ledger; a run that committed locally and never landed anywhere
    would pass the exit-code assertions above.
    """
    run_route_b(world)
    pushed = git(world.origin, "ls-tree", "--name-only", "main", env=world.env)
    _checked(pushed, "origin main tree")
    assert "noni" in pushed.stdout.split(), (
        f"the state branch holds no noni/ directory: {pushed.stdout!r}"
    )
    # The same promise, read off the origin rather than the clone: the remote the
    # clone pushes to is the fixture's origin, nothing redirects that push, and the
    # origin's own main is the commit the clone names.
    url = git(world.state, "config", "--get", "remote.origin.url", env=world.env)
    _checked(url, "the state clone's origin URL")
    assert url.stdout.strip() == str(world.origin), (
        f"the state clone does not push to the fixture's origin: "
        f"{url.stdout!r} {url.stderr!r}")
    pushurl = git(world.state, "config", "--get", "remote.origin.pushurl",
                  env=world.env)
    assert pushurl.returncode == 1 and not pushurl.stdout and not pushurl.stderr, (
        "a pushurl would redirect the page's first push away from the origin these "
        f"tests read: rc={pushurl.returncode} stdout={pushurl.stdout!r} "
        f"stderr={pushurl.stderr!r}")
    origin_main = git(world.origin, "rev-parse", "main", env=world.env)
    state_main = git(world.state, "rev-parse", "main", env=world.env)
    _checked(origin_main, "the origin's main")
    _checked(state_main, "the state clone's main")
    assert origin_main.stdout.strip() == state_main.stdout.strip(), (
        "the clone's main is not the commit the origin holds, so the writers' "
        f"commits are not on the origin: origin {origin_main.stdout.strip()!r} "
        f"clone {state_main.stdout.strip()!r}")


def test_the_ordering_note_appears_in_human_mode_and_not_in_json(world: World) -> None:
    """The page's claim about the ``--json`` stream, observed on the Route A tree.

    The page tells the reader the census says out loud that ``ordering-closed``
    was not evaluated, that no ``note:`` line goes to stdout in ``--json`` mode,
    and that the summary row carries the sentence instead. All three are about
    output, so all three are read from two runs of the same census over the same
    tree. The absence of the line in the ``--json`` run is only worth anything
    next to the positive half in the *same* run: the stream has to parse as
    NDJSON, carry the ordering group's summary row with its ``not_evaluated``
    entry, and reach the verdict the page ends with. An assertion that only
    looked for the note's absence would be satisfied by a census that never read
    anything, which is the vacuity this pins shut.
    """
    for argv in route_commands(("Route A",)):
        _checked(launch(world, argv, world.project), f"Route A command {argv}")

    plain = run_noni("census", "--repo", str(world.project), "--only", "ordering-closed",
                     cwd=world.project, env=world.env)
    _checked(plain, "the plain census run")
    note = ordering_note_from_product()
    assert note in plain.stdout, (
        f"the census does not print the note the page quotes it as printing: "
        f"{plain.stdout!r}")

    as_json = run_noni("census", "--repo", str(world.project), "--only",
                      "ordering-closed", "--json", cwd=world.project, env=world.env)
    _checked(as_json, "the --json census run")
    assert note not in as_json.stdout, (
        f"--json mode prints the note the page says it never prints: "
        f"{as_json.stdout!r}")
    # The page's third claim, in the same run: the sentence is not lost to the
    # mode, it moves to the summary row (issue #97).
    rows = [json.loads(line) for line in as_json.stdout.splitlines() if line.strip()]
    assert rows, f"--json mode printed no stream at all: {as_json.stdout!r}"
    summaries = [row for row in rows if row.get("kind") == "summary"]
    assert len(summaries) == 1, f"no single summary row in the --json stream: {rows}"
    summary, = summaries
    carried = summary.get("not_evaluated")
    assert isinstance(carried, list) and any(note[6:] in line for line in carried), (
        f"--json mode neither printed the note nor carried it on the summary row: "
        f"{summary}")
    assert summary.get("exit") == 0 and summary.get("ok") is True, summary
    assert all(row.get("schema") == rows[0]["schema"] for row in rows), rows
    # The payload has to answer for the ordering group, not just be well-formed:
    # the page tells the reader to keep the group in the run ("``--only`` must
    # name an ordering class, or name none"), and this tree holds no ordering
    # artifact, which the page itself says earns no ordering rows at all. So the
    # honest positive half is the group's own count, present and zero -- a run
    # that had read nothing, or had dropped the class from the run, prints a
    # summary with no such entry, and the absence asserted above would then be
    # true of a stream that never asked the question.
    page = read(QUICKSTART)
    assert "name an ordering class" in page, (
        "the page no longer says the ordering group must stay in the run, so the "
        "count asserted below is unpinned")
    assert "ordering rows at all" in page, (
        "the page no longer says what a tree with no ordering artifact earns from "
        "the ordering group, so a zero count below proves nothing")
    counts = summary["counts"]
    assert isinstance(counts, dict), (
        f"the summary row carries no counts mapping, so the zero below proves "
        f"nothing: {summary}")
    assert counts.get("ordering-closed", 0) == 0, (
        f"a tree with no ordering artifact produced ordering-closed findings: "
        f"{summary}")
    assert not [row for row in rows if row.get("kind") == "finding"], rows


def test_the_deny_list_states_are_named_and_the_gate_refuses_an_inactive_class(
    tmp_path: Path,
) -> None:
    """All three inactive states appear where the deny-list is documented, and the
    gate the page names really refuses to report clean without one.

    ``absent`` and ``corrupt`` are the two a reader guesses; ``present but empty``
    is the one a reader who wrote a file of comments hits and cannot explain from
    the row alone, because the file exists. The words are the product's rendering,
    derived from the two sources that write them, so a rename fails the pages
    (``tests/test_docs_promises.py``) rather than quietly shrinking the set here.

    The second half is the page's exit-code sentence: ``That CLI exits 2 when the
    class was not active, so it cannot report a false "clean"``. The argv is the
    golden DENYLIST command rather than one typed here, and the run happens in a
    throwaway committed tree under ``tmp_path`` rather than in this checkout. The
    gate picks the tree it audits by the wrapper's own location, so a run whose cwd
    is ``REPO`` scans this checkout and its verdict moves with an untracked
    ``.noni-scrub-denylist`` here -- green in CI, red on the operator's machine, for
    one page. :mod:`quickstart_gate` builds the scratch tree and pins the exit.
    """
    quickstart = _page()
    for word in DENYLIST_STATES:
        assert word in quickstart, (
            f"the deny-list section does not name every inactive state: {word!r}")
    gate_page_sentences()
    expected = GATE_DENYLIST_INACTIVE_EXIT
    proc = run_gate_on_tree_with_no_denylist(tmp_path)
    assert proc.returncode == expected, (
        f"the publishing gate reported {proc.returncode} on a tree with no "
        f"deny-list; the page promises {expected}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "deny-list class inactive" in proc.stderr, (
        f"the gate's refusal did not name the class it skipped: {proc.stderr!r}")



def test_the_page_s_pr_only_ignore_rule_actually_hides_the_state_clone(
    world: World,
) -> None:
    """Each ignore line the page prints is launched on its own, then read back from disk.

    Route B prints the same rule twice -- ``echo ... >> .gitignore`` for an ordinary
    project, ``printf ... >> .git/info/exclude`` for a PR-only one -- and the page's
    promise for the second is the reason it exists: a project that cannot take a
    commit to its own ``.gitignore`` still gets the state clone hidden from
    ``git status``. Nothing read that file back, so a payload no shell can render (a
    lone ``%`` is an invalid conversion specification: the reader's step exits 1 and
    writes nothing), a step that truncated the file instead of appending to it, and a
    rule that reached neither file each left the suite green.

    Each line therefore runs into a tree seeded with the reader's own prior rules, and
    the file is read afterwards: the rule has to be there, the reader's lines have to
    still be there, and ``git check-ignore`` -- git's reading of its own files, not
    this suite's pattern matching -- has to name the file the page's line writes.
    Each line runs against a tree holding only its own target file: walked together
    they would collide, because git reports only the first file whose rule matches and
    a PR-only rule that wrote nothing at all would still read as ignored through the
    other variant -- which is the situation a reader on a PR-only project is in, since
    that reader never runs the ``echo`` line.
    """
    reader_lines = ["*.local", "/build/"]
    for target in (".gitignore", GIT_INFO_EXCLUDE):
        argv = _ignore_line_for(world, target)
        _leave_only(world, target)
        _seed_ignore_file(world, target, reader_lines)
        _checked(launch(world, argv, world.project), f"ignore line {argv}")
        written = ignore_rules_written(world)[target]
        for line in reader_lines:
            assert line in written, (
                f"the page's {argv[0]} line destroyed the reader's {line!r} in "
                f"{target}, which is a file the project already owns: {written}")
        assert written.count(IGNORE_RULE) == 1, (
            f"the page's {argv[0]} line did not append {IGNORE_RULE!r} to {target} "
            f"exactly once: {written}")
        _assert_git_ignores_the_state_tree(world, argv, target)


def _leave_only(world: World, keep: str) -> None:
    """Remove every ignore file of the project but ``keep``, as a PR-only reader has it.

    A reader on a branch-protected project never runs the ``echo`` line, so the state
    of their tree is the exclude file and nothing else: leaving the other variant on
    disk during this test would let git satisfy the probe from a file the reader under
    test never wrote.
    """
    for other in (".gitignore", GIT_INFO_EXCLUDE):
        if other != keep:
            (world.project / other).unlink(missing_ok=True)


def _ignore_line_for(world: World, target: str) -> list[str]:
    """The page's one ignore line for ``target``, from the compared golden list.

    Read through :func:`quickstart_runner.route_commands` rather than typed here, so
    the line this test launches is the line the golden list pins and the page prints.
    Exactly one per target: two lines writing to the same file would leave this test
    guessing which of the page's steps a failure belongs to.
    """
    lines = [argv for argv in route_commands(("Route B",))
             if argv[0] in ("echo", "printf") and argv[-1] == target]
    assert len(lines) == 1, (
        f"the page must print exactly one ignore rule for {target}, got {lines}")
    return lines[0]


def _seed_ignore_file(world: World, target: str, lines: list[str]) -> None:
    """The reader's pre-existing rules in one ignore file, before the page's line runs.

    A file with nothing in it cannot show a truncating step: an empty file plus a
    rule reads the same as an existing file plus a rule. The path is created here
    because the page's own step is what the test is about, and a step that could only
    ever succeed against a file the harness made is a step nothing tested.
    """
    path = world.project / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def _assert_git_ignores_the_state_tree(world: World, argv: list[str],
                                       target: str) -> None:
    """One ignore file, on its own, has to hide the state clone from the project.

    The file is left holding exactly what the page's line put in it -- the reader's
    prior rules are dropped, so a pass is the rule the page printed and not a rule the
    harness seeded with a shape git happens to honour.
    """
    path = world.project / target
    only_rule = [line for line in path.read_text(encoding="utf-8").splitlines()
                 if line == IGNORE_RULE]
    path.write_text("".join(f"{line}\n" for line in only_rule), encoding="utf-8")
    probe = world.state / "noni" / "decisions" / "probe.json"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("{}\n", encoding="utf-8")
    relative = str(probe.relative_to(world.project))
    ignored = git(world.project, "check-ignore", "-v", relative, env=world.env)
    assert ignored.returncode == 0, (
        f"git still sees the state clone after the page's {argv[0]} line, so a "
        f"writer's commit would turn up in the project's own status: "
        f"rc={ignored.returncode} out={ignored.stdout!r} err={ignored.stderr!r}")
    assert target in ignored.stdout and IGNORE_RULE in ignored.stdout, (
        f"git ignored the path through a file other than the one the page's "
        f"{argv[0]} line names: {ignored.stdout!r}")
