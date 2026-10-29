"""decide.py supersedes a baseline: the pointer, the chain, the census.

Extracted from the decide writer suite: the supersede path, the record it writes
and refuses to write, and what the census says about the pair."""

import json
import sys

from _harness import (
    _git_e2,
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
    _commit_tree,
    _decide,
    _head_paths,
    _porcelain,
    _read,
    _record_json,
    _record_path,
    _run,
)


def test_supersede_writes_both_paths_in_one_commit(tmp_path):
    """A supersede writes the new record and flips the target in one commit
    holding exactly those two paths, with both censuses clean afterwards."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 0, proc.stderr

    new_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    baseline_rel = f"noni/decisions/{BASELINE_ID}.json"
    assert set(_head_paths(repo)) == {new_rel, baseline_rel}, _head_paths(repo)
    # Each path the run wrote is named once by the commit it landed in: the two
    # paths and nothing else, with neither repeated (see
    # test_hardening_a_supersede_lists_each_path_once_in_the_commit for the
    # rollback and message halves of the same property).
    listed = _head_paths(repo)
    assert sorted(listed) == sorted([new_rel, baseline_rel]), listed
    assert len(listed) == len(set(listed)), f"a path is listed twice: {listed}"
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == f"steering: supersede {BASELINE_ID} with {BASELINE_ID[:10]}-scheduler"

    target = _read(repo, BASELINE_ID)
    assert target["status"] == "superseded"
    new = _read(repo, f"{BASELINE_ID[:10]}-scheduler")
    assert new["status"] == "decided"
    assert new["supersedes"] == BASELINE_ID
    # Only the target's status changed: every other field of the superseded
    # record still reads as it was committed (references/supersede.md).
    assert target["questions"][0]["answer"] == "yes"
    assert target["date"] == BASELINE_DATE
    assert target["asked_by"] == "developer"
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "a supersede")


def test_supersede_target_keeps_every_byte_but_its_status(tmp_path):
    """The supersede target's committed bytes differ from HEAD's only in the
    status value: nothing else in the file moves."""
    repo = _baseline_repo(tmp_path)
    before = _git_e2(repo, "show", f"HEAD:noni/decisions/{BASELINE_ID}.json").stdout
    _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
    )
    after = _git_e2(repo, "show", f"HEAD:noni/decisions/{BASELINE_ID}.json").stdout
    assert json.loads(before)["status"] == "decided"
    assert json.loads(after)["status"] == "superseded"
    stripped = dict(json.loads(before))
    stripped.pop("status")
    other = dict(json.loads(after))
    other.pop("status")
    assert stripped == other, "a supersede changes the target's status and nothing else"


def test_supersede_with_an_unanswered_question_exits_two(tmp_path):
    """An unanswered question in a supersede would leave the chain with no
    live answer, so it is refused as input and nothing is written."""
    repo = _baseline_repo(tmp_path)
    ledger = repo / "noni" / "decisions"
    before = _git_e2(repo, "show", f"HEAD:noni/decisions/{BASELINE_ID}.json").stdout
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS,
        "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 2, proc.stderr
    assert "--supersedes" in proc.stderr
    assert _git_e2(repo, "show", f"HEAD:noni/decisions/{BASELINE_ID}.json").stdout == before
    assert sorted(p.name for p in ledger.glob("*.json")) == [f"{BASELINE_ID}.json"]
    assert _porcelain(repo, "noni/decisions") == ""


def test_supersede_of_a_missing_target_exits_four(tmp_path):
    """A target with no record file is refused (exit 4) and the ledger is
   untouched, including its git state."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--supersedes", "2026-09-09-nope")
    assert proc.returncode == 4, proc.stderr
    assert _porcelain(repo) == ""
    assert _head_paths(repo) == [f"noni/decisions/{BASELINE_ID}.json"]
    assert sorted(p.name for p in (repo / "noni" / "decisions").glob("*.json")) == [
        f"{BASELINE_ID}.json"
    ]


def test_supersede_of_an_already_superseded_target_exits_four(tmp_path):
    """superseded is terminal, so a second supersede of the same target is
    refused (exit 4) with the target left byte-identical."""
    repo = _baseline_repo(tmp_path)
    baseline_rel = f"noni/decisions/{BASELINE_ID}.json"
    first_rel = f"noni/decisions/{BASELINE_ID[:10]}-first.json"
    second_rel = f"noni/decisions/{BASELINE_ID[:10]}-second.json"
    # The chain: baseline -> first -> second, with only `second` live. Each
    # record is committed with the status its chain position gives it, so the
    # fixture is census-clean before decide.py is pointed at it.
    _commit_tree(repo, first_rel,
                 _record_json(f"{BASELINE_ID[:10]}-first", "decided", "yes", BASELINE_ID),
                 f"steering: supersede {BASELINE_ID} with {BASELINE_ID[:10]}-first",
                 BASELINE_DATE)
    _commit_tree(repo, baseline_rel,
                 _record_json(BASELINE_ID, "superseded", "yes", None),
                 "fixture: baseline is superseded by first", BASELINE_DATE)
    _commit_tree(repo, second_rel,
                 _record_json(f"{BASELINE_ID[:10]}-second", "decided", "no",
                              f"{BASELINE_ID[:10]}-first"),
                 f"steering: supersede {BASELINE_ID[:10]}-first with {BASELINE_ID[:10]}-second",
                 BASELINE_DATE)
    _commit_tree(repo, first_rel,
                 _record_json(f"{BASELINE_ID[:10]}-first", "superseded", "yes", BASELINE_ID),
                 "fixture: first is superseded by second", BASELINE_DATE)
    # The fixture's own chain must be clean first, or a failure below would say
    # something about the fixture rather than about decide.py's refusal.
    _assert_both_censuses_clean(repo, "building a two-step supersede chain")
    committed = _git_e2(repo, "show", f"HEAD:{baseline_rel}").stdout
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 4, proc.stderr
    assert "already" in proc.stderr.lower() or "terminal" in proc.stderr.lower()
    assert _git_e2(repo, "show", f"HEAD:{baseline_rel}").stdout == committed
    assert _porcelain(repo) == ""


def test_supersede_of_an_uncommitted_target_exits_four(tmp_path):
    """A target that was never committed is refused: folding it into this
    commit would commit a record decide.py did not validate."""
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID[:10]}-draft.json"
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(
        _record_json(f"{BASELINE_ID[:10]}-draft", "decided", "yes", None), encoding="utf-8"
    )
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", f"{BASELINE_ID[:10]}-draft",
    )
    assert proc.returncode == 4, proc.stderr
    assert "not tracked" in proc.stderr or "commit" in proc.stderr.lower()
    # The draft is still an untracked draft, and no new record was written.
    assert _porcelain(repo, rel) == f"?? {rel}"
    assert not _record_path(repo, NEW_ID).exists()


def test_supersede_of_a_locally_modified_target_exits_four(tmp_path):
    """A target whose working-tree bytes differ from its last commit is
    refused (exit 4): decide.py supersedes committed records, not drafts."""
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID}.json"
    edited = json.loads((repo / rel).read_text(encoding="utf-8"))
    edited["scope"] = "someone's uncommitted edit"
    (repo / rel).write_text(json.dumps(edited, indent=2) + "\n", encoding="utf-8")
    proc = _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 4, proc.stderr
    assert "byte-identical" in proc.stderr
    # The operator's uncommitted edit is left exactly as it was: refuse is not
    # repair, and decide.py never reverts a file it did not write.
    assert json.loads((repo / rel).read_text(encoding="utf-8"))["scope"] == (
        "someone's uncommitted edit"
    )
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()


def test_supersede_needs_the_targets_date(tmp_path):
    """A supersede carries the date of the record it replaces, so a --date from
    another day is refused rather than writing a record outside the chain."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--supersedes", BASELINE_ID)
    assert proc.returncode == 4, proc.stderr
    assert BASELINE_ID[:10] in proc.stderr, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()
    assert _porcelain(repo, "noni/decisions") == ""


# --- refusals: input, identity, collision -------------------------------------


def test_missing_git_identity_exits_three_with_the_config_hint(tmp_path):
    """Without git config user.name the record cannot be attributed, so the
    run refuses (exit 3) and names the command that fixes it.

    The conftest's autouse fixture already cleared the ambient GIT_AUTHOR_*
    vars, so the repo's own name (unset here) is the only source left once
    every config file is /dev/null.
    """
    repo = _baseline_repo(tmp_path)
    monkey_home = tmp_path / "no-home"
    monkey_home.mkdir(exist_ok=True)
    env = {
        "PATH": sys.executable.rsplit("/", 2)[0] + ":/usr/bin:/bin",
        "HOME": str(monkey_home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    proc = _decide(repo, *ANSWERED, env=env, identity=None)
    assert proc.returncode == 3, proc.stderr
    assert "user.name" in proc.stderr
    assert "git" in proc.stderr and "config" in proc.stderr, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_non_repository_exits_three(tmp_path):
    """A --repo that is not a git work tree is a git problem (exit 3), not a
    usage problem: the fix is running it in the right place."""
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = run_decide(plain, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
                      *QUESTION, *OPTIONS, *ANSWERED)
    assert proc.returncode == 3, proc.stderr
    assert "git" in proc.stderr.lower()
