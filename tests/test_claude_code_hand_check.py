"""The hand check the Claude Code page prints, launched rather than read.

The page's "Verifying it" section is the only proof a reader has that the wiring
works: the adapter ships no script, so there is no failure line to look at and no
``/hooks`` screen to open. That makes the fence the one part of the page that has
to be *run* to be checked. Every test here takes the fence's own bytes out of the
page, hands them to ``/bin/sh``, and asserts on what came back.

Why this is a separate module from ``test_claude_code_hook.py``: that file checks
the block a reader pastes and the copy around it, and reads the page to do it. A
block that lexes is not a block that works -- the page shipped for an issue's
lifetime a hand check that could not print a page, because every reader who
checked it read it instead of running it. Running is a different kind of check, it
needs a shimmed ``noni`` on ``PATH`` and a planted tree, and the two suites fail
for different reasons.

Two rules the whole module keeps. Nothing here types a sentence the brief prints:
the standing rules come from ``noni.brief``, the planted page's content from the
brief suite's own fixture, and the empty-state sentences from the Codex suite's
constant, so a reworded tool reddens these checks rather than letting them agree
with a page about bytes no tool prints. And every command launched is the fence's
own text, read out of the page by ``claude_code_hook_source``, so a page that
quietly changed its hand check fails here instead of passing a check that was
written against the old one.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from claude_code_hook_source import (
    BASH_FENCE,
    BRIEF_COMMAND,
    EXPORT_COMMAND,
    VERIFY_HEADING,
    broken_hand_check_script,
    empty_state_root_script,
    hand_check_script,
    not_a_directory_script,
    page,
    verify_argv,
    verifying_body,
)
from codex_hook_source import EMPTY_STATE_ROOT_SIGNALS
from docs_promises import STATE_DIR
from harness_runners import subprocess_env
from quickstart_page import flowed_section


def _run_shell(script: str, cwd, path_dir, *, census=None) -> subprocess.CompletedProcess:
    """Run a shell script the page prints, with a ``noni`` shim on ``PATH``.

    One runner for every command this suite launches in a shell, so the harness is
    stated once: ``/bin/sh -c`` (a reader's hook runs under their own shell, and
    ``sh`` is the one every documented command is valid in), the working directory
    the caller names, an environment that starts from the suite's stripped one with
    ``CLAUDE_PROJECT_DIR`` deliberately absent (the page's job is to set it, so a
    value supplied here would let an export that stopped working pass unnoticed), and
    a ``bin`` holding the shim the launched ``noni`` resolves to.

    The shim answers to two shapes. By default it execs the real ``noni`` module, the
    command the page prints and the only thing an ordinary reader runs. With
    ``census`` given it first looks for that script and, finding it, execs it in the
    arbiter's place: the one route to the state where the census prints no verdict
    line, which no tree can be planted into (see
    :func:`_arbiter_without_a_reading_tool`).

    The shim is written here rather than passed in, and every caller passes a fresh
    ``path_dir``, because a shim left where the next test looks would make that run
    inherit this one's arbiter.
    """
    shim_dir = path_dir
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "noni"
    body = ""
    if census is not None:
        body = (f'if [ -f "{census}" ]; then exec "{sys.executable}" "{census}" '
                '"$@"; fi\n')
    shim.write_text(f'{body}#!/bin/sh\nexec "{sys.executable}" -m noni.cli "$@"\n',
                    encoding="utf-8")
    shim.chmod(0o755)

    env = subprocess_env()
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True,
                         cwd=str(cwd), env=env, timeout=120)


def _standing_rules() -> str:
    """The three sentences a page that printed anything must open with.

    Read out of ``noni.brief.STANDING_RULES``, the one place the tool spells them,
    and never restated here: a reworded brief fails this suite rather than letting it
    go on asserting yesterday's page. (The pi hook's ``REMINDER`` carries the same
    three rules in the harness's own voice, and is compared to the hook's output in
    ``test_the_per_turn_command_prints_pis_reminder_byte_for_byte``; the brief's own
    text is what the hand check prints, so that is what the checks below pin.)
    """
    from noni.brief import STANDING_RULES
    return "\n".join(STANDING_RULES)


def _planted_tokens() -> tuple[str, ...]:
    """The words only a planted tree can print, read from the fixture that plants it.

    The order's own issue numbers are derived (``#1``, ``#2``) and too short to prove
    anything, so the proof is the record id the fixture names and a purpose line it
    wrote -- both read from that module rather than typed, so a fixture that stopped
    seeding them fails here instead of leaving this satisfied by an empty page.
    """
    import brief_fixtures
    return (brief_fixtures.RECORD_ID, brief_fixtures.PURPOSE_LINES[0])


def _plant(project, *, name: str = STATE_DIR):
    """A state root holding a real page, at the path the page documents.

    Built by the brief suite's own fixture, so the purpose prose, the record id and
    the order entry are values that suite owns and this one reads.
    """
    import brief_fixtures
    return brief_fixtures.plant_brief_tree(Path(project), name=name)


def test_the_verifying_fence_is_two_statements_and_nothing_else() -> None:
    """The fence a reader copies is the export and the block's own command, as argv.

    This is the fix the issue records, pinned as bytes. A shell expands the whole of a
    command line before an assignment written on that line takes effect, so
    ``CLAUDE_PROJECT_DIR="$PWD" noni brief --repo "$CLAUDE_PROJECT_DIR/.noni-state"``
    on one line hands the reader ``--repo /.noni-state``: an empty page, a silent
    exit, and a wiring that looks fine. The page is only correct when the assignment
    is a statement of its own, which is what :func:`verify_argv` pins before any of
    the executing checks below can run.
    """
    assert verify_argv(page()) == [EXPORT_COMMAND, shlex.split(BRIEF_COMMAND)]


def test_the_hand_check_runs_and_prints_the_brief(tmp_path) -> None:
    """The page's command, run as printed, exits 0 and prints the standing rules.

    The check the issue's first finding is about: the hand check had to be run to be
    known to work, and it had never been run. So the fence's exact bytes go to a
    shell whose ``noni`` resolves to the real package, over a project whose state
    root holds a planted page, and the assertion is on what came back -- exit zero
    and the reminder's own three sentences.

    The same run is performed with the one-line form the page used to carry, and that
    one must fail to print a page: it is the proof that the export line the page now
    ships does the work the prose claims, rather than the check passing for a reason
    that has nothing to do with the anchor.
    """
    project = tmp_path / "project"
    _plant(project)
    good = _run_shell(hand_check_script(page()), project, tmp_path / "bin")
    assert good.returncode == 0, (
        f"the page's own hand check exited {good.returncode}: {good.stderr!r}")
    assert _standing_rules() in good.stdout, (
        f"the hand check printed no standing rules: {good.stdout!r}")

    broken = _run_shell(broken_hand_check_script(), project, tmp_path / "broken-bin")
    # The falsifier has to be the bug the issue names, not merely a run that printed
    # no page: an empty variable is only proven when the refusal says which path it
    # was handed. Asserting the absence of the rules alone would stay green for a
    # command that failed for an unrelated reason, or for a page whose one-line form
    # had quietly grown an argument of its own.
    assert broken.returncode == 2, (
        f"the one-line form the page used to carry exited {broken.returncode}, not "
        f"the refusal this suite exists to pin: {broken.stderr!r}")
    assert "--repo /.noni-state" in broken.stderr, (
        "the one-line form did not reach the root an empty variable makes of it, so "
        f"the anchor stopped being the thing under test: {broken.stderr!r}")
    assert _standing_rules() not in broken.stdout, (
        "the one-line form the page used to carry printed a real page, which means "
        f"the anchor stopped mattering: {broken.stdout!r}")


def test_the_hand_check_names_the_empty_state_root_signals(tmp_path) -> None:
    """The two sentences the page points a reader at that a tree can produce.

    The page tells a reader not to read the exit code as the signal and names three
    sentences to look for instead, so this runs the fence itself -- one token of its
    ``--repo`` argument swapped for the same path under ``$PWD``, so the root tested
    sits where the page says a project's state root sits -- against a tree that holds
    a ``.noni-state`` with no direction in it, and asserts both halves of the claim:
    the exit is zero and the sentences are on the page.

    Which trees that is is settled by the page's own words rather than by taste: a
    root that exists with no ``noni/`` under it, and an empty directory is the
    smallest tree that is that case -- a hand check has to tell a wrong root from a
    project that merely has not steered yet, and a planted fixture tree would blur
    the two into one. The standing rules are the tool's own.

    The third sentence the page names is the arbiter's, and no tree prints it, so it
    is asserted in
    :func:`test_the_hand_check_reports_a_census_that_reached_no_verdict` rather than
    here; skipping it in this loop is that split, not an omission.

    The sentences come from the Codex suite's constant, so the two adapter pages owe
    one set of words and cannot each pin their own. Asserting a non-zero exit here
    would be the false claim this issue exists to remove, which is why the exit is
    pinned at zero.
    """
    project = tmp_path / "project"
    project.mkdir()
    (project / STATE_DIR).mkdir(parents=True)
    planted = _run_shell(empty_state_root_script(page()), project,
                         tmp_path / "bin")
    assert planted.returncode == 0, (
        f"a state root that exists exited {planted.returncode}, which is what the "
        f"page used to claim and no longer does: {planted.stderr!r}")
    assert _standing_rules() in planted.stdout, (
        f"the empty page printed no standing rules: {planted.stdout!r}")
    for signal in EMPTY_STATE_ROOT_SIGNALS[:2]:
        assert _block(signal) in planted.stdout.splitlines(), (
            f"the page names {signal!r} as a sentence a wrong state root prints, "
            f"but no line of the run read {signal.partition(': ')[2]!r}: "
            f"{planted.stdout!r}")


def test_the_hand_check_reports_a_census_that_reached_no_verdict(tmp_path) -> None:
    """``summary: not-run`` is the page's third sentence, and the tool prints it.

    The page tells a reader to look for the line the brief prints when the arbiter
    never judged the tree. No planted tree puts the tool in that state -- the census
    renders a verdict for any directory that exists -- so the state has to be built,
    and it is built the real way: the census reads history through ``git``, names that
    tool as required, and returns without a verdict when the reading machine has none
    (the refusal the census suite already pins). So the page's own command is launched
    unchanged through a shell over a planted tree, with the arbiter's reading tool
    taken away.

    The assertion is both halves of the page's reassurance: the brief still exits 0,
    still prints the standing rules, and says in its own words that it got no verdict.
    No verdict word is typed in this file -- the line is compared against the same
    constant the Codex page's own check reads, so neither adapter page can keep a
    sentence of its own about a line no tool prints.

    The seam is a script rather than a ``monkeypatch`` because the run under test is a
    launched process: the ``noni`` the child imports is a different module object from
    this one's, and a patch put here would leave the reader's run untouched and the
    check green while it tested nothing.
    """
    project = tmp_path / "project"
    _plant(project)
    launched = _run_shell(empty_state_root_script(page()), project,
                         tmp_path / "arbiter-bin",
                         census=_arbiter_without_a_reading_tool(
                             tmp_path / "arbiter-bin"))
    assert launched.returncode == 0, (
        f"a brief whose arbiter reached no verdict exited {launched.returncode}, "
        f"which would make the page's reassurance a lie: {launched.stderr!r}")
    assert _standing_rules() in launched.stdout, (
        f"the brief stopped printing its rules when the arbiter reached no verdict: "
        f"{launched.stdout!r}")
    # Compared as a prefix, not against the shared constant whole: the Codex page
    # quotes the brief's refusal line in full (`summary: not-run; 0 finding(s);
    # verdict fail`, the whole of ``brief.NOT_RUN_SUMMARY``) while this page quotes
    # its opening clause, which is what a reader learns to grep for. The stand-in
    # arbiter prints no verdict at all, so whatever the line is, it is the brief's own
    # sentence and not this file's; pinning the constant here would assert the Codex
    # page's wording against this page's check.
    assert any(line.startswith(EMPTY_STATE_ROOT_SIGNALS[2])
               for line in launched.stdout.splitlines()), (
        f"the page points a reader at {EMPTY_STATE_ROOT_SIGNALS[2]!r}, which the "
        f"brief prints when the arbiter reaches no verdict: {launched.stdout!r}")


def test_the_hand_check_exits_two_only_for_a_root_that_is_no_directory(tmp_path) -> None:
    """The half of the page's exit-code claim that is not zero.

    The paragraph is a pair, and a suite that checked only the zero half would let a
    page that promised 2 for everything pass. So the same fence, export included, is
    pointed at a path that is not a directory, and the exit must be the refusal the
    page names -- with no page on stdout, which is what makes the two cases
    distinguishable to a reader who is standing at exactly that fork.
    """
    project = tmp_path / "project"
    project.mkdir()
    missing = tmp_path / "no-such-root"
    refused = _run_shell(not_a_directory_script(page(), str(missing)), project,
                        tmp_path / "refused-bin")
    assert refused.returncode == 2, (
        f"the page reserves exit 2 for a --repo that is no directory at all, and "
        f"pointing the fence at {missing} exited {refused.returncode}: "
        f"{refused.stdout!r} {refused.stderr!r}")
    assert _standing_rules() not in refused.stdout, (
        f"a refused root printed a page, so a reader could not tell the two states "
        f"apart from the output alone: {refused.stdout!r}")


def test_the_hand_check_prints_a_planted_projects_own_page(tmp_path) -> None:
    """The same fence, run where the page says the state lives, prints that tree.

    The reader's question is not "does noni run" but "does the hook print my
    project's page", so the fixture is the brief suite's planted tree -- purpose,
    records, a live order entry -- at the path the page documents, and the assertion
    is on content only that tree could print: the record id the fixture wrote and a
    purpose line it wrote, both read from that fixture's own constants so a fixture
    that stopped seeding them fails here rather than leaving this satisfied by an
    empty page.
    """
    project = tmp_path / "project"
    _plant(project)
    result = _run_shell(hand_check_script(page()), project, tmp_path / "bin")
    assert result.returncode == 0, (
        f"the hand check exited {result.returncode}: {result.stderr!r}")
    for token in _planted_tokens():
        assert token in result.stdout, (
            f"the planted page was printed without {token!r}: {result.stdout!r}")


def test_the_verifying_section_states_the_exit_rule_and_the_headless_check() -> None:
    """The prose around the fence states the two things a reader cannot see in it.

    The fence shows a command; it cannot show what a wrong root does, or what to do
    with no terminal. So the page owes two sentences, and they are checked where a
    reader will look for them -- in the verifying section, as prose, with the fences
    cut so no code block can answer for a sentence: that the exit code is not the
    signal (an existing root with no direction exits 0, and only a root that is no
    directory exits 2), and that the check is runnable with no interactive session
    through the brief's own ``--repo``.

    The second is the issue's fourth finding: a headless harness run prints no
    reader any notice that a hook failed, and no page said how to check the wiring
    without a screen.
    """
    body = verifying_body(page())
    prose = "\n".join(line for line in body.splitlines() if not line.startswith("```"))
    flowed = " ".join(prose.split())
    for clause, why in (("still exits 0",
                         "the section does not say a state root holding no noni/ "
                         "exits 0, which is the sentence that stops a reader taking "
                         "a silent exit code for a broken hook"),
                        ("exits 2",
                         "the section does not name the one state that earns a "
                         "refusal, so a reader has no way to tell a wrong root from "
                         "an unreadable one"),
                        ("no interactive session",
                         "the section gives a reader with no terminal no way to "
                         "check the wiring")):
        assert clause in flowed, why
    assert "noni brief --repo <root>" in flowed, (
        "the headless guidance names no command a headless reader can run")
    assert BASH_FENCE and "```" + BASH_FENCE in body, "the fence itself is gone"


def test_the_verifying_section_names_the_empty_state_root_signals() -> None:
    """Every signal the Codex page's constant holds is on this page too, in its own words.

    The two adapter pages tell a reader the same thing about the same tool, so they
    owe one set of words: this check imports :data:`EMPTY_STATE_ROOT_SIGNALS` from
    the Codex suite rather than restating it, so a page that dropped or reworded one
    signal reddens here instead of quietly keeping a sentence of its own about a line
    no tool prints. Each is looked for in this page's own "Verifying it" section, and
    nowhere else on the page -- a signal that wandered into another heading is not the
    reassurance a reader running the hand check is looking for. Line wrapping is
    collapsed before the search, so the pin is on the words and not on where the page
    happened to break them.

    The section also owes the exit rule the signals exist to replace: an existing
    directory with no ``noni/`` exits 0, and only a root that is no directory at all
    exits 2. Both halves are pinned, because a page that said only the first would
    leave a reader trusting the exit code they were warned about.
    """
    flowed = flowed_section(VERIFY_HEADING, page())
    for signal in EMPTY_STATE_ROOT_SIGNALS:
        assert signal in flowed, (
            f"the Verifying it section does not name {signal!r}, what the brief "
            "prints for a state root that holds no direction")
    assert "still exits 0" in flowed, (
        "the section does not say that an existing directory with no noni/ still "
        "exits 0, which is the sentence that stops a reader taking a silent exit "
        "code for a broken hook")
    assert "only a" in flowed and "exits 2" in flowed, (
        "the section does not reserve exit 2 for a root that is no directory at all")


def _block(signal: str) -> str:
    """One of the page's three empty-state sentences, rendered the way the tool renders it.

    The Codex page quotes the sentences with a colon -- ``Purpose: not readable``,
    ``top 10: the order is empty`` -- which is how a sentence about a block is written
    in prose. The brief has no colon: it prints the header on its own line and the
    fixed word beneath it (``brief._purpose_block``, ``brief._order_block``, each
    ``[HEADER, NOT_READ]`` or ``[HEADER, EMPTY_ORDER]``). So the sentence a check has
    to find is the constant's own words, read off the colon, sitting on a line of
    their own. A colon added to this suite's copy would satisfy the check with bytes
    no tool prints, which is the same delusion the Codex page's own check guards
    against.
    """
    return signal.partition(": ")[2] if ": " in signal else signal


def _arbiter_without_a_reading_tool(path_dir) -> Path:
    """A stand-in arbiter for a reading machine with no ``git``, as a script path.

    The page tells a reader to look for the sentence the brief prints when the arbiter
    never judged the tree, and no tree puts the census in that state. The real route
    there is the census's own refusal: it reads history through ``git``, names the
    tool as required, and returns without printing a verdict when the reading machine
    has none (``census_run``, beside its ``git not found`` line). This program takes
    that tool away through the seam the census asks the question at -- the module's
    own ``shutil.which``, the same one the census suite uses to pin that refusal --
    and then hands the page's whole command line to the real console dispatch, so
    every byte of the brief the reader sees is the product's.

    It prints nothing of its own and holds no verdict word: the sentence the check
    below looks for is printed by the brief or not at all.

    The seam is a script rather than a ``monkeypatch`` because the run under test is a
    launched process, whose ``noni`` is a different module object from this one's; a
    patch put here would leave the reader's run untouched and the check green while it
    tested nothing.
    """
    path_dir.mkdir(parents=True, exist_ok=True)
    script = path_dir / "arbiter-no-git.py"
    script.write_text(
        "import sys\n"
        "import noni.census_run as census_run\n"
        "census_run.shutil.which = lambda name: None\n"
        "from noni.cli import main\n"
        "raise SystemExit(main(sys.argv[1:]))\n",
        encoding="utf-8")
    return script


