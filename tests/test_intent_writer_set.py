"""The intent writer: one verb, one file, one commit, and four honest codes.

``intent.py`` is the only writer of ``noni/direction/intent.md``; these tests are
the contract that claim rests on. The file is written only after every read and
every check has passed, is committed with the subject that cites the record that
set the direction, and a refusal leaves the tracked files byte-identical.
"""

from __future__ import annotations

import subprocess

import pytest
from intent_fixtures import (
    GOOD_INTENT,
    INTENT_REL,
    RECORD_ID,
    _commit,
    commit_intent,
    install_intent,
    record,
    repo_with_record,
)
from intent_shapes import (
    FENCED_EXAMPLES,
    FENCED_HEADING,
    INDENTED_STAMP,
    INTENT_REFUSAL_SHAPES,
)
from intent_writer_support import (
    commit_count,
    draft,
    intent_home_isolation,
    intent_run,
    tracked_digests,
)

SET = "set"


def test_set_installs_a_draft_and_commits_it(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    installed = repo / INTENT_REL
    assert installed.is_file()
    assert "## Purpose" in installed.read_text(encoding="utf-8")
    assert _subject(repo) == f"intent: {RECORD_ID}"
    assert _touched(repo) == [INTENT_REL]


def test_the_stamp_is_the_run_day_and_not_the_drafts(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID, "--now", "2026-11-09T23:59:59Z")
    assert result.returncode == 0, result.stderr
    lines = (repo / INTENT_REL).read_text(encoding="utf-8").splitlines()
    stamps = [line for line in lines if line.startswith("Last-confirmed:")]
    assert stamps == ["Last-confirmed: 2026-11-09"]


def test_a_run_that_changes_no_byte_commits_nothing(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    before = _head(repo)
    commits = commit_count(repo)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    assert "unchanged" in result.stdout
    assert _head(repo) == before
    assert commit_count(repo) == commits


def test_no_commit_leaves_the_file_written_and_says_so(tmp_path):
    repo = repo_with_record(tmp_path)
    commits = commit_count(repo)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID, "--no-commit")
    assert result.returncode == 0, result.stderr
    assert (repo / INTENT_REL).is_file()
    assert "uncommitted" in result.stdout
    assert commit_count(repo) == commits


@pytest.mark.parametrize("name, text, _subject", INTENT_REFUSAL_SHAPES)
def test_a_draft_the_shape_refuses_is_exit_4_and_writes_nothing(
        tmp_path, name, text, _subject):
    repo = repo_with_record(tmp_path)
    before = tracked_digests(repo)
    result = intent_run(repo, SET, "--from", draft(tmp_path, text),
                        "--decision", RECORD_ID)
    assert result.returncode == 4, result.stdout + result.stderr
    assert _subject in result.stderr
    assert tracked_digests(repo) == before
    assert not (repo / INTENT_REL).exists()


def test_a_draft_from_outside_the_tree_installs(tmp_path):
    """A draft is input, not state: its location constrains nothing but its bytes."""
    repo = repo_with_record(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    src = elsewhere / "draft.md"
    src.write_text(GOOD_INTENT, encoding="utf-8")
    result = intent_run(repo, SET, "--from", str(src), "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr


def test_a_draft_that_is_not_utf8_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, b"\xff\xfe broken"),
                        "--decision", RECORD_ID)
    assert result.returncode == 2
    assert (repo / INTENT_REL).exists() is False


def test_a_draft_path_that_is_a_directory_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    directory = tmp_path / "dir"
    directory.mkdir()
    result = intent_run(repo, SET, "--from", str(directory), "--decision", RECORD_ID)
    assert result.returncode == 2


def test_a_draft_path_that_is_a_symlink_is_refused(tmp_path):
    repo = repo_with_record(tmp_path)
    real = tmp_path / "real.md"
    real.write_text(GOOD_INTENT, encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    result = intent_run(repo, SET, "--from", str(link), "--decision", RECORD_ID)
    assert result.returncode == 2
    assert "symlink" in result.stderr


def test_a_now_that_names_no_instant_is_exit_2(tmp_path):
    """The reproducibility knob is not a suggestion: a stamp the writer cannot name
    is refused rather than quietly replaced by the clock."""
    repo = repo_with_record(tmp_path)
    for bad in ("2026-10-27T12:00:00", "not a timestamp", "2026-10-27 12:00"):
        result = intent_run(repo, "set", "--from", draft(tmp_path, GOOD_INTENT, bad),
                            "--decision", RECORD_ID, "--now", bad)
        assert result.returncode == 2, f"{bad!r}: {result.stdout}{result.stderr}"
        assert "--now" in result.stderr, result.stderr


def test_a_now_with_an_offset_stamps_the_utc_day_it_falls_on(tmp_path):
    """The instant is what matters, not the zone it was spelled in: the same
    minute expressed east of UTC is still the day before it in UTC."""
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, "set", "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID, "--now",
                        "2026-10-27T23:30:00+02:00")
    assert result.returncode == 0, result.stderr
    stamps = [line for line in (repo / INTENT_REL).read_text(encoding="utf-8").splitlines()
              if line.startswith("Last-confirmed:")]
    assert stamps == ["Last-confirmed: 2026-10-27"]


def test_a_draft_that_cannot_be_read_is_exit_3(tmp_path):
    """"Not there" is a usage error and "there but unreadable" is an environment
    fault: the caller fixes them differently, so the codes stay apart."""
    repo = repo_with_record(tmp_path)
    path = tmp_path / "unreadable.md"
    path.write_text(GOOD_INTENT, encoding="utf-8")
    path.chmod(0o000)
    try:
        result = intent_run(repo, "set", "--from", str(path), "--decision", RECORD_ID)
    finally:
        path.chmod(0o644)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "could not be read" in result.stderr, result.stderr


@pytest.mark.parametrize("decision", [
    "2026-13-40-nope",        # not a date-shaped stem
    "2026-10-01",             # a date and no slug
    "2026-10-01-UPPER",       # an id no writer names a file by
    "",                       # empty
    "not a slug",             # a space
])
def test_a_decision_id_that_could_name_no_file_is_exit_4(tmp_path, decision):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", decision)
    assert result.returncode == 4
    assert not (repo / INTENT_REL).exists()


def test_a_record_the_ledger_does_not_hold_is_exit_4(tmp_path):
    repo = repo_with_record(tmp_path, records=())
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 4
    assert RECORD_ID in result.stderr


def test_a_superseded_record_is_exit_4_and_names_the_successor(tmp_path):
    repo = repo_with_record(tmp_path, records=(
        record(), record(status="superseded", supersedes=RECORD_ID),
    ))
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 4
    assert "superseded" in result.stderr


def test_an_unreadable_record_is_exit_3_not_exit_4(tmp_path):
    """"I could not read it" and "it is not there" are different answers."""
    repo = repo_with_record(tmp_path)
    path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    path.chmod(0o000)
    try:
        result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                            "--decision", RECORD_ID)
    finally:
        path.chmod(0o644)
    assert result.returncode == 3


def test_a_symlink_at_the_intent_path_is_exit_3_and_survives(tmp_path):
    repo = repo_with_record(tmp_path)
    link = repo / INTENT_REL
    link.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.md"
    outside.write_text("# something\n", encoding="utf-8")
    link.symlink_to(outside)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 3
    assert link.is_symlink()
    assert outside.read_text(encoding="utf-8") == "# something\n"


def test_a_directory_at_the_intent_path_is_exit_3(tmp_path):
    repo = repo_with_record(tmp_path)
    (repo / INTENT_REL).mkdir(parents=True)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 3


def test_a_repo_that_is_not_a_directory_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    missing = tmp_path / "nowhere"
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID, repo_override=missing)
    assert result.returncode == 2


def test_a_missing_draft_argument_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--decision", RECORD_ID)
    assert result.returncode == 2


def test_a_missing_decision_argument_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT))
    assert result.returncode == 2


def test_an_unknown_verb_is_exit_2(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, "show")
    assert result.returncode == 2


def test_a_missing_subcommand_names_the_verb_it_wants(tmp_path):
    """The refusal without the verb still says which verb (issue #98).

    ``intent --repo X --from f --decision d`` with no ``set`` reached argparse's own
    missing-positional refusal, which names the slot and not the word that fills it:
    only an *invalid* verb printed the fix line that did. The wording argparse
    composes is kept (it is the same refusal every tool prints) and the verb is
    named beside it, with the usage line above, at the usage code and with no
    traceback. Nothing is written by a run this early in the checks.
    """
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "the following arguments are required: subcommand" in result.stderr, (
        result.stderr)
    assert "choose from: set" in result.stderr, result.stderr
    assert result.stderr.startswith("usage: intent.py "), result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert not (repo / INTENT_REL).exists()


def test_a_fenced_heading_does_not_become_a_section(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, FENCED_HEADING),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    # The fenced one is prose inside the Never section, so the file still holds
    # exactly one real Ask-first heading -- and the writer left the example alone.
    assert (repo / INTENT_REL).read_text(encoding="utf-8").count("## Ask first") == 2
    assert "this is an example, not the section" in \
        (repo / INTENT_REL).read_text(encoding="utf-8")


def test_an_indented_stamp_line_survives_and_the_real_one_is_restamped(tmp_path):
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, SET, "--from", draft(tmp_path, INDENTED_STAMP),
                        "--decision", RECORD_ID, "--now", "2026-11-09T00:00:00Z")
    assert result.returncode == 0, result.stderr
    lines = (repo / INTENT_REL).read_text(encoding="utf-8").splitlines()
    assert "    Last-confirmed: 2020-01-01" in lines
    assert [line for line in lines if line.startswith("Last-confirmed:")] == \
        ["Last-confirmed: 2026-11-09"]


def test_a_draft_whose_fences_balance_installs(tmp_path):
    """A worked example is allowed: the refusal is the unclosed opener, not fences.

    The control for ``unclosed-fence`` in the shared shape table -- a rule that
    refused any fenced example would pass every other test in this file.
    """
    repo = repo_with_record(tmp_path)
    before = commit_count(repo)
    result = intent_run(repo, SET, "--from", draft(tmp_path, FENCED_EXAMPLES),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    assert commit_count(repo) == before + 1
    assert (repo / INTENT_REL).read_text(encoding="utf-8").count("## Principles") == 2


@pytest.mark.parametrize("opener", ("```", "~~~~"))
def test_an_unclosed_fence_is_exit_4_and_writes_nothing(tmp_path, opener):
    """The tail an unclosed opener hides is refused, not read as nothing.

    Both fence tokens are driven: the walk pairs a backtick opener only with a
    backtick closer and a tilde only with a tilde, so a fix that checked one token
    and not the other -- or counted openers instead of tracking them -- fails on
    one of the two parameters.
    """
    repo = repo_with_record(tmp_path)
    before = tracked_digests(repo)
    text = GOOD_INTENT + f"{opener}\n## Principles\nExtra.\nLast-confirmed: 2030-01-01\n"
    result = intent_run(repo, SET, "--from", draft(tmp_path, text),
                        "--decision", RECORD_ID)
    assert result.returncode == 4, result.stdout + result.stderr
    assert "unclosed code fence" in result.stderr, result.stderr
    assert tracked_digests(repo) == before
    assert not (repo / INTENT_REL).exists()


def test_the_commit_stages_only_the_intent_file(tmp_path):
    """A file somebody else staged is neither committed nor unstaged."""
    repo = repo_with_record(tmp_path)
    _commit(repo, "other.md", "staged by someone else\n")
    (repo / "other.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(repo, "add", "other.md")
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    assert _touched(repo) == [INTENT_REL]
    assert (repo / "other.md").exists()


def test_the_writer_writes_nothing_outside_the_state_root(tmp_path):
    """HOME, XDG and git's own config dirs are empty for the whole run."""
    repo = repo_with_record(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    result = intent_home_isolation(repo, home, SET, "--from",
                                   draft(tmp_path, GOOD_INTENT),
                                   "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    assert _home_is_empty(home)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        capture_output=True, text=True, check=True)


def _subject(repo) -> str:
    return _git(repo, "log", "-1", "--format=%s").stdout.strip()


def _head(repo) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _touched(repo) -> list[str]:
    return _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()


def _home_is_empty(home) -> bool:
    return not any(home.iterdir())
