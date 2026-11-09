"""``order --help`` puts its verb where the docs put it (issue #77, AC1).

Three texts spell the order command and none of them used to be compared with
the others: argparse's rendered ``usage:`` line (built from the parser's own
action order, so a positional declared between two flags is printed behind every
flag), the ``Usage:`` block in ``order.py``'s docstring, and the command block in
``skills/direction/SKILL.md``. The two documents were verb-first
(``order.py --repo REPO add ISSUE --decision ID``); the help line was not, and a
reader copying from ``--help`` got a line that hid the one word they had to
choose.

This module runs the two ``--help`` routes and pins the printed line against
both documents. ``tests/test_order_writer_docs.py`` holds the document half of
the same contract (what the two pages say about the writer); the fixtures in
``tests/order_fixtures.py`` parse the module's docstring, and the shared usage
helpers in ``tests/order_usage_support.py`` read the rendered line, so the two
files cannot drift into two readings of one line.

The refusal-path tests below are the exit-code half of AC4: the fix was a help
formatter and not a parser reshuffle, so the argparse refusals the earlier suite
pinned are re-asserted here unchanged.
"""

from __future__ import annotations

import json
import subprocess

from _harness import (
    REPO,
    _commit_file,
    _git,
    _git_ok,
    _init_repo,
    run_from,
    run_module,
    run_noni,
    run_wrapper,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER,
    ORDER_REL,
    SKILL_DIR,
    _entry,
    _issues,
    _order,
    _order_path,
    _repo,
    _seed,
)
from order_usage_support import (
    VERBS,
    assert_verb_precedes_flags,
    docstring_verb_lines,
    first_usage_line,
    skill_md_verb_lines,
)

# The state root as a Route B reader names it, and the artifact path that form
# produces: --repo joined to the path under the state root, which is the token
# both of this writer's output lines must carry (issue #77, AC2).
STATE_DIR = ".noni-state"
ORDER_TOKEN = f"{STATE_DIR}/{ORDER_REL}"


# --- AC1: the rendered usage line, against the two documents ------------------


def test_order_help_puts_the_verb_ahead_of_the_flags(tmp_path):
    """``scripts/order.py --help`` leads with the verb, not with the flag block."""
    # ``--repo`` is required and argparse prints its usage before honouring
    # --help, so the run names a real (empty of order) tree: the path is an
    # argument the help route never reads.
    proc = _order(_repo(tmp_path), "--help")
    assert proc.returncode == 0, proc.stderr
    assert_verb_precedes_flags(first_usage_line(proc.stdout), "order.py --help")


def test_the_console_route_prints_the_same_verb_first_usage():
    """``noni order --help`` and the wrapper agree byte for byte.

    Both routes share the one parser, so one formatter fix covers both; this is
    the assertion that says so rather than trusting it.
    """
    wrapper = run_wrapper(ORDER, "--help")
    console = run_noni("order", "--help")
    assert wrapper.stdout == console.stdout, (
        f"the two routes' help differ:\nwrapper: {wrapper.stdout!r}\n"
        f"console: {console.stdout!r}"
    )
    assert_verb_precedes_flags(first_usage_line(console.stdout), "noni order --help")


def test_the_rendered_usage_leads_the_flag_block_of_the_docstring_block(tmp_path):
    """The parser's usage line and the module's own ``Usage:`` block agree.

    ``tests/test_order_writer_docs.py`` pins the two halves' *flag sets*; this
    pins the position the verb holds in each, which no existing check read. The
    docstring is read from the shipped source through ``order_fixtures``, so a
    docstring that moved the verb behind the flags fails here and not silently.
    """
    rendered = first_usage_line(_order(_repo(tmp_path), "--help").stdout)
    assert_verb_precedes_flags(rendered, "order.py --help")
    lines = docstring_verb_lines()
    assert len(lines) == 5, f"expected one line per verb plus add --item: {lines}"
    for line in lines:
        assert " --repo REPO " in line, f"Usage line does not name --repo: {line!r}"
        assert_verb_precedes_flags(line, f"docstring Usage line {line!r}")


def test_skill_md_and_the_help_name_the_same_verb_first_form(tmp_path):
    """The two texts a reader copies from say the same thing about the verb.

    The skill's command block is the form the ticket names; the help must lead
    with the same position, and the four verbs it lists are the four the parser
    accepts.
    """
    documented = skill_md_verb_lines()
    assert len(documented) == 5, f"SKILL.md documents {len(documented)} order lines"
    for line in documented:
        assert_verb_precedes_flags(line, f"skills/direction/SKILL.md {line!r}")

    rendered = first_usage_line(_order(_repo(tmp_path), "--help").stdout)
    assert_verb_precedes_flags(rendered, "order.py --help")
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for verb in VERBS:
        assert f"--repo REPO {verb} " in text, f"SKILL.md omits the {verb} verb"


# The verbs the writer accepts, spelled out for the refusal that has to name them.
# ``order_usage_support.VERBS`` is the same set in parser order; the "or" is the
# writer's own sentence, not a join the tests get to choose.
_ACCEPTED_VERBS = "add, move, remove or confirm"


def test_order_help_exits_zero_and_prints_no_traceback(tmp_path):
    """Every usage print of this writer answers, on every Python it runs on.

    The formatter this file's four tests used to exercise called a private argparse
    method, and Python 3.14 removed it: on that interpreter ``--help``, a missing
    subcommand and an unknown flag all died with an ``AttributeError``, so a run
    that only asserted the shape of a line it never got to read was not asserting
    anything (issue #98). The routes and the three usage prints are each run here
    for their documented exit code and a stderr that carries no traceback.
    """
    repo = _repo(tmp_path)
    cases = [
        (run_wrapper, (ORDER, "--help"), 0),
        (run_wrapper, (ORDER, "--repo", str(repo)), 2),
        (run_wrapper, (ORDER, "--repo", str(repo), "--not-a-flag"), 2),
        (run_noni, ("order", "--repo", str(repo), "--help"), 0),
        (run_noni, ("order", "--repo", str(repo)), 2),
        (run_noni, ("order", "--repo", str(repo), "--not-a-flag"), 2),
        (run_module, ("order", "--repo", str(repo), "--help"), 0),
    ]
    for launch, argv, expected in cases:
        proc = launch(*argv)
        assert proc.returncode == expected, (
            f"{argv}: expected {expected}, got {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        assert "Traceback" not in proc.stderr, f"{argv}: {proc.stderr}"


def test_a_missing_verb_still_refuses_with_the_pinned_wording():
    """The parser surface is unchanged and the verbs are still named (issue #98).

    Two halves, one assertion each. The wording and the code are what they always
    were: a ``subparsers`` or ``choices=`` fix would have changed both, and the
    ticket's out-of-scope list forbids either, so this is the evidence the parser
    was not reshaped. The verbs beside the wording are the fix -- before it the run
    named the slot and left the reader to guess the four words that fill it, which
    only the *invalid*-verb refusal said.
    """
    proc = run_wrapper(ORDER, "--repo", str(REPO))
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "the following arguments are required: subcommand" in proc.stderr, (
        proc.stderr
    )
    assert f"choose from: {_ACCEPTED_VERBS}" in proc.stderr, proc.stderr
    assert_verb_precedes_flags(first_usage_line(proc.stderr), "argparse refusal")


# --- AC4: the exit-code regression net the plan names for this file -----------


def test_an_unknown_subcommand_exits_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "shuffle", "7", "--now", NOW)
    assert proc.returncode == 2
    assert "add, move, remove or confirm" in proc.stderr
    assert not _order_path(repo).exists()


def test_a_non_positive_issue_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for token in ("0", "-3", "seven", "1.5", ""):
        proc = _order(repo, "add", token, "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 2, f"{token!r}: {proc.returncode} {proc.stderr}"
        assert "positive integer" in proc.stderr or "expected one argument" in proc.stderr


def test_a_non_ascii_digit_issue_number_exits_two(tmp_path):
    """``str.isdigit`` is True for characters ``int`` will not accept.

    A superscript two is a "digit" to ``isdigit`` and a ``ValueError`` to ``int``,
    so the issue token used to reach ``int(token)`` past the digit check and the
    writer died with a traceback instead of a usage refusal. The token is refused
    before the artifact is opened, and nothing is written.
    """
    repo = _repo(tmp_path)
    for token in ("\u00b2", "\u0667"):
        proc = _order(repo, "add", token, "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 2, f"{token!r}: {proc.returncode} {proc.stderr}"
        assert "positive integer" in proc.stderr, f"{token!r}: {proc.stderr}"
        assert "Traceback" not in proc.stderr, f"{token!r}: {proc.stderr}"
        assert not _order_path(repo).exists(), f"{token!r} wrote the artifact"


def test_a_non_ascii_digit_position_exits_two(tmp_path):
    """``--at`` and ``--to`` obey the token rule an issue number obeys.

    A position is read with the same ``int`` call, so a superscript digit reached
    it past any gate that stopped at ``isdigit`` and the writer raised instead of
    refusing. The two flags are refused with the position's own wording, on the
    order they were handed, and nothing is written.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    for token in ("\u00b2", "\u0667"):
        add = _order(repo, "add", "7", "--at", token, "--decision", BASELINE_ID,
                     "--now", NOW)
        assert add.returncode == 2, f"--at {token!r}: {add.returncode} {add.stderr}"
        assert "--at" in add.stderr and "position" in add.stderr, add.stderr
        assert "Traceback" not in add.stderr, add.stderr
        move = _order(repo, "move", "1", "--to", token, "--now", NOW)
        assert move.returncode == 2, f"--to {token!r}: {move.returncode} {move.stderr}"
        assert "--to" in move.stderr and "position" in move.stderr, move.stderr
        assert "Traceback" not in move.stderr, move.stderr
        assert _issues(repo) == [1, 2], f"{token!r} changed the order"


def test_a_missing_issue_number_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for verb in ("add", "move", "remove"):
        proc = _order(repo, verb, "--now", NOW) if verb != "move" else _order(
            repo, verb, "--to", "1", "--now", NOW)
        assert proc.returncode == 2, f"{verb}: {proc.returncode} {proc.stderr}"
        assert "needs an issue number" in proc.stderr or "expected one argument" in proc.stderr


def test_a_position_outside_the_order_exits_two(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    for flag, value in (("--to", "0"), ("--to", "3"), ("--to", "top")):
        proc = _order(repo, "move", "1", flag, value, "--now", NOW)
        assert proc.returncode == 2, f"{flag} {value}: {proc.returncode}"
        assert _issues(repo) == [1, 2]


def test_a_flag_passed_to_the_wrong_verb_exits_two(tmp_path):
    """A flag that means nothing for the verb it came with is a usage error, not
    a hint the run quietly ignores: each of the three mis-placements is named.

    ``--decision`` belongs to ``add`` and ``move`` and to nothing else (issue #134), so
    the two verbs that neither place an entry nor re-cite one are driven here: a run
    that handed ``remove`` or ``confirm`` a decision would otherwise be a command whose
    extra flag answers nothing, silently."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    cases = [
        ("move", "1", "--to", "1", "--at", "1", "--now", NOW),
        ("remove", "1", "--to", "1", "--now", NOW),
        ("confirm", "--at", "1", "--now", NOW),
        ("confirm", "1", "--decision", BASELINE_ID, "--now", NOW),
        ("remove", "1", "--decision", BASELINE_ID, "--now", NOW),
        ("confirm", "--decision", BASELINE_ID, "--now", NOW),
    ]
    for argv in cases:
        proc = _order(repo, *argv)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert "belongs to" in proc.stderr, f"{argv}: {proc.stderr}"
    # The refusal names the verbs that do own the flag, so a reader is not sent to
    # ``add`` alone when ``move`` answers the question too.
    proc = _order(repo, "remove", "1", "--decision", BASELINE_ID, "--now", NOW)
    assert "add and move own" in proc.stderr, proc.stderr


def test_a_now_that_is_not_a_utc_timestamp_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for bad in ("yesterday", "2026-13-45T00:00:00Z", "2026-10-27T12:00:00"):
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", bad)
        assert proc.returncode == 2, f"{bad!r}: {proc.returncode}"
        assert "--now" in proc.stderr
    assert not _order_path(repo).exists()


def test_an_argparse_failure_exits_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "--not-a-flag")
    assert proc.returncode == 2
    proc = _order(repo)  # --repo is required
    assert proc.returncode == 2


def test_a_repo_that_is_not_a_directory_is_a_fault(tmp_path):
    """A --repo naming no directory is refused before the artifact is read or the
    decision looked up, and nothing is created under the path.

    The refusal is the state-root refusal every other writer makes (exit 2, the
    code a wrong path is: an argument the caller passed, not a fault of the tree
    and not a refusal of the order), and it fires ahead of the citation check so
    the message names the path rather than a record the caller may have spelled
    correctly all along. Nothing is written either way: the run created no tree
    it refused.
    """
    proc = _order(tmp_path / "no-such-repo", "add", "7", "--decision", BASELINE_ID,
                  "--now", NOW)
    assert proc.returncode == 2, proc.returncode
    assert "--repo" in proc.stderr, proc.stderr
    assert "is not a directory" in proc.stderr, proc.stderr
    assert not (tmp_path / "no-such-repo").exists(), "the writer created a tree it refused"


def _code_repo(tmp_path, name: str):
    """A committed git tree holding source and no ``noni/``: the pilot's mistake.

    Built with a commit rather than an empty ``_init_repo`` tree, because that is the
    shape a caller actually points ``--repo`` at (their code repository, where the
    state clone was meant) and the writers' git probes answer differently on a tree
    with no commit at all.
    """
    repo = _init_repo(tmp_path / name)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_file(repo, "README.md", "# a code repository\n")
    _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
    return repo


def test_a_repo_that_holds_no_noni_directory_is_a_fault(tmp_path):
    """A committed git tree with no noni/ is the same fault, and the same exit 2.

    The case above names a path that does not exist, which every state-root test in
    this suite did -- so a directory that exists, is a valid git work tree and simply
    holds no noni/ fell past the is_dir check into the reads and answered "no decision
    record ... is in the ledger" about a repository holding no ledger (issue #120,
    reproduced from the quickstart's Route B block with --repo aimed at the project
    instead of the clone). The contrast cases stay distinct and stay theirs: a tree
    with an empty ledger is exit 4, a noni/ that is not a directory is exit 3, and
    neither of those is this state.
    """
    repo = _code_repo(tmp_path, "code-repo")
    proc = _order(repo, "move", "7", "--to", "1", "--now", NOW)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert str(repo) in proc.stderr, (
        f"the refusal must name the path the caller passed: {proc.stderr}")
    assert "is not a noni state root" in proc.stderr, proc.stderr
    assert "no noni/" in proc.stderr, proc.stderr
    assert "--repo" in proc.stderr, (
        f"the hint must name the flag the caller passed wrong: {proc.stderr}")
    assert "is in the ledger" not in proc.stderr, (
        f"the reads must not answer for a tree with no state root: {proc.stderr}")
    assert not (repo / "noni").exists(), "the writer created a noni/ it refused"


def test_confirm_without_an_issue_creates_nothing_on_a_repo_with_no_noni(tmp_path):
    """confirm is refused on a no-noni/ tree rather than writing an empty order.

    Reproduced on main: confirm with no issue argument planned no change, so it exited
    0 and left a valid empty noni/direction/order.json behind on a tree the caller had
    pointed at the wrong repository -- the first-run write path the rule about which
    verbs may create noni/ has to close, since confirm creates nothing legitimate.
    """
    repo = _code_repo(tmp_path, "code-repo-confirm")
    proc = _order(repo, "confirm", "--now", NOW, "--no-commit")
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "is not a noni state root" in proc.stderr, proc.stderr
    assert not (repo / "noni").exists(), (
        "confirm wrote an empty order.json into a tree that is not a state root")


# --- AC2: this writer's path token, from a relative --repo -------------------


def _state_root(tmp_path, name: str):
    """A project cwd holding one committed baseline record in a nested state clone.

    ``--decision`` is answerable only from the tree the writer is pointed at, so
    the record lives under the state root and the two runs of the pair are
    launched from the project directory with ``--repo .noni-state``: the exact
    shape docs/QUICKSTART.md Route B tells a reader to build, and the one whose
    ``--no-commit`` line the pilot misread as a stray ``noni/``.
    """
    project = tmp_path / name
    project.mkdir(parents=True)
    _git_ok(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text(f"{STATE_DIR}/\n", encoding="utf-8")
    _git_ok(project, "add", ".gitignore")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "ignore the state clone")

    state = project / STATE_DIR
    state.mkdir()
    _git_ok(state, "init", "-q", "-b", "main")
    _git_ok(state, "config", "user.name", "Replay")
    _git_ok(state, "config", "user.email", "replay@fixture.invalid")
    record = state / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({
        "id": BASELINE_ID, "date": f"{BASELINE_ID[:10]}T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Which order?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "ordering", "status": "decided", "supersedes": None,
    }, indent=2) + "\n", encoding="utf-8")
    _git_ok(state, "add", f"noni/decisions/{BASELINE_ID}.json")
    _git_ok(state, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"steering: {BASELINE_ID}")
    return project, state


def _between(text: str, start: str, end: str | None = None) -> str:
    """The token ``text`` carries between two of its own literals.

    Splitting on a separator the surrounding prose also contains (a path carries
    ``/``, the claim line carries ``;``) would cut the token short, so the caller
    names both bounds and the helper takes what lies between them.
    """
    assert start in text, f"{start!r} not in {text!r}"
    tail = text.split(start, 1)[1]
    if end is not None:
        tail = tail.split(end, 1)[0]
    return tail.strip()


def _one_line(stdout: str, label: str) -> str:
    """The single output line carrying ``label``, or the failure that says so."""
    matching = [row for row in stdout.splitlines() if label in row]
    assert len(matching) == 1, f"expected one {label!r} line, got {matching}"
    return matching[0]


def _run_order_ok(cwd, *args: str) -> subprocess.CompletedProcess[str]:
    """``scripts/order.py`` from ``cwd``, whose exit code has to be 0."""
    proc = run_from(cwd, ORDER, "--repo", STATE_DIR, *args)
    assert proc.returncode == 0, (f"{args}: {proc.returncode}"
                                  f"\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    return proc


def test_order_names_the_same_path_committed_and_uncommitted(tmp_path):
    """One relative --repo, two runs, one path token: ``.noni-state/noni/...``.

    The committed line and the ``left uncommitted`` line are the pair the pilot
    read as two files, because the second printed only the artifact's name under
    the state root. The exact match is what forbids that spelling and the
    absolute machine path alike; the writer's own ``wrote`` wording is the
    boundary the token is taken between.
    """
    project, state = _state_root(tmp_path, "order-token")
    committed = _run_order_ok(project, "add", "7", "--decision", BASELINE_ID,
                              "--now", NOW)
    uncommitted = _run_order_ok(project, "add", "8", "--decision", BASELINE_ID,
                                "--now", NOW, "--no-commit")

    committed_line = _one_line(committed.stdout, "committed")
    uncommitted_line = _one_line(uncommitted.stdout, "left uncommitted")
    committed_token = _between(committed_line, "committed ", " (")
    uncommitted_token = _between(uncommitted_line, "wrote ", "; left uncommitted")

    assert committed_token == ORDER_TOKEN, committed_line
    assert uncommitted_token == ORDER_TOKEN, uncommitted_line
    # The two runs really did the two different things the pair is meant to test:
    # one advanced the clone's head, the other left the file unstaged in the tree.
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == [
        f" M {ORDER_REL}"], _git_ok(state, "status", "--porcelain").stdout
    assert (state / ORDER_REL).is_file(), "the --no-commit run wrote no file"
