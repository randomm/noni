"""``order confirm`` with no issue refuses; confirming the whole order needs ``--all``.

A bare ``order confirm`` used to read as "restamp every entry". Twice that run was
made by somebody who only wanted to see the queue, and both times the flattened
``confirmed`` times were committed and pushed. The fix is small and it is in one
place: a confirm that names no issue is a usage error, and the whole-order restamp
is reachable only through an explicit ``--all``.

What this module pins, in the order the run meets them:

- the bare form refuses at the writer's usage code (2) and the refusal names both
  halves of the answer: that every entry needs ``--all``, and how to read the order
  without writing it;
- the refusal happens on argv alone -- before the state root is asked about, before
  the artifact is opened, and before any git call -- so a refused run creates no
  ``noni/``, opens no malformed file and moves no HEAD;
- ``confirm --all`` is the old bare confirm byte for byte, including the commit
  subject ``direction: confirm all``, and ``--no-commit`` keeps its contract;
- ``--all`` is ``confirm``'s flag alone, and it is refused beside an issue number in
  either order; which sentence refuses the flag-first order is the interpreter's, so that
  half pins the code and the untouched state and not the wording (see the test);
- the unknown-verb fix line offers only confirm forms the parser actually takes.

The wording is asserted from the product's own constants rather than a copy typed
here, the way ``tests/order_race_fixtures.py`` pins the guard's refusals: a test that
retyped the sentence would keep passing after the sentence drifted.
"""

from __future__ import annotations

import subprocess

from _harness import (
    run_module,
    run_noni,
    run_wrapper,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER,
    ORDER_REL,
    STAMP,
    _assert_census_clean,
    _entry,
    _order,
    _order_module,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
)

from noni import order_plan

# The whole-order flag, asked of the module that declares it rather than spelled here:
# a test that typed "--all" would keep passing if the flag were renamed.
ALL = order_plan.ALL_FLAG

# The two halves of the refusal, taken from the product's own wording (see the module
# docstring). The headline says what the run refused to do; the fix line names the
# read-without-writing route the operator was really after.
REFUSAL_HEADLINE = order_plan.BARE_CONFIRM[0]
READ_WITHOUT_WRITING = order_plan.BARE_CONFIRM[1]
ALL_WITH_ISSUE_HEADLINE = order_plan.ALL_WITH_ISSUE[0]


def _git_out(repo, *args: str) -> str:
    """One git call whose answer is stdout, asked of git rather than the writer."""
    from _harness import subprocess_env

    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, env=subprocess_env(),
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _head(repo) -> str:
    """HEAD's commit id: read from git, not through the code under test."""
    return _git_out(repo, "rev-parse", "HEAD")


def _subject(repo) -> str:
    """HEAD's commit subject without the writer's digest suffix.

    The verb word is what this assertion is about; the digest over the written bytes
    is the next fixture's business and would make every seed change this line.
    """
    return _git_out(repo, "log", "-1", "--format=%s").split(" [")[0]


def _seeded(tmp_path, name: str):
    """A tree holding three entries at three distinct confirmed stamps.

    Three, not two, and deliberately unequal: a run that flattened the queue changed
    every one of the three bytes, and a fixture whose entries already agreed with the
    run's stamp would let the destructive run take the writer's no-change shortcut and
    commit nothing -- the test would then be asserting the absence of a write that was
    never going to happen.
    """
    repo = _repo(tmp_path, name)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-02T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-03T00:00:00Z"))
    return repo


# --- the bare confirm refuses -------------------------------------------------


def test_a_bare_confirm_refuses_at_two_and_leaves_the_order_and_git_alone(tmp_path):
    """The reproduction the ticket was filed from, run against the fix.

    Every ``confirmed`` byte survives and HEAD does not move: the pre-fix run exited
    0, flattened all three entries to its own stamp and committed the result.
    """
    repo = _seeded(tmp_path, "bare")
    before = _order_path(repo).read_bytes()
    head_before = _head(repo)
    porcelain_before = _porcelain(repo)

    proc = _order(repo, "confirm", "--now", NOW)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert _order_path(repo).read_bytes() == before, "a refused confirm rewrote the order"
    assert _head(repo) == head_before, "a refused confirm committed"
    assert _porcelain(repo) == porcelain_before, (
        f"a refused confirm left the tree dirty: {_porcelain(repo)!r}")
    # The success signal is the printed order and the committed line; neither may
    # appear on a run that planned nothing.
    assert "order.json (" not in proc.stdout, proc.stdout
    assert "committed" not in proc.stdout, proc.stdout
    _assert_census_clean(repo, "a refused bare confirm")


def test_the_refusal_names_the_flag_and_the_read_without_writing_route(tmp_path):
    """Both halves of the answer, in the headline-plus-hint shape every refusal uses.

    A caller who ran a bare confirm wanted one of two things: to see the queue, or to
    say the whole queue still stands. The refusal answers both, or the reader learns
    the second from a traceback and the first from nobody.
    """
    repo = _seeded(tmp_path, "wording")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert REFUSAL_HEADLINE in proc.stderr, proc.stderr
    assert READ_WITHOUT_WRITING in proc.stderr, proc.stderr
    # The fix line is the writer's own shape: headline line, then "fix:" and the hint.
    assert f"pass {ALL}" in proc.stderr, proc.stderr
    assert " fix: " in proc.stderr, proc.stderr
    for route in ("noni/direction/order.json", "noni brief"):
        assert route in proc.stderr, f"the hint omits {route!r}: {proc.stderr}"


def test_all_three_console_routes_print_the_same_refusal(tmp_path):
    """The wrapper, ``noni order`` and ``python -m noni.order`` agree byte for byte.

    The refusal lives in ``main``, so all three get it -- but the only place that
    claim is checked is the wrapper route the fixtures launch, so a refusal moved into
    one entry point's own code would pass every other test in this file.
    """
    repo = _seeded(tmp_path, "routes")
    runs = (
        run_wrapper(ORDER, "--repo", str(repo), "confirm", "--now", NOW),
        run_noni("order", "--repo", str(repo), "confirm", "--now", NOW),
        run_module("order", "--repo", str(repo), "confirm", "--now", NOW),
    )
    for proc in runs:
        assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
        assert REFUSAL_HEADLINE in proc.stderr, proc.stderr
        assert READ_WITHOUT_WRITING in proc.stderr, proc.stderr
    assert runs[0].stdout == runs[1].stdout == runs[2].stdout, (
        f"{runs[0].stdout!r} / {runs[1].stdout!r} / {runs[2].stdout!r}")
    assert runs[0].stderr == runs[1].stderr == runs[2].stderr, (
        f"{runs[0].stderr!r} / {runs[1].stderr!r} / {runs[2].stderr!r}")


# --- the gate runs on argv alone ----------------------------------------------


def test_a_bare_confirm_refuses_before_the_state_root_is_asked_about(tmp_path):
    """On a tree with no ``noni/`` at all the bare form still refuses at 2, and the
    refusal is the confirm one, not the state-root one.

    The gate is pure argv, so it cannot be the reads answering instead: the state-root
    refusal's own words are asserted absent. Before the fix this run reached the reads
    and wrote an empty ``order.json`` into a tree that is not a state root.
    """
    from _harness import _commit_file, _git, _init_repo

    repo = _init_repo(tmp_path / "code-repo")
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_file(repo, "README.md", "# a code repository\n")

    proc = _order(repo, "confirm", "--now", NOW)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert REFUSAL_HEADLINE in proc.stderr, proc.stderr
    assert "is not a noni state root" not in proc.stderr, proc.stderr
    assert not (repo / "noni").exists(), "a refused confirm created noni/ in a wrong tree"


def test_a_bare_confirm_refuses_before_the_artifact_is_read(tmp_path):
    """The gate precedes the artifact read, which the exit codes can tell apart.

    A malformed artifact is exit 4 and an unreadable one is exit 3, so a bare confirm
    that returned 4 or 3 here had opened the file: the refusal is 2 and the file's own
    bytes are what they always were.
    """
    repo = _repo(tmp_path, "unreadable")
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text("{ this is not json", encoding="utf-8")
    before = _order_path(repo).read_bytes()

    proc = _order(repo, "confirm", "--now", NOW)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert REFUSAL_HEADLINE in proc.stderr, proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_bare_confirm_never_reaches_git(tmp_path, monkeypatch):
    """The refusal returns before the run's first git call.

    A refusal that probed or committed first would answer the ticket's "git is
    untouched" from the artifact comparison alone, and the artifact comparison cannot
    tell a run that never called git from one whose git call happened to be a no-op.
    So the writer's own git helper is watched: it answers every call as a timeout, a
    route that could only ever be reached by a run that went past the gate.
    """
    module = _order_module()
    helper = module.gitwrite
    real = helper.git
    seen: list[tuple] = []

    def watching(repo_arg, *args, **kwargs):
        seen.append(args)
        return real(repo_arg, *args, **kwargs)

    monkeypatch.setattr(helper, "git", watching)
    repo = _seeded(tmp_path, "nogit")
    head_before = _head(repo)

    code = module.main(["--repo", str(repo), "confirm", "--now", NOW])

    assert code == 2, code
    assert seen == [], f"the refusal called git: {seen}"
    assert _head(repo) == head_before


# --- --all is the old bare confirm --------------------------------------------


def test_confirm_all_restamps_every_entry_and_commits(tmp_path):
    """``--all`` does exactly what a bare confirm did, down to the commit subject."""
    repo = _seeded(tmp_path, "all")
    head_before = _head(repo)

    proc = _order(repo, "confirm", ALL, "--now", NOW)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert [entry["confirmed"] for entry in _read(repo)["entries"]] == [NOW] * 3
    assert "(confirm all)" in proc.stdout, proc.stdout
    assert _head(repo) != head_before, "--all committed nothing"
    assert _subject(repo) == "direction: confirm all"
    _assert_census_clean(repo, "a confirm --all")


def test_confirm_all_that_changes_no_byte_commits_nothing(tmp_path):
    """The no-change arm the bare form had, kept: same stamp, nothing to write."""
    repo = _repo(tmp_path, "all-noop")
    _seed(repo, _entry(1, BASELINE_ID, STAMP), _entry(2, BASELINE_ID, STAMP))
    before = _order_path(repo).read_bytes()
    head_before = _head(repo)

    proc = _order(repo, "confirm", ALL, "--now", NOW)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert "unchanged" in proc.stdout and "nothing to commit" in proc.stdout, proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _head(repo) == head_before
    assert _porcelain(repo) == "", _porcelain(repo)


def test_confirm_all_with_no_commit_writes_the_file_and_moves_no_head(tmp_path):
    """``--all --no-commit`` is what a bare ``--no-commit`` was: file written, no git."""
    repo = _seeded(tmp_path, "all-no-commit")
    head_before = _head(repo)

    proc = _order(repo, "confirm", ALL, "--no-commit", "--now", NOW)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert [entry["confirmed"] for entry in _read(repo)["entries"]] == [NOW] * 3
    assert _head(repo) == head_before, "--no-commit committed"
    # The path is staged (the writer stages only its own path), hence "M " not " M ".
    assert _porcelain(repo).strip() == f"M {ORDER_REL}", _porcelain(repo)


def test_confirm_an_issue_is_unchanged(tmp_path):
    """The one-entry verb is untouched by this fix, with or without an issue."""
    repo = _seeded(tmp_path, "one")
    proc = _order(repo, "confirm", "2", "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert [entry["confirmed"] for entry in _read(repo)["entries"]] == \
        ["2026-10-01T00:00:00Z", NOW, "2026-10-03T00:00:00Z"]


# --- --all belongs to confirm alone, and not beside an issue -------------------


def test_all_is_refused_by_the_verbs_that_do_not_own_it(tmp_path):
    """``--all`` is confirm's flag: add, move and remove answer it as any stranger.

    A flag whose meaning no verb can use must not be dropped in silence -- the same
    rule ``--why`` and ``--decision`` obey, in the same place, with the same wording.
    """
    repo = _seeded(tmp_path, "ownership")
    before = _order_path(repo).read_bytes()
    cases = (        ("add", "9", "--decision", BASELINE_ID, ALL),
        ("move", "1", "--to", "2", ALL),
        ("remove", "1", ALL),
    )
    for argv in cases:
        proc = _order(repo, *argv, "--now", NOW)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert ALL in proc.stderr, f"{argv}: {proc.stderr}"
        assert "belongs to" in proc.stderr, f"{argv}: {proc.stderr}"
    assert _order_path(repo).read_bytes() == before, "a refused run rewrote the order"


def test_all_beside_an_issue_is_a_usage_error_in_either_order(tmp_path):
    """An issue names one entry and ``--all`` names every entry, so the pair is
    refused whichever order the tokens came in, at exit 2 and having written nothing.

    Only one order is the writer's own refusal. ``confirm 1 --all`` always arrives with
    ``issue="1"`` and ``all_entries`` set, so ``order_plan.confirm_usage_rule`` answers
    it with the writer's headline on every Python this project supports, and that
    wording is pinned exactly. The other order is argparse's business: ``confirm --all
    1`` puts the flag before the optional positional, and whether the positional still
    gets filled is the interpreter's. On 3.11 it does not -- the ``1`` is left over and
    argparse refuses the run as an unrecognised argument; on 3.14 it does, and the
    writer's own ALL_WITH_ISSUE refusal answers instead. Both exit 2 and neither writes.
    So the version-dependent half asserts only what holds on every supported version:
    the code, the untouched artifact, an unmoved HEAD, a clean tree, and a stderr that is
    one of those two known refusals rather than a traceback. Pinning either wording for
    this order would fail on the other half of the supported range.
    """
    repo = _seeded(tmp_path, "all-issue")
    before = _order_path(repo).read_bytes()
    head_before = _head(repo)
    # The order that reaches the writer on every supported version: exact wording.
    routed = _order(repo, "confirm", "1", ALL, "--now", NOW)
    assert routed.returncode == 2, f"{routed.returncode}: {routed.stderr}"
    assert ALL_WITH_ISSUE_HEADLINE in routed.stderr, routed.stderr
    # The order whose refusal depends on the interpreter: version-independent claims.
    stranded = _order(repo, "confirm", ALL, "1", "--now", NOW)
    assert stranded.returncode == 2, f"{stranded.returncode}: {stranded.stderr}"
    assert ALL_WITH_ISSUE_HEADLINE in stranded.stderr or \
        "unrecognized arguments: 1" in stranded.stderr, stranded.stderr
    for proc in (routed, stranded):
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "Traceback" not in proc.stdout, proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _head(repo) == head_before
    assert _porcelain(repo) == "", _porcelain(repo)


def test_the_unknown_verb_fix_line_names_the_confirm_forms_that_are_accepted(tmp_path):
    """A line a reader copies must be a line the parser takes (issue #193).

    The unknown-verb refusal advertised ``confirm [ISSUE]``, a form this writer refuses,
    so a caller who mistyped the verb was told to run a command that refuses them. The
    two arms of ``confirm`` are pinned in the words the refusal prints: the bracketed form
    every other verb takes says the subject is optional, and a confirm naming no subject
    is not, so the bracket is asserted absent rather than each fragment spelled a second
    time here.
    """
    repo = _seeded(tmp_path, "unknown-verb")
    proc = _order(repo, "shuffle", "7", "--now", NOW)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "confirm [ISSUE]" not in proc.stderr, proc.stderr
    assert f"confirm ISSUE | confirm {ALL}" in proc.stderr, proc.stderr


def test_the_help_line_names_the_flag_on_the_confirm_form(tmp_path):
    """``--all`` is discoverable where a caller looks, and on no other form.

    The usage block and the parser are pinned against each other by
    ``tests/test_order_writer_docs.py``; this is the half that says the flag is
    confirm's, not a fifth flag every verb takes.
    """
    proc = _order(_repo(tmp_path, "help"), "--help")
    assert proc.returncode == 0, proc.stderr
    assert ALL in proc.stdout, proc.stdout
    all_lines = [line for line in proc.stdout.splitlines() if ALL in line]
    assert any("confirm" in line for line in all_lines), proc.stdout
