"""The commit decide.py makes: one path, one subject, one identity.

Extracted from the decide writer suite: the git side of the write, the pinned
author and date, and the refusals before a commit is attempted."""

import json

from _harness import (
    _git,
    _git_e2,
    _init_repo,
    git_pin_date,
    run_decide,
)
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_DATE,
    BASELINE_ID,
    NEW_DATE,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _assert_both_censuses_clean,
    _baseline_repo,
    _census_py,
    _census_sh,
    _commit_tree,
    _decide,
    _forced_commit_failure,
    _head_paths,
    _pin_identity,
    _porcelain,
    _read,
    _record_json,
    _record_path,
    _run,
)


def test_forced_commit_failure_rolls_both_paths_back(tmp_path):
    """A commit that fails leaves git status --porcelain empty for the paths
    this run touched, and both censuses are clean afterwards."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, env=_forced_commit_failure())
    assert proc.returncode == 5, proc.stderr
    assert "commit" in proc.stderr.lower()
    rel = f"noni/decisions/{NEW_ID}.json"
    assert _porcelain(repo, rel) == "", _porcelain(repo)
    assert not _record_path(repo, NEW_ID).exists(), "the record this run made must be unlinked"
    assert _head_paths(repo) == [f"noni/decisions/{BASELINE_ID}.json"]
    _assert_both_censuses_clean(repo, "a rolled-back commit")


def test_forced_commit_failure_rolls_both_supersede_paths_back(tmp_path):
    """A supersede whose commit fails restores the target's committed bytes and
    removes the new record, so the chain is exactly as it was."""
    repo = _baseline_repo(tmp_path)
    before = _git_e2(repo, "show", f"HEAD:noni/decisions/{BASELINE_ID}.json").stdout
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
        env=_forced_commit_failure(),
    )
    assert proc.returncode == 5, proc.stderr
    new_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    assert _porcelain(repo, new_rel, target_rel) == "", _porcelain(repo)
    assert not (repo / new_rel).exists()
    assert (repo / target_rel).read_text(encoding="utf-8") == before
    _assert_both_censuses_clean(repo, "a rolled-back supersede")


def test_no_commit_writes_without_moving_head(tmp_path):
    """--no-commit writes the record, leaves HEAD where it was, and prints one
    'left uncommitted' line naming the path."""
    repo = _baseline_repo(tmp_path)
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    proc = _decide(repo, *ANSWERED, "--no-commit")
    assert proc.returncode == 0, proc.stderr
    assert _record_path(repo, NEW_ID).is_file()
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    rel = f"noni/decisions/{NEW_ID}.json"
    assert rel in proc.stdout
    uncommitted = [line for line in proc.stdout.splitlines() if "uncommitted" in line]
    assert len(uncommitted) == 1, proc.stdout
    assert "commit" in uncommitted[0]
    assert _porcelain(repo, rel) == f"?? {rel}"


def test_no_commit_supersede_writes_both_paths_without_moving_head(tmp_path):
    """A --no-commit supersede leaves the target edited and the new record
    untracked, names both paths, and says to commit them before the census."""
    repo = _baseline_repo(tmp_path)
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
        "--no-commit",
    )
    assert proc.returncode == 0, proc.stderr
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    new_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    assert new_rel in proc.stdout and target_rel in proc.stdout
    assert "uncommitted" in proc.stdout and "census" in proc.stdout.lower()
    # AC3: the line also says what the target now holds, so a run aborted here
    # knows to restore that file as well as delete the new record (the one line
    # names both paths and the status, so the operator needs no second command).
    status_lines = [line for line in proc.stdout.splitlines()
                    if target_rel in line]
    assert len(status_lines) == 1, proc.stdout
    assert "superseded" in status_lines[0], proc.stdout
    assert _read(repo, BASELINE_ID)["status"] == "superseded"
    # The censuses read the working tree, so the edited target is exactly what
    # an uncommitted supersede looks like: the 'left uncommitted' line is the
    # run saying so, and committing resolves it (PM's ruling on this pair).
    code_sh, _ = _census_sh(repo)
    assert code_sh == 12, "an uncommitted supersede must read as edited-after-commit"
    _git(repo, "add", new_rel, target_rel)
    git_pin_date(repo, f"{BASELINE_ID[:10]}T00:00:00Z", "commit", "-q", "-m", "handoff")
    _assert_both_censuses_clean(repo, "committing a --no-commit supersede by hand")


def test_a_foreign_staged_file_survives_the_run(tmp_path):
    """A file staged before the run (README.md) is neither committed by
    decide.py nor unstaged by it: 'git add -- <paths>' plus 'commit --only'
    is what keeps the commit to the paths this run wrote."""
    repo = _baseline_repo(tmp_path)
    (repo / "README.md").write_text("somebody else's staged work\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    assert "README.md" in _git_e2(repo, "diff", "--cached", "--name-only").stdout

    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"], _head_paths(repo)
    assert "README.md" in _git_e2(repo, "diff", "--cached", "--name-only").stdout


def test_a_target_that_is_not_an_object_exits_four(tmp_path):
    """A target whose file is valid JSON but not a record object is refused
    (exit 4): decide.py cannot flip the status of something that has none."""
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID[:10]}-list.json"
    _commit_tree(repo, rel, json.dumps(["not", "a", "record"]) + "\n", "fixture: junk", BASELINE_DATE)
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", f"{BASELINE_ID[:10]}-list",
    )
    assert proc.returncode == 4, proc.stderr
    assert "JSON object" in proc.stderr
    assert _porcelain(repo) == ""


def test_a_target_whose_body_disagrees_with_its_name_exits_four(tmp_path):
    """A file named <id>.json whose record carries a different id is refused:
    the censuses key the chain on the id field, so superseding by filename
    would mark a record the operator did not name."""
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID[:10]}-mismatch.json"
    body = json.loads(_record_json(f"{BASELINE_ID[:10]}-mismatch", "decided", "yes", None))
    body["id"] = "2026-10-01-something-else"
    _commit_tree(repo, rel, json.dumps(body, indent=2) + "\n", "fixture: mismatched id",
                 BASELINE_DATE)
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", f"{BASELINE_ID[:10]}-mismatch",
    )
    assert proc.returncode == 4, proc.stderr
    assert "in its own record" in proc.stderr
    assert _porcelain(repo) == ""


def test_an_empty_scope_or_asked_by_exits_two(tmp_path):
    """Both fields are census-checked as non-empty strings, so a blank one is
    refused as input rather than written into a record that fails later."""
    repo = _baseline_repo(tmp_path)
    blank_scope = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, "--scope", "   ",
        "--asked-by", "developer", *QUESTION, *OPTIONS, *ANSWERED,
    )
    assert blank_scope.returncode == 2, blank_scope.stderr
    assert "--scope" in blank_scope.stderr
    blank_asker = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, "--scope", "release ordering",
        "--asked-by", "  ", *QUESTION, *OPTIONS, *ANSWERED,
    )
    assert blank_asker.returncode == 2, blank_asker.stderr
    assert "--asked-by" in blank_asker.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_malformed_question_or_a_duplicated_id_exits_two(tmp_path):
    """A --question with no '=', or one that reuses an id, cannot name a
    question unambiguously, so both are refused before anything is written."""
    repo = _baseline_repo(tmp_path)
    no_equals = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
        "--question", "nobody knows", "--option", "q1=a", "--option", "q1=b",
    )
    assert no_equals.returncode == 2, no_equals.stderr
    assert "--question" in no_equals.stderr
    duplicate = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
        "--question", "q1=First?", "--question", "q1=Second?",
        "--option", "q1=a", "--option", "q1=b", "--answer", "q1=a",
    )
    assert duplicate.returncode == 2, duplicate.stderr
    assert "twice" in duplicate.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_malformed_option_exits_two(tmp_path):
    """An --option with no '=' is refused the same way an --answer is: it
    cannot say which question it belongs to."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE, *QUESTION,
        "--option", "orphan", "--option", "q1=real", "--answer", "q1=real",
    )
    assert proc.returncode == 2, proc.stderr
    assert "--option" in proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_supersede_target_id_that_is_not_an_id_exits_two(tmp_path):
    """--supersedes takes a record id; anything else is a usage error, refused
    before git is consulted at all."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE, *QUESTION, *OPTIONS,
        *ANSWERED, "--supersedes", "../etc/passwd",
    )
    assert proc.returncode == 2, proc.stderr
    assert "record id" in proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_supersede_without_a_date_writes_todays_record(tmp_path):
    """A supersede is dated like any other record: with no --date the run's own
    UTC day names it, so a correction made later no longer has to carry the old day.

    The run is made with --no-commit so the fixture can name the day it commits
    under: a plain commit would carry the wall-clock day the censuses cannot be
    pinned to, which is every census call in this suite's rule."""
    repo = _baseline_repo(tmp_path)
    _pin_identity(repo, "Replay")
    proc = run_decide(
        repo,
        "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
        "--no-commit",
    )
    assert proc.returncode == 0, proc.stderr
    # The new id comes off the writer's own `wrote` line (the record is named
    # first, the target second), not off a clock read in this process: the two
    # cannot disagree, not even across midnight UTC.
    wrote = [line for line in proc.stdout.splitlines() if "wrote " in line]
    assert len(wrote) == 1, proc.stdout
    new_rel = wrote[0].split("wrote ", 1)[1].split(",")[0]
    new_id = new_rel.rsplit("/", 1)[-1][: -len(".json")]
    assert new_id.endswith("-scheduler"), proc.stdout
    assert (repo / "noni" / "decisions" / f"{new_id}.json").is_file()
    assert _read(repo, new_id)["supersedes"] == BASELINE_ID
    assert _read(repo, BASELINE_ID)["status"] == "superseded"
    _git(repo, "add", "-A", "noni/decisions")
    git_pin_date(repo, f"{new_id[:10]}T00:00:00Z", "commit", "-q", "-m", "handoff")
    _assert_both_censuses_clean(repo, "committing a no-date supersede by hand")


def test_the_ledger_directory_is_created_for_the_first_record(tmp_path):
    """A fresh attached project has no noni/decisions yet: the writer allocates
    the directory that holds its own record rather than failing, once asked to
    start the state root with --init."""
    repo = _init_repo(tmp_path / "fresh")
    assert not (repo / "noni" / "decisions").exists()
    proc = _decide(repo, *ANSWERED, "--init")
    assert proc.returncode == 0, proc.stderr
    assert _record_path(repo, NEW_ID).is_file()
    # The unified census treats a recordless ledger as ledger-empty; with the
    # record written it must read as a real ledger, which is what this proves.
    code_py, out_py = _census_py(repo)
    assert code_py == 0, out_py


def test_a_second_option_flag_for_the_same_question_adds_an_option(tmp_path):
    """Two --option flags for one question are two options, not one: folding
    the repeats into a map would silently lose the option the operator listed."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "three-options", "--date", NEW_DATE, *BASE,
        "--question", "q1=Which release?",
        "--option", "q1=next train", "--option", "q1=after that", "--option", "q1=drop it",
        "--answer", "q1=drop it",
    )
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, f"{NEW_DATE}-three-options")
    assert record["questions"][0]["options"] == ["next train", "after that", "drop it"]
    assert record["questions"][0]["answer"] == "drop it"
    _assert_both_censuses_clean(repo, "writing three options")


def test_a_free_text_answer_may_contain_an_equals_sign(tmp_path):
    """The escape hatch stores the operator's own words, which may carry '=':
    only the first '=' splits the flag, so the answer survives intact."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "escape", "--date", NEW_DATE, *BASE, *QUESTION, *OPTIONS,
        "--answer", "q1=ship=friday when it is ready",
    )
    assert proc.returncode == 0, proc.stderr
    assert _read(repo, f"{NEW_DATE}-escape")["questions"][0]["answer"] == (
        "ship=friday when it is ready"
    )
