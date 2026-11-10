"""The README keeps its promises: sections, scripts, gate text and the try-it run.

The README is the one page a team lead reads before attaching noni to a
project, so its claims are product surface. This module reads it the way
``tests/test_gate_wiring.py`` reads the CI workflow and ``pyproject.toml``: as
data, with the assertions standing between the prose and the code.

What is pinned, and why:

- the section order, so the page keeps answering what / why / try it / how in
  the order a first-time reader asks them;
- the size cap, on the same shape as the SKILL.md cap in
  ``tests/test_skill_scrub.py``;
- every path either page names exists in this repository, which is what stops
  the page drifting from the tree;
- the try-it block runs for real, in the topology the page sells: one committed
  record, a census ending clean on its last line with its hygiene scan actually
  run, and a tree still clean afterwards; a second case plants one malformed
  record and asserts the documented failing verdict instead;
- the README links CONTRIBUTING.md, and CONTRIBUTING.md still carries the gate
  commands the CI workflow runs, so the move of that block cannot be a loss.

The hygiene and public-safety classes themselves are tested elsewhere; here the
README only has to stay clean enough for them. Each script the page hands a
reader is pinned to its skill directory at the foot of this file.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from _harness import REPO, _git
from census_report_line import _documented_summary_shape, _summary_parts
from readme_support import (
    _ALLOWED_SHELL,
    _CLEAN_RUN_WARN_ROWS,
    _CLONE_PATH,
    _CLONE_URL_PLACEHOLDER,
    _COVERAGE_DATA_FILE,
    _HYGIENE_NOT_RUN_MARKER,
    _NUMBER_WORDS,
    _READER_DIR_PLACEHOLDER,
    CONTRIBUTING,
    CONTRIBUTING_GATE_COMMANDS,
    EXPECTED_SECTIONS,
    NONI_DIR,
    README,
    README_LINE_LIMIT,
    REQUIRED_TRY_IT_SCRIPTS,
    _argv_for_run,
    _block_words,
    _clone_script,
    _materialise_clone,
    _paths_in,
    _reader_env,
    _reader_repository,
    _readme_text,
    _run_documented,
    _safe_relative,
    _script_name,
    _section,
    _section_of,
)
from readme_tryit import _claim_is_documented, _state_token_claim, _try_it_commands


def test_readme_follows_the_documented_section_order() -> None:
    """The page answers what noni is, why, how to try it, and where it stands,
    in that order, so a first-time reader is not handed a design note."""
    text = _readme_text()
    positions: list[int] = []
    for section in EXPECTED_SECTIONS:
        heading = f"## {section}"
        assert heading in text, f"README.md is missing the section {heading!r}"
        positions.append(text.index(heading))
    assert positions == sorted(positions), (
        f"README sections are out of order: {list(EXPECTED_SECTIONS)} expected"
    )
    assert text.index("# noni") < positions[0], "README does not open with the product"


def test_readme_stays_within_the_line_limit() -> None:
    """The page stays short enough to read in one minute (the ticket's cap)."""
    lines = _readme_text().count("\n")
    assert lines <= README_LINE_LIMIT, f"README.md is {lines} lines; the cap is {README_LINE_LIMIT}"


def test_readme_states_the_purity_rule_near_the_end() -> None:
    """The purity sentence moved to the tail of the page but stayed on it: it
    belongs after the reader knows what noni is, not before.

    The rule is pinned to one section by heading, so a purity sentence planted
    above Status cannot satisfy it from the section further down."""
    text = _readme_text()
    section = _section(text, "Purity")
    lowered = section.lower()
    # The rule itself, not the word: the heading carries the word "purity", so
    # checking for it in the body would pass on an empty section.
    assert "no tickets" in lowered and "no backlog" in lowered, (
        "the Purity section does not state the purity rule"
    )
    assert "project-specific" in lowered, "the Purity section does not state the rule"
    earlier = text[: text.index("## Purity")].lower()
    assert "purity" not in earlier, (
        "the purity rule moved back above the end of the page, where a first-time "
        "reader meets design doctrine before the product"
    )


def test_readme_names_what_the_committed_check_does_not_cover() -> None:
    """The public-repo rule has a half the committed patterns cannot enforce:
    operator names, external project or tool names and hostnames live only in
    the untracked deny-list. The page that is a reader's only route to the rule
    has to say so, or a green committed run reads as a scrub-clean guarantee
    when docs/PUBLISHING.md says it is not one."""
    section = _section(_readme_text(), "Contributing")
    lowered = section.lower()
    assert "deny-list" in lowered, (
        "the Contributing section routes the reader to the scrub checklist "
        "without saying the committed check does not cover names or hostnames"
    )
    assert "hostname" in lowered, "the deny-list-only half of the rule is not named"
    assert "docs/PUBLISHING.md" in section, "the checklist itself is not linked"


def test_readme_counts_the_subcommands_the_console_names() -> None:
    """Every 'noni --help names the N subcommands' sentence states the real
    size of ``cli.TOOLS``.

    The count is prose, so nothing but this check ties it to the dispatch
    table: when a verb is added the page can say 'seven' in one paragraph and
    leave 'five' in another, and both sentences describe the same command.
    """
    from noni import cli

    expected = len(cli.TOOLS)
    # spelled-out or digit, so a page that moves to "7" is pinned the same way.
    stated = re.findall(r"`noni --help` names the (\w+) subcommands", _readme_text())
    assert stated, "the README no longer states the subcommand count at all"
    for word in stated:
        number = _NUMBER_WORDS.get(word.lower(), word)
        assert str(number) == str(expected), (
            f"README says 'noni --help names the {word} subcommands' but "
            f"noni --help names {expected} ({', '.join(cli.TOOLS)})"
        )


def test_readme_links_the_contributing_page() -> None:
    """The dev commands moved to CONTRIBUTING.md and the link stayed behind:
    no test of the old page would notice a silent drop of either."""
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md is missing"
    assert "CONTRIBUTING.md" in _readme_text(), "README.md does not link CONTRIBUTING.md"


def test_contributing_carries_the_gate_commands() -> None:
    """The moved block is the gate CI runs, not a summary of it.

    The commands are read from the CI workflow rather than copied as literals,
    so a gate step that changes there fails here instead of leaving the page
    documenting a gate nobody runs. The comparison is on parsed argv tokens, not
    a substring: ``"." in body`` or ``"-m" in body`` matches anything.
    """
    body = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    for command in CONTRIBUTING_GATE_COMMANDS:
        assert command in contributing, f"CONTRIBUTING.md does not document {command!r}"
        argv: tuple[str, ...] = tuple(shlex.split(command, posix=True))
        if not argv[0].startswith(".venv/bin/"):
            continue  # the venv setup step, which CI does in its own step
        tool, rest = Path(argv[0]).name, argv[1:]
        assert tool and rest, (
            f"gate command {command!r} is not a pinned venv tool with a subcommand; "
            "the token comparison below needs both"
        )
        # CI installs a pinned tool set rather than the project's own extras, so
        # the install step is compared on ``pip install`` alone; the lint and
        # coverage steps are compared on tool plus subcommand, which is what a
        # bare substring would otherwise let a short token (``.``, ``-m``) match
        # by accident.
        compared = rest[:1]
        expected_run = f"{tool} {' '.join(compared)}"
        if tool == "coverage":
            # CI runs the three coverage steps as one shell block, so each sits
            # on its own line rather than after ``run:``.
            expected_run = f".venv/bin/{expected_run}"
        assert expected_run in body, (
            f"CI does not run {expected_run}, which CONTRIBUTING.md documents as "
            f"{command!r}"
        )


def test_contributing_points_the_purity_rule_at_its_scrub() -> None:
    """The scrub pointer belongs with the purity rule it qualifies, not under the
    coverage paragraph: the sentence that used to connect them moved once and
    lost its referent. Pinned by heading, the way the README's purity sentence
    is."""
    section = CONTRIBUTING.read_text(encoding="utf-8")
    purity = _section_of(CONTRIBUTING, "Purity")
    assert "docs/PUBLISHING.md" in purity, (
        "the scrub checklist is not linked from the Purity section, so the reader "
        f"meets the rule here without its enforcement: {section[:80]!r}..."
    )


def test_every_path_the_readme_names_exists() -> None:
    """No command or sentence on either page names a script or file this
    repository does not have, so the page cannot drift from the tree.

    The repository URL on the page's clone line is a placeholder, so the clone
    itself is not executable here: the test materialises it (see
    ``_materialise_clone``) and only the commands that operate on the reader's
    repository are run. Two kinds of token cannot resolve here and are checked
    instead against the file that makes the claim: a placeholder path
    (``<skill>``, or the clone directory inside the placeholder URL) is resolved
    by substituting each skill that exists or by the clone layout, and attached
    state (``noni/...``, ``.venv/bin/...``) has to appear in the skill or config
    that creates it. A traversal token is a failure rather than an existence
    hit: ``skills/../x`` resolves inside this checkout and would satisfy
    ``.exists()`` while handing the reader a path that does not exist in their
    tree."""
    skills = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    missing: list[str] = []
    for doc in (README, CONTRIBUTING):
        body = doc.read_text(encoding="utf-8")
        for token in _paths_in(body):
            if "<" in token:
                if any((REPO / token.replace("<skill>", name)).exists() for name in skills):
                    continue
                missing.append(f"{doc.name}: {token} (no skill matches the placeholder)")
                continue
            if token == _CLONE_PATH and _CLONE_URL_PLACEHOLDER in body:
                # The clone directory under the placeholder clone URL: the
                # scripts under it are checked by the try-it assertions, which
                # run them from the materialised clone.
                continue
            if token == _READER_DIR_PLACEHOLDER:
                # The reader's own repository, named by the block's cd step: the
                # test supplies that tree and runs there.
                continue
            if not _safe_relative(token):
                missing.append(f"{doc.name}: {token} (not a tree-relative path)")
                continue
            if token.startswith("../"):
                # A clone-rooted path: ``..`` has no meaning from this checkout's
                # root, so it is checked where it resolves, as a file of the clone
                # (which is this repository's tracked content).
                if (REPO / _clone_script(["python3", token])).is_file():
                    continue
                missing.append(f"{doc.name}: {token} (no such script in the clone)")
                continue
            if (REPO / token.rstrip("/")).exists():
                continue
            claim = _state_token_claim(token)
            if claim is not None and _claim_is_documented(token, claim):
                continue
            missing.append(f"{doc.name}: {token}")
    assert not missing, f"docs name paths that do not exist: {sorted(missing)}"


def test_try_it_block_names_scripts_that_run() -> None:
    """Every command in the try-it block is a real entry point: a permitted
    git form (the clone, the two identity lines), or an existing noni script run
    under python3 from the clone path the page prints. A bare ``decide.py``
    would satisfy a name-existence check and fail on a real shell, so the
    interpreter and the clone-rooted script path are both part of the
    contract."""
    commands = _try_it_commands()
    ran_a_script = False
    for argv in commands:
        if _block_words(argv) in _ALLOWED_SHELL:
            continue
        assert argv[0] == "python3", (
            f"try-it block runs a program the page may not name: {argv}; "
            "a noni script goes under python3"
        )
        assert len(argv) > 1, f"try-it command names no script: {argv}"
        script = _clone_script(argv)
        target = REPO / script
        assert target.is_file(), f"try-it block names no such script: {argv[1]}"
        # Both scripts the page hands a reader are launched as ``python3
        # <path>``, so neither needs a shebang or the executable bit: census.py
        # carries neither by design (it is launched by path, and loads its own
        # siblings the same way). The launch form, not the file mode, is what the
        # page commits a reader to.
        if Path(script).name == "decide.py":
            assert target.suffix == ".py", f"{argv[1]} is not a Python script"
        ran_a_script = True
    assert ran_a_script, "try-it block runs no noni script"
    named = {_script_name(argv) for argv in commands}
    assert REQUIRED_TRY_IT_SCRIPTS <= named, (
        f"try-it block must record a decision and read the census; it names {sorted(named)}"
    )


def _assert_documented_summary(line: str, expected: str | None) -> int:
    """Check the census's last line against the page's, and return the count it reports.

    Whole-segment equality on the head and the machine tail is the assertion: a
    page that moved ``verdict ok`` into an earlier message, or a census that
    dropped the human verdict word from the final line, would keep two
    independent substring tests green while the line the reader compares against
    had changed. The count between the verdict word and ``verdict ok`` is the one
    part the page leaves open (see ``_CLEAN_RUN_WARN_ROWS``), so it is parsed
    rather than compared and handed back for the caller to tie to the rows above.

    The human word is compared with the page's whenever the page pinned one, so a
    page that says ``clean`` above a run that counted warnings fails here rather
    than reading as all-clear (issue #117). ``expected`` is None when the page
    held that word open as a placeholder, which leaves the shape check to the
    tail; the warn-aware half of the page's promise is held by
    ``test_readme_census_wording.py``.
    """
    reported = _summary_parts(line)
    if expected is None:
        assert reported[3] == "verdict ok", (
            f"the census's summary line is not the all-clear shape the page "
            f"documents: {line!r}"
        )
    else:
        documented = _summary_parts(expected)
        assert reported[0] == documented[0] and reported[3] == documented[3], (
            f"the census's summary line is not the page's: {line!r} != {expected!r}"
        )
        assert reported[1] == documented[1], (
            f"the census's human verdict word is not the page's: {line!r} != "
            f"{expected!r}"
        )
    assert reported[2].isdigit(), f"the summary line carries no finding count: {line!r}"
    return int(reported[2])


def _documented_summary_line() -> str | None:
    """The page's summary line, or None when the page holds its verdict word open.

    The scrape lives in ``census_report_line._documented_summary_shape`` so this
    file and ``test_readme_census_wording.py`` read one rendering of the page
    rather than two that can drift. The line's human word is the page's own, so a
    page that printed ``clean`` above a warn-bearing run differs here from the
    real run it is compared against.
    """
    line, _word, open_count = _documented_summary_shape()
    return None if open_count else line


def _assert_hygiene_ran(lines: list[str]) -> None:
    """The census ran its hygiene checker: no row of this run says it did not.

    ``hygiene scan`` is the subject the census gives the row it emits when
    ``scripts/public_safety.py`` is missing, unloadable, or the tree is not a
    git repository. Asserting its absence is what makes the run proof that the
    checker was present: a planted or missing checker, or a --repo the census
    cannot resolve, fails here rather than reading as a clean summary.
    """
    not_run = [line for line in lines if _HYGIENE_NOT_RUN_MARKER in line]
    assert not not_run, (
        "the documented run reports its hygiene scan as not run, so the tree is "
        f"not the topology the page sells: {not_run}"
    )


def test_the_documented_try_it_path_works(tmp_path: Path) -> None:
    """The README's own commands, run verbatim against a materialised noni clone
    and a separate scratch repository, produce what the page promises: one
    committed record, a census whose last line is the documented summary with
    its hygiene scan actually run, and a tree that stays clean afterwards.

    The topology is the documented one: the scripts come from the clone the page
    clones, ``--repo .`` names the reader's own repository (the commands' cwd),
    and nothing is installed in that repository beforehand. That is the only
    shape in which the promise can break, and the only one whose census output a
    reader can compare to the page.

    What the run's lines *say* -- the warn-aware wording of the summary line and
    the headline above warn rows -- is ``test_readme_census_wording.py``'s; this
    test covers the commands, the record and the tree (issue #117 split them so
    each page promise is held in one place).
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
    summary_line = _documented_summary_line()
    env = _reader_env()

    for argv in _try_it_commands():
        cmd = _argv_for_run(argv, clone, repo)
        proc = _run_documented(cmd, repo, env)
        assert proc.returncode == 0, (
            f"documented command failed ({proc.returncode}): {argv}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        if _script_name(argv) == "census.py":
            lines = proc.stdout.splitlines()
            assert lines, f"the census printed nothing: {argv}"
            _assert_hygiene_ran(lines)
            reported = _assert_documented_summary(lines[-1], summary_line)
            # Every row the summary counted must appear above it, by class word:
            # a count that did not come from the rows would be a number the page
            # invented.
            for row_class in _CLEAN_RUN_WARN_ROWS[:reported]:
                assert any(row_class in line for line in lines[:-1]), (
                    f"the summary counted {reported} finding(s) but no row names "
                    f"{row_class!r}:\n{proc.stdout}"
                )

    records = sorted((repo / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, f"expected one committed record, got {[p.name for p in records]}"
    assert records[0].read_text(encoding="utf-8").strip(), "the record is empty"
    head = _git(repo, "log", "--oneline", "--format=%s").stdout
    assert records[0].stem in head, (
        f"the record is not committed: HEAD subjects are {head!r}"
    )
    # The whole tree, because that is the page's promise: a ``-- noni`` scope
    # would permit untracked state anywhere else in the reader's tree, which is
    # precisely what "it never writes" rules out. One class of file is excluded,
    # and the exclusion is named rather than scoped around: when the suite runs
    # under the documented gate, each launched interpreter writes coverage's own
    # ``.coverage.<host>.pid<pid>.*`` data file into the tree it ran in. Those
    # are the harness measuring the product, not the product writing, and they
    # are matched by a pattern anchored at the file's own start so no product
    # output can hide behind them.
    dirty = [line for line in _git(repo, "status", "--porcelain").stdout.splitlines()
             if not _coverage_data_line(line)]
    assert dirty == [], (
        "the documented path left the reader's tree dirty, which contradicts the "
        f"page: {dirty}"
    )


def _coverage_data_line(porcelain_line: str) -> bool:
    """True when one porcelain row names a coverage data file, not a product file.

    Only an untracked (``??``) row at the tree's top level counts: a modified or
    staged entry, or anything inside ``noni/`` or ``skills/``, is never coverage's
    and so is never excused here.
    """
    if not porcelain_line.startswith("?? "):
        return False
    path = porcelain_line[3:].strip().rstrip("/")
    return "/" not in path and bool(_COVERAGE_DATA_FILE.match(path))


def test_the_try_it_census_reports_a_failure_it_found(tmp_path: Path) -> None:
    """The documented census command also has to fail honestly.

    The page sells the census's "honest exit codes", and the clean-run test above
    pins only the exit-0 half, so a regression that turned a finding into a clean
    verdict would pass it. One malformed record is planted in the same
    scratch tree and the same census command from the block is run against it, so
    the failing rendering (non-zero exit, a fail verdict line, the class word and
    the row's own subject) is observed rather than assumed.
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
    decisions = repo / "noni" / "decisions"
    decisions.mkdir(parents=True)
    # The eight required fields of the record schema; this one carries none of
    # them, so the class that reports a record that is not the artifact fires.
    (decisions / "2026-10-01-not-a-record.json").write_text("{}\n", encoding="utf-8")

    census = [argv for argv in _try_it_commands() if _script_name(argv) == "census.py"]
    assert census, "the try-it block does not run the census"
    proc = _run_documented(_argv_for_run(census[0], clone, repo), repo, _reader_env())
    assert proc.returncode != 0, (
        f"a malformed record did not fail the census: rc={proc.returncode}, "
        f"stdout: {proc.stdout}"
    )
    lines = proc.stdout.splitlines()
    assert lines and lines[-1].startswith("summary: ") and lines[-1].endswith("; verdict fail"), (
        f"the failing run did not end with a fail verdict line: {lines[-1:]!r}"
    )
    assert any("ledger-record" in line and "2026-10-01-not-a-record.json" in line
               for line in lines), (
        f"the malformed register file was not reported by name: {proc.stdout}"
    )


@pytest.mark.parametrize("tool,where", (
    ("decide.py", "steering-ledger"),
    ("census.py", "steering-ledger"),
))
def test_the_try_it_scripts_are_where_the_readme_says(tool: str, where: str) -> None:
    """Each script the page hands a reader sits in the skill directory the page
    implies, where a clone checks it out.

    ``census.py`` is the case worth naming: the ledger wrapper and the unified
    census's own script share the name, one per directory
    (``skills/census/scripts/census.py`` is the arbiter), so the check is the
    location the page sells and not uniqueness of the name under ``skills/``.
    """
    assert (REPO / "skills" / where / "scripts" / tool).is_file(), (
        f"skills/{where}/scripts/{tool} is missing")
