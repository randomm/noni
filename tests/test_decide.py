"""The decide.py writer: one command per steering act, honest exit codes.

Covered, in the order the acceptance criteria name them:

- a decided record written and committed under ``steering: <id>``, and an open
  record whose unanswered question carries ``"answer": null`` — both pass the
  unified census and census.sh, and the unified one runs under ``--strict``.
- ``--supersedes`` writes the new record and flips the target to superseded in
  one commit holding exactly those two paths, message ``steering: supersede
  <target> with <id>``, with both censuses clean afterwards.
- the refusals: an unanswered question with ``--supersedes`` (exit 2); a
  missing, already-superseded, uncommitted or locally modified target (exit 4),
  each leaving the target and the ledger byte-identical to before.
- no ``git config user.name`` (exit 3, with the config command in the hint);
  an empty or malformed slug (exit 2); a filename collision (exit 4); an
  argparse failure (exit 2).
- a forced commit failure (exit 5) leaves ``git status --porcelain -- <paths>``
  empty and both censuses clean; ``--no-commit`` writes without touching HEAD
  and prints one 'left uncommitted' line naming the paths.
- a file somebody else staged (README.md) is neither swept into the commit nor
  unstaged by the run.
- the docstring's exit table and Usage block are the EXIT_* constants and the
  parser's flags, and the declined/open state is documented in the null form.
- the hardening round (``test_hardening_*.py``-shaped concerns, all in this
  file): a non-UTF-8 target is a clean exit 4 that never echoes the bytes; a
  rollback that cannot restore names the leftover path in the exit 5; a git
  call that times out is never read as a clean answer (``GIT_TIMEOUT_RC``);
  every git call disables hooks and external transports without neutralising
  global config; a supersede refuses a target the writer would rewrite beyond
  its status; written files are 0644-and-umask, never 0600; and source ids
  must be positive.

The census baseline convention (PM's ruling): every test commits a record
with ``git_pin_date`` before running decide, and both census invocations pass a
pinned ``--now``, so a run measures the ledger and not the wall clock.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from _harness import (
    DECIDE,
    REPO,
    _git,
    _git_e2,
    _init_repo,
    _script_ast,
    git_pin_date,
    run_decide,
    subprocess_env,
)
from _harness import _git_env_with_identity as _harness_identity_env

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

# Every census in this file is pinned: --now stops the wall clock from
# deciding a staleness or empty-ledger row, and the baseline records are
# committed under the same fixed dates (see git_pin_date).
NOW = "2026-10-26T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
BASELINE_DATE = "2026-10-01T10:00:00Z"
NEW_DATE = "2026-10-26"
NEW_ID = f"{NEW_DATE}-scheduler"

# One question, two options: the smallest shape both censuses accept. Flags are
# kept as lists so each test reads as the command line it runs.
QUESTION = ["--question", "q1=Which release carries the scheduler?"]
OPTIONS = ["--option", "q1=next train", "--option", "q1=after that"]
ANSWERED = ["--answer", "q1=next train"]
BASE = ["--scope", "release ordering", "--asked-by", "developer"]


def _record_path(repo: Path, record_id: str) -> Path:
    return repo / "noni" / "decisions" / f"{record_id}.json"


def _read(repo: Path, record_id: str) -> dict:
    return json.loads(_record_path(repo, record_id).read_text(encoding="utf-8"))


def _run(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run decide.py with exactly the flags given, identity pinned to Replay."""
    _pin_identity(repo, "Replay")
    return run_decide(repo, *args, env=env)


def _baseline_repo(tmp_path: Path, subdir: str = "repo") -> Path:
    """A repo whose ledger holds one committed decided record, at a pinned date.

    ``subdir`` names the repo's directory under ``tmp_path``: pytest gives one
    directory per test, so a test that builds two baselines (a loop over
    refusal shapes) needs two names, or the second call would find the first
    repo already there and commit nothing.

    The census needs a committed record to have anything to arbitrate: an
    empty ledger is a warn (42 under --strict) and census.sh's edited-after-
    commit check skips a path with no commit, so both would report a state
    unrelated to what decide.py just did.
    """
    repo = _init_repo(tmp_path / subdir)
    record = {
        "id": BASELINE_ID,
        "date": BASELINE_DATE,
        "asked_by": "developer",
        "questions": [
            {
                "id": "q1",
                "text": "Adopt the new scheduler?",
                "options": ["yes", "no", "later"],
                "answer": "yes",
            }
        ],
        "by": "Replay",
        "scope": "release ordering",
        "status": "decided",
        "supersedes": None,
    }
    rel = f"noni/decisions/{BASELINE_ID}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"steering: {BASELINE_ID}")
    return repo


def _decide(repo: Path, *args: str, env: dict | None = None, identity: str | None = "Replay"):
    """Run decide.py with the standard flags, overridable per test.

    ``identity`` is written into the repo's own git config before the run.
    The harness identity env pins ``GIT_CONFIG_GLOBAL=/dev/null`` (so a host
    ``~/.gitconfig`` cannot leak into a test), which also blocks the local
    config ``_init_repo`` would otherwise carry, so the name decide.py reads
    for ``by`` is set here rather than inherited: naming it is also what makes
    the exit-3 test's ``identity=None`` a real absence and not a sandbox
    coincidence.
    """
    _pin_identity(repo, identity)
    return run_decide(
        repo,
        "--slug", "scheduler",
        "--date", NEW_DATE,
        *BASE, *QUESTION, *OPTIONS, *args,
        env=env,
    )


def _pin_identity(repo: Path, identity: str | None) -> None:
    """Give the repo an author name, or make sure it has none.

    ``git config --unset`` runs even for ``None``: a repo built by a previous
    helper in the same test must not keep an identity the current run means to
    withhold.
    """
    if identity is None:
        _git_e2(repo, "config", "--unset", "user.name")
        _git_e2(repo, "config", "--unset", "user.email")
        return
    _git(repo, "config", "user.name", identity)
    _git(repo, "config", "user.email", "replay@fixture.invalid")


def _census_py(repo: Path) -> tuple[int, str]:
    """The unified census under --strict: the arbiter that owns the schema.

    The hygiene class is not this writer's contract (a tree with no deny-list
    reports it as a warn, which --strict promotes to 50), so the ledger group
    is what a decide.py run is held to: --only names the three ledger checks
    plus ledger-empty, which is the group the record and its chain belong to.
    """
    args = ["--repo", str(repo), "--json", "--strict", "--now", NOW]
    for check in ("ledger-record", "ledger-edited", "ledger-chain", "ledger-empty"):
        args += ["--only", check]
    proc = subprocess.run(
        [sys.executable, str(CENSUS), *args],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _census_sh(repo: Path) -> tuple[int, str]:
    """The per-epic census.sh shim over the same ledger."""
    proc = subprocess.run(
        ["bash", str(CENSUS_SH), str(repo / "noni" / "decisions")],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _assert_both_censuses_clean(repo: Path, context: str) -> None:
    code_py, out_py = _census_py(repo)
    code_sh, out_sh = _census_sh(repo)
    assert code_py == 0, f"unified census not clean after {context} (exit {code_py}):\n{out_py}"
    assert code_sh == 0, f"census.sh not clean after {context} (exit {code_sh}):\n{out_sh}"


def _head_paths(repo: Path) -> list[str]:
    """The paths HEAD's own commit touches (no header, no rename rewriting)."""
    out = _git_e2(repo, "show", "--format=", "--name-only", "HEAD").stdout
    return [line for line in out.splitlines() if line.strip()]


def _porcelain(repo: Path, *rels: str) -> str:
    return _git_e2(repo, "status", "--porcelain", "--", *rels).stdout.strip()


def _commit_tree(repo: Path, rel: str, body: str, message: str, date: str) -> None:
    """Commit ``rel`` under a pinned date, creating parents as needed.

    Re-committing a path that is already tracked is how a fixture restates a
    record (the one legal restatement is a supersede target's ``status``).
    ``git add`` on a path whose bytes already match the index is a no-op, and
    ``git commit`` with nothing staged would fail, so the write is forced to
    differ from HEAD: a fixture that asked for the bytes HEAD already has is
    a fixture bug, and this says so rather than committing nothing.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_text(encoding="utf-8") == body:
        raise AssertionError(f"fixture commits identical bytes for {rel}: change the record")
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", message)


def _record_json(record_id: str, status: str, answer: str | None, supersedes: str | None) -> str:
    return json.dumps(
        {
            "id": record_id,
            "date": f"{record_id[:10]}T00:00:00Z",
            "asked_by": "developer",
            "questions": [
                {
                    "id": "q1",
                    "text": "Adopt the new scheduler?",
                    "options": ["yes", "no", "later"],
                    "answer": answer,
                }
            ],
            "by": "Replay",
            "scope": "release ordering",
            "status": status,
            "supersedes": supersedes,
        },
        indent=2,
    ) + "\n"


# --- writing a record ---------------------------------------------------------


def test_writes_a_decided_record_and_commits_only_that_path(tmp_path):
    """A fully answered run writes one valid record, commits exactly that path
    with 'steering: <id>', and both censuses are clean afterwards."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    assert str(_record_path(repo, NEW_ID)) in proc.stdout, proc.stdout

    record = _read(repo, NEW_ID)
    assert record["id"] == NEW_ID
    assert record["status"] == "decided"
    assert record["questions"][0]["answer"] == "next train"
    assert record["supersedes"] is None
    assert set(record) == {
        "id", "date", "asked_by", "questions", "by", "scope", "status", "supersedes"
    }
    # by is git's configured identity, not a value the caller supplied.
    assert record["by"] == "Replay"
    assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"]
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == f"steering: {NEW_ID}", subject
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "writing a decided record")


def test_unanswered_question_is_open_with_a_null_answer(tmp_path):
    """No --answer gives status open and writes the answer as null, not an
    absent key: the null form is the documented answer-absent shape."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo)
    assert proc.returncode == 0, proc.stderr

    record = _read(repo, NEW_ID)
    assert record["status"] == "open"
    question = record["questions"][0]
    assert "answer" in question, "the open form writes answer: null, it does not omit the key"
    assert question["answer"] is None
    # A partly answered record is open too, and the answered question keeps
    # its answer: status is derived from the set, never supplied.
    _assert_both_censuses_clean(repo, "writing an open record")


def test_partially_answered_record_is_open(tmp_path):
    """One answered and one unanswered question give open, with the answered
    question keeping its answer and the other carrying null."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo,
        "--slug", "two-questions",
        "--date", NEW_DATE,
        *BASE,
        *QUESTION, *OPTIONS, *ANSWERED,
        "--question", "q2=Who reviews it?",
        "--option", "q2=the operator", "--option", "q2=nobody",
    )
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, f"{NEW_DATE}-two-questions")
    assert record["status"] == "open"
    by_id = {q["id"]: q for q in record["questions"]}
    assert by_id["q1"]["answer"] == "next train"
    assert by_id["q2"]["answer"] is None
    _assert_both_censuses_clean(repo, "writing a partly answered record")


def test_source_provenance_is_written_when_both_flags_are_given(tmp_path):
    """The optional source field carries the tracker's issue and comment ids
    when both flags name them, and stays absent when neither does."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--source-issue", "42", "--source-comment", "9102")
    assert proc.returncode == 0, proc.stderr
    record = _read(repo, NEW_ID)
    assert record["source"] == {"issue_number": 42, "comment_id": 9102}
    _assert_both_censuses_clean(repo, "writing a record with source provenance")


def test_source_with_only_one_flag_is_a_usage_error(tmp_path):
    """Half a provenance is refused before anything is written: a source with
    one of its two integers would fail the census."""
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, "--source-issue", "42")
    assert proc.returncode == 2, proc.stderr
    assert "both" in proc.stderr.lower()
    assert not _record_path(repo, NEW_ID).exists()


# --- supersede ----------------------------------------------------------------


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


def test_an_empty_slug_exits_two(tmp_path):
    """An empty slug would give the record an id ending in a dash, which the
    census's filename rule rejects."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "", "--date", NEW_DATE, *BASE, *QUESTION, *OPTIONS, *ANSWERED
    )
    assert proc.returncode == 2, proc.stderr
    assert "slug" in proc.stderr


def test_a_malformed_slug_exits_two(tmp_path):
    """A slug with a dot, slash, space or uppercase letter is refused: those
    characters are what make census.sh report 10:bad-name for the whole ledger."""
    repo = _baseline_repo(tmp_path)
    for bad in ("../escape", "with.dot", "UPPER", "with space", "sla/sh"):
        proc = _run(
            repo, "--slug", bad, "--date", NEW_DATE, *BASE, *QUESTION, *OPTIONS, *ANSWERED
        )
        assert proc.returncode == 2, f"slug {bad!r}: {proc.stderr}"
        assert "slug" in proc.stderr
    # Nothing was written anywhere: the ledger holds only the baseline.
    assert sorted(p.name for p in (repo / "noni" / "decisions").glob("*.json")) == [
        f"{BASELINE_ID}.json"
    ]
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_filename_collision_exits_four(tmp_path):
    """An existing record of the same id is never overwritten: the run refuses
    (exit 4) and leaves the existing bytes alone."""
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{NEW_ID}.json"
    _commit_tree(repo, rel, _record_json(NEW_ID, "decided", "yes", None), f"steering: {NEW_ID}",
                 f"{NEW_DATE}T00:00:00Z")
    before = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 4, proc.stderr
    assert "already exists" in proc.stderr
    assert _git_e2(repo, "show", f"HEAD:{rel}").stdout == before
    assert _porcelain(repo, rel) == ""


def test_an_argparse_failure_exits_two(tmp_path):
    """A missing required flag and an unknown flag are argparse failures, which
    argparse itself reports with exit 2 — before any of decide.py's own checks
    run, so the usage error is argparse's and not a reimplementation of it."""
    repo = _baseline_repo(tmp_path)
    # --asked-by is required: argparse refuses it, and it is refused for every
    # other flag too, so no check of decide.py's own is reached.
    missing = _run(repo, "--slug", "scheduler", "--date", NEW_DATE, *QUESTION, *OPTIONS)
    assert missing.returncode == 2, missing.stderr
    assert "--asked-by" in missing.stderr or "required" in missing.stderr.lower()
    # An unknown flag is refused by name: no --status flag exists, because
    # status is derived.
    unknown = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE, *QUESTION, *OPTIONS,
        *ANSWERED, "--status", "decided",
    )
    assert unknown.returncode == 2, unknown.stderr
    assert "--status" in unknown.stderr
    assert sorted(p.name for p in (repo / "noni" / "decisions").glob("*.json")) == [
        f"{BASELINE_ID}.json"
    ]


def test_a_question_without_enough_options_exits_two(tmp_path):
    """A question with fewer than two options is a record no census would
    accept, so it is refused before any file is written."""
    repo = _baseline_repo(tmp_path)
    proc = _run(
        repo, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
        "--question", "q1=Only one way?", "--option", "q1=yes", *ANSWERED,
    )
    assert proc.returncode == 2, proc.stderr
    assert "2-4" in proc.stderr or "option" in proc.stderr.lower()
    assert _porcelain(repo, "noni/decisions") == ""


def test_a_malformed_pair_or_unknown_question_id_exits_two(tmp_path):
    """An --answer with no '=' or naming a question nobody asked cannot attach
    to anything, so both are usage errors."""
    repo = _baseline_repo(tmp_path)
    no_equals = _decide(repo, "--answer", "just-a-value")
    assert no_equals.returncode == 2, no_equals.stderr
    assert "ID=" in no_equals.stderr
    unknown_id = _decide(repo, *ANSWERED, "--answer", "q9=anything")
    assert unknown_id.returncode == 2, unknown_id.stderr
    assert "q9" in unknown_id.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_too_many_questions_exits_two(tmp_path):
    """A fifth question is outside the 1-4 bound both censuses enforce."""
    repo = _baseline_repo(tmp_path)
    args = ["--slug", "many", "--date", NEW_DATE, *BASE]
    for index in range(1, 6):
        args += ["--question", f"q{index}=Question {index}?",
                 "--option", f"q{index}=a", "--option", f"q{index}=b"]
    proc = _run(repo, *args)
    assert proc.returncode == 2, proc.stderr
    assert "1-4" in proc.stderr


def test_a_bad_date_exits_two(tmp_path):
    """A --date that is not a real YYYY-MM-DD day would produce an id and a
    date field the census rejects, so it is refused up front."""
    repo = _baseline_repo(tmp_path)
    for bad in ("2026-13-01", "not-a-date", "2026-10"):
        proc = _run(
            repo, "--slug", "scheduler", "--date", bad, *BASE, *QUESTION, *OPTIONS, *ANSWERED
        )
        assert proc.returncode == 2, f"--date {bad}: {proc.stderr}"
        assert "--date" in proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""


# --- the commit path ----------------------------------------------------------


def _forced_commit_failure():
    """The env a decide.py run needs to have its commit fail on purpose.

    The exit-5 rollback path is unreachable through inputs: every input that
    could make git refuse the commit is refused earlier by an exit 2, 3 or 4
    check, so the only way to watch a rollback happen is to inject the failure.
    The injection is a real (if narrow) property of the product: a committed
    record's bytes can be clobbered out of band, which is exactly the state the
    rollback exists to undo, and no input flag reproduces it.

    The variable's name comes from decide.py's own ``FAIL_COMMIT_ENV_VAR``
    constant (read off the loaded module, not copied), so renaming the seam in
    the product fails these two tests instead of leaving them quietly exercising
    a real commit.

    The env seam has exactly one value, ``1``: it makes the commit step fail and
    nothing else. A per-verb or per-rc form is not a property of the writer, so
    the tests that need one specific git call to fail inject it in-process
    (``_git_spy``) instead of widening the variable.
    """
    return {**_identity_env(), _decide_module().FAIL_COMMIT_ENV_VAR: "1"}


def _decide_module():
    """decide.py loaded as a module, for the constants its tests name."""
    from _harness import _decide_module as load

    return load()


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


def test_a_supersede_without_a_date_exits_two(tmp_path):
    """The chain's date is the target's date; without --date there is nothing
    to match it against, so the run asks for it instead of inventing one."""
    repo = _baseline_repo(tmp_path)
    proc = run_decide(
        repo,
        "--slug", "scheduler", *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 2, proc.stderr
    assert "--date" in proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""


def test_the_ledger_directory_is_created_for_the_first_record(tmp_path):
    """A fresh attached project has no noni/decisions yet: the writer allocates
    the directory that holds its own record rather than failing."""
    repo = _init_repo(tmp_path / "fresh")
    assert not (repo / "noni" / "decisions").exists()
    proc = _decide(repo, *ANSWERED)
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


# --- the hardening round --------------------------------------------------------
#
# Eight properties a reviewer asked for, each with the failure it closes. They
# are written first and observed failing, so a green suite means the writer
# was changed and not merely re-described.


def _non_canonical_target_repo(
    tmp_path: Path, body: str, name: str = "odd", target_id: str | None = None
) -> tuple[Path, str, str]:
    """A repo whose committed target is ``body`` verbatim.

    ``target_id`` is the record's id and defaults to ``<BASELINE date>-<name>``;
    a fixture that builds its bytes from another id passes it so the record's
    own ``id`` field and its filename agree. The commit bypasses
    ``_commit_tree``'s identical-bytes guard on purpose: these fixtures commit
    bytes the writer itself would not have produced, and the whole point is
    that HEAD holds them exactly as given.
    """
    repo = _baseline_repo(tmp_path, f"target-{name}")
    target_id = target_id or f"{BASELINE_ID[:10]}-{name}"
    rel = f"noni/decisions/{target_id}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"fixture: odd target {name}")
    return repo, rel, target_id


def _canonical_body(target_id: str, status: str = "decided") -> str:
    """``target_id``'s record in the writer's canonical bytes (the _render form).

    The record is built by the fixture helper and rendered by the writer's own
    _render, so the bytes a canonical fixture commits are exactly the bytes this
    writer would have written for that record.
    """
    record = json.loads(_record_json(target_id, status, "yes", None))
    return _decide_module()._render(record)


def _subcommand(cmd: list[str]) -> str:
    """The git subcommand of a _git command line: the first argument past the
    ``-C <repo>`` pair and any ``-c <key=value>`` hardening options.

    A spy that monkeypatches subprocess.run needs this rather than a fixed
    index: the hardening options sit between -C and the subcommand, so the
    position of the verb moves when they are added.
    """
    index = 1
    while index < len(cmd):
        arg = cmd[index]
        if arg in ("-C", "-c"):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg
    return ""


def _git_spy(failures: dict[str, tuple[int, str]]) -> None:
    """Make the writer's git calls answer ``failures[verb]`` with that rc.

    subprocess.run is replaced in the namespace ``run_git`` looks the name up in,
    taken from the helper's one cached load, so the product file is never modified
    and every writer run in this session resolves through the same spy. A verb
    outside ``failures`` runs for real, so the run reaches the call under test
    with its normal surroundings; each stand-in carries no stdout, as a hung or
    refused call does.

    The spy answers only the repo of the run in flight (``_RUN_REPO``), which is
    what keeps the harness's own fixture calls real while sys.modules is shared.
    A test that installs it drives the writer with ``_decide_in_process``, which
    sets both knobs for that run; a launched interpreter is a different process
    and never sees them.
    """
    gitwrite = _gitwrite_module()
    real_run = gitwrite.run_git.__globals__["subprocess"].run
    claimed = dict(failures)
    # The repo is snapshotted here, not read at call time: _writer_git_call reads
    # the module-level name, and a test that assigned it as a local would leave
    # the spy answering no call at all (the symptom that sent one run down to a
    # later guard's refusal instead of the injected failure).
    repo_under_test = _RUN_REPO[0]

    def _spy(cmd, *args, **kwargs):
        argv = [str(part) for part in cmd]
        verb = _subcommand(argv)
        if verb in claimed and _writer_git_call(argv, repo_under_test):
            rc, stderr = claimed[verb]
            return subprocess.CompletedProcess(argv, returncode=rc, stdout="",
                                               stderr=stderr)
        return real_run(cmd, *args, **kwargs)

    gitwrite.run_git.__globals__["subprocess"].run = _spy


def _writer_git_call(cmd: list[str], repo: Path | None) -> bool:
    """Whether ``cmd`` is the writer's own hardened call in the repo under test.

    sys.modules is process-wide, so while an in-process run is going on the
    harness's fixture calls (git init, add, commit) pass through the same spy
    installed in front of it. Matching the run's ``-C`` directory is what keeps
    those calls real: only the writer's calls in the repo under test are answered.
    """
    if repo is None or cmd[:1] != ["git"] or len(cmd) < 3 or cmd[1] != "-C":
        return False
    if not any(arg == "protocol.ext.allow=never" for arg in cmd):
        return False
    try:
        return Path(cmd[2]).resolve() == repo
    except OSError:
        return False


# The repository of the in-process run currently in flight, or [None].
_RUN_REPO: list[Path | None] = [None]


def _gitwrite_module():
    """The git helper module the writer itself uses, so a spy on its
    subprocess.run is the one ``run_git`` resolves through.

    The writer's own load is reused once one has happened (it is registered under
    the name decide.py binds it to); otherwise the helper is exec'd once under a
    name of our own. Either way this session has exactly one module object per
    name, and a spy installed in front of it never touches the product file or the
    harness's git calls.
    """
    module = sys.modules.get("noni_gitwrite") or sys.modules.get(_GITWRITE_TEST_NAME)
    if module is None:
        path = DECIDE.parent / "gitwrite.py"
        spec = importlib.util.spec_from_file_location(_GITWRITE_TEST_NAME, path)
        if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
            raise RuntimeError(f"cannot load the git helper from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_GITWRITE_TEST_NAME] = module
        spec.loader.exec_module(module)
    return module


_GITWRITE_TEST_NAME = "noni_gitwrite_under_test"


def _decide_in_process(repo: Path, *args: str, env: dict | None = None,
                       failures: dict[str, tuple[int, str]] | None = None,
                       monkeypatch=None) -> subprocess.CompletedProcess[str]:
    """Run the writer in this process, so a spy sees its git calls, and report
    what a launched run would have reported.

    The launched route (``_decide`` / ``run_decide``) cannot observe a patch of
    this process's subprocess.run, so the tests that inject a specific git call's
    failure drive the writer here instead. The flag set matches ``_decide``'s
    (``--slug scheduler --date NEW_DATE`` plus BASE, QUESTION and OPTIONS), with
    ``args`` appended as ``_decide`` appends them. stdout and stderr are captured
    the way the CLI's prints and ``_fail`` write them, and the exit code is
    main()'s return value. The identity is pinned in the repo's config first, as
    ``_decide`` does, because decide.py reads ``by`` from git config.

    The seam variable is cleared for the run unless ``env`` sets it, so an
    in-process run cannot inherit a forced failure a sibling test left in this
    process's environment. The test's ``monkeypatch`` fixture is used when given:
    a launched fixture call inherits this process's environment, and an
    unpersisted seam would force a failure inside the harness's own git commit.

    ``failures`` is this run's per-verb injection (verb -> ``(returncode,
    stderr)``), installed through ``_git_spy`` and scoped to ``repo`` for the
    duration of the run; with none the run is a plain in-process run.

    The helper spy is installed before the writer is loaded, so the module object
    decide.py binds its constants through is the one carrying the spy.
    """
    _pin_identity(repo, "Replay")
    argv = ["--repo", str(repo), "--slug", "scheduler", "--date", NEW_DATE,
            *BASE, *QUESTION, *OPTIONS, *args]
    seam = _decide_module().FAIL_COMMIT_ENV_VAR
    run_env = {seam: None, **(env or {})}
    saved = {key: os.environ.get(key) for key in run_env}
    previous_repo = _RUN_REPO[0]
    _RUN_REPO[0] = repo.resolve()
    try:
        _git_spy(failures or {})
        for key, value in run_env.items():
            if monkeypatch is not None:
                if value is None:
                    monkeypatch.delenv(key, raising=False)
                else:
                    monkeypatch.setenv(key, value)
            elif value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _decide_module().main(argv)
    finally:
        _RUN_REPO[0] = previous_repo
        if monkeypatch is None:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return subprocess.CompletedProcess(argv, returncode=code,
                                       stdout=out.getvalue(), stderr=err.getvalue())


def _supersede(repo: Path, target_id: str,
               env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """The standard supersede of ``target_id``, for the hardening tests."""
    return _run(
        repo,
        "--slug", "scheduler",
        "--date", BASELINE_ID[:10],
        *BASE, *QUESTION, *OPTIONS, *ANSWERED,
        "--supersedes", target_id,
        env=env,
    )


def test_hardening_non_utf8_target_refuses_with_four_and_echoes_nothing(tmp_path):
    """A committed target whose bytes are not UTF-8 is a refused supersede
    (exit 4), not a traceback, and its bytes reach neither stream.

    The clobber is a real out-of-band state (the same class the exit-5 seam
    models): a reader that lets UnicodeDecodeError escape would end the run
    with a traceback instead of the refusal, and a reader that quoted the
    bytes would put them on the operator's terminal. The junk bytes are built
    from integers, not written as escapes, so the fixture carries no invalid
    escape sequence of its own.
    """
    repo = _baseline_repo(tmp_path)
    rel = f"noni/decisions/{BASELINE_ID}.json"
    junk = b'{"id": "x", "scope": "' + bytes([0x83, 0x92, 0xC3, 0x28, 0xA0]) + b'"}\n'
    (repo / rel).write_bytes(junk)
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", "fixture: target clobbered out of band")

    proc = _supersede(repo, BASELINE_ID)
    assert proc.returncode == 4, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "JSON object" in proc.stderr, proc.stderr
    # Neither stream carries a byte of the target, nor a stand-in for one.
    for stream in (proc.stdout, proc.stderr):
        assert "\ufffd" not in stream, stream
        assert "\\x" not in stream, stream
    # The refusal writes nothing: the clobbered target stays on disk as planted
    # and the tree is clean, so HEAD still holds the bytes just committed.
    assert (repo / rel).read_bytes() == junk
    assert _porcelain(repo) == ""
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists()


def test_hardening_rollback_names_the_path_it_could_not_restore(tmp_path):
    """A path the rollback cannot put back is named, not hidden: the new
    record's path is held by a directory planted after the collision check, so
    the write fails, the rollback's unlink fails with it, and the run exits 5
    naming that leftover exactly as the commit-failure branch names one.

    Silently leaving the ledger holding a directory where a record belongs would
    be worse than the failure the rollback recovers from: the censuses read it
    and the operator is never told which path to clear by hand.
    """
    repo = _baseline_repo(tmp_path)
    # The new record's own path, which the collision check passed while nothing
    # was there, is taken by a directory before the run writes it.
    record_rel = f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json"
    (repo / record_rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / record_rel).mkdir()
    env = {**_identity_env()}

    proc = _supersede(repo, BASELINE_ID, env=env)
    assert proc.returncode == 5, proc.stderr
    assert "rollback did not finish" in proc.stderr, proc.stderr
    assert record_rel in proc.stderr, proc.stderr
    assert (repo / record_rel).is_dir(), (
        "the leftover is the planted directory: the rollback's unlink cannot "
        "remove what it is not a file, which is why the message must name it"
    )


def test_hardening_a_timeout_on_a_guard_probe_refuses_with_three(tmp_path, monkeypatch):
    """A guard probe (rev-parse, ls-files, status, config, show) that times out
    is a git problem (exit 3) naming the command, never a clean answer.

    The writer's timeout is injected in-process: the spy answers the call for
    the probe with GIT_TIMEOUT_RC and nothing, so the writer has no returncode
    to read as 'a work tree' and must refuse. rc 124 is not zero, and a probe
    whose timeout were read as rc 0 would have gone on to write the record,
    which the exit code and the absent file together rule out.
    """
    module = _decide_module()
    assert module.GIT_TIMEOUT_RC == 124
    repo = _baseline_repo(tmp_path)
    hung = f"git rev-parse timed out after {module.GIT_TIMEOUT}s"
    proc = _decide_in_process(repo, *ANSWERED, env=_identity_env(), monkeypatch=monkeypatch,
                              failures={"rev-parse": (module.GIT_TIMEOUT_RC, hung)})
    assert proc.returncode == 3, proc.stderr
    assert "timed out" in proc.stderr.lower(), proc.stderr
    assert "rev-parse" in proc.stderr, proc.stderr
    assert _porcelain(repo) == ""
    assert not _record_path(repo, NEW_ID).exists()


def test_hardening_a_timeout_on_commit_goes_through_rollback_with_five(tmp_path, monkeypatch):
    """A commit that times out is a failed commit: the run rolls the path back
    and exits 5 naming the command, rather than reporting success.

    The spy stands a hang in for the commit itself, so the writer sees a call
    that ran past GIT_TIMEOUT and returned nothing; the record it wrote must be
    gone and HEAD must be where it was.
    """
    module = _decide_module()
    repo = _baseline_repo(tmp_path)
    hung = f"git commit timed out after {module.GIT_TIMEOUT}s"
    proc = _decide_in_process(repo, *ANSWERED, env=_identity_env(), monkeypatch=monkeypatch,
                              failures={"commit": (module.GIT_TIMEOUT_RC, hung)})
    assert proc.returncode == 5, proc.stderr
    assert "commit" in proc.stderr.lower() and "timed out" in proc.stderr.lower(), proc.stderr
    rel = f"noni/decisions/{NEW_ID}.json"
    assert _porcelain(repo, rel) == "", _porcelain(repo)
    assert not _record_path(repo, NEW_ID).exists()
    assert _head_paths(repo) == [f"noni/decisions/{BASELINE_ID}.json"]


def test_hardening_a_failing_reset_is_reported_and_not_claimed_rolled_back(tmp_path,
                                                                            monkeypatch):
    """A reset that fails is an undo that failed, so the run must say so and
    name the paths that may still be staged.

    Only GIT_TIMEOUT_RC counted as a bad reset, so a reset that answered 128 (or
    1, or 129) was read as success: the exit-5 message then promised a tree
    rolled back to its state before the run while the index kept this run's
    paths staged. The commit failure comes from the env seam (``1``) and the
    reset failure is injected in-process with a non-124 code, which is the
    answer the old code treated as clean. The record file's absence is the
    control that says the rest of the rollback still ran.
    """
    module = _decide_module()
    repo = _baseline_repo(tmp_path)
    # 128 is git's own general failure: a real reset failure, never a timeout.
    env = {**_identity_env(), module.FAIL_COMMIT_ENV_VAR: "1"}
    proc = _decide_in_process(repo, *ANSWERED, env=env, monkeypatch=monkeypatch,
                              failures={"reset": (128,
                                                  "git reset failed: unable to lock index")})
    rel = f"noni/decisions/{NEW_ID}.json"
    assert proc.returncode == 5, proc.stderr
    low = proc.stderr.lower()
    assert "reset" in low, proc.stderr
    assert rel in proc.stderr, "the message must name the path that may still be staged"
    assert "rolled back to their state before this run" not in low, proc.stderr
    assert not _record_path(repo, NEW_ID).exists()


def test_seam_value_that_is_not_one_is_inert_and_the_run_writes(tmp_path):
    """A NONI_DECIDE_FAIL_COMMIT value that is not ``1`` answers nothing.

    The old ``<rc>:<verb>`` form let a stray environment value fail one named git
    call, which is not a property of the writer. With each of those values the
    run is a normal run: it commits its record and prints the one 'wrote' line.
    """
    module = _decide_module()
    for index, inert in enumerate(("42:config", "7:ls-files", "", "0", "yes", "1:commit")):
        repo = _baseline_repo(tmp_path, subdir=f"repo-inert-{index}")
        env = {**_identity_env(), module.FAIL_COMMIT_ENV_VAR: inert}
        proc = _decide(repo, *ANSWERED, env=env)
        assert proc.returncode == 0, f"seam {inert!r}: {proc.stderr}"
        assert _record_path(repo, NEW_ID).is_file(), f"seam {inert!r} wrote nothing"
        assert _read(repo, NEW_ID)["id"] == NEW_ID
        assert _head_paths(repo) == [f"noni/decisions/{NEW_ID}.json"]


def test_hardening_a_repo_local_pre_commit_hook_does_not_run(tmp_path):
    """A repo-local pre-commit hook is not run by this writer.

    The hook here exits 0 and writes a marker, so a run that honoured it would
    leave the marker behind and exit 0 anyway: the marker's absence is the
    assertion, and the record's presence is the control that says the commit
    itself happened.
    """
    repo = _baseline_repo(tmp_path)
    marker = repo / "HOOK_RAN"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n" + "printf x > " + str(marker) + "\nexit 0\n", encoding="utf-8"
    )
    hook.chmod(0o755)

    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, proc.stderr
    assert _record_path(repo, NEW_ID).is_file(), "the commit itself must still happen"
    assert not marker.exists(), "decide.py ran a hook it must not run"
    # Identity still comes from the tree's config: hardening the call must not
    # neutralise global config, whose user.name is what `by` reads.
    assert _read(repo, NEW_ID)["by"] == "Replay"
    _assert_both_censuses_clean(repo, "a commit run with hooks disabled")


def test_hardening_supersede_refuses_a_target_the_writer_would_rewrite(tmp_path):
    """A target outside the writer's canonical form is refused (exit 4) rather
    than rewritten: the supersede must change the status value and no other
    byte, which it cannot promise for bytes it would not have written.

    Two shapes are refused here: an unknown extra field, which the writer's
    FIELD_ORDER render would drop, and a different indent, which it would
    re-flow. The positive control below is the byte test that proves the
    refusal is not over-broad.
    """
    probe_id = f"{BASELINE_ID[:10]}-probe"
    canonical = json.loads(_canonical_body(probe_id))
    extra_field = json.dumps({**canonical, "operator_note": "not in the writer's field order"},
                             indent=2) + "\n"
    odd_indent = json.dumps(canonical, indent=4) + "\n"
    for label, body in (("extra-field", extra_field), ("odd-indent", odd_indent)):
        # Same bytes, committed under the name the writer is asked to supersede:
        # the id inside is probe's, so the refusal under test can only be the
        # canonical-form rule and not the id/name mismatch.
        repo, rel, target_id = _non_canonical_target_repo(tmp_path, body, label, probe_id)
        # The fixture's own bytes must differ from the canonical form they were
        # built from, or the test would assert on a target that needed no
        # refusal at all.
        assert body != _canonical_body(probe_id), label
        before = _git_e2(repo, "show", f"HEAD:{rel}").stdout
        proc = _supersede(repo, target_id)
        assert proc.returncode == 4, f"{label}: {proc.stderr}"
        assert "canonical" in proc.stderr.lower(), f"{label}: {proc.stderr}"
        assert _git_e2(repo, "show", f"HEAD:{rel}").stdout == before, label
        assert _porcelain(repo) == "", label
        assert not (repo / f"noni/decisions/{BASELINE_ID[:10]}-scheduler.json").exists()


def test_hardening_a_canonical_target_still_supersedes_by_the_status_line_only(tmp_path):
    """The positive control: a canonical target is superseded, and the raw
    committed text differs from HEAD's in the status line and nowhere else."""
    target_id = f"{BASELINE_ID[:10]}-canonical"
    repo, rel, _id = _non_canonical_target_repo(tmp_path, _canonical_body(target_id),
                                                "canonical", target_id)
    before = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    assert json.loads(before)["status"] == "decided"
    proc = _supersede(repo, target_id)
    assert proc.returncode == 0, proc.stderr
    after = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines), (before_lines, after_lines)
    differing = [(a, b) for a, b in zip(before_lines, after_lines, strict=True) if a != b]
    assert differing == [('  "status": "decided",', '  "status": "superseded",')], differing


def test_hardening_written_files_are_not_owner_only(tmp_path):
    """A record written by decide.py is readable like any other project file:
    mkstemp's 0600 must be widened before os.replace, masked by the umask, and
    a superseded target keeps the mode it already had."""
    umask = os.umask(0o022)
    try:
        expected = 0o644 & ~umask
        repo = _baseline_repo(tmp_path)
        # A baseline the writer did not make, so its mode proves nothing yet.
        target_rel = f"noni/decisions/{BASELINE_ID}.json"
        (repo / target_rel).chmod(0o644)
        proc = _decide(repo, *ANSWERED, "--source-issue", "7", "--source-comment", "8")
        assert proc.returncode == 0, proc.stderr
        written = _record_path(repo, NEW_ID).stat().st_mode & 0o777
        assert written == expected, oct(written)
        assert written != 0o600, "a 0600 record is unreadable to the census's usual reader"

        proc = _supersede(repo, BASELINE_ID)
        assert proc.returncode == 0, proc.stderr
        flipped = (repo / target_rel).stat().st_mode & 0o777
        assert flipped == expected, oct(flipped)
    finally:
        os.umask(umask)


def test_hardening_source_ids_must_be_positive(tmp_path):
    """--source-issue and --source-comment are tracker ids: zero or negative is
    a usage error (exit 2), refused before anything is written."""
    repo = _baseline_repo(tmp_path)
    for flag in ("--source-issue", "--source-comment"):
        other = "--source-comment" if flag == "--source-issue" else "--source-issue"
        for bad in ("0", "-1"):
            proc = _decide(repo, *ANSWERED, flag, bad, other, "7")
            assert proc.returncode == 2, f"{flag} {bad}: {proc.stderr}"
            assert flag in proc.stderr, proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""
    assert sorted(p.name for p in (repo / "noni/decisions").glob("*.json")) == [
        f"{BASELINE_ID}.json"
    ]


def test_hardening_docs_state_the_refusals_the_code_performs(tmp_path):
    """The docstring's exit 4 table and exit 3's hint are what the code does.

    The old wording claimed a target "belongs to another chain" (nothing
    refuses that) and omitted the two refusals the hardening round added, so a
    reader of the table could not predict a run's exit code. The hint text is
    checked against the runtime hint for the same reason: a doc that names a
    different command than the one stderr names is two contracts, one stale.
    """
    doc = _docstring(_decide_ast())
    lines = doc.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "Exit codes:")
    block: dict[int, str] = {}
    current: int | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif current is not None:
            block[current] += " " + line.strip()
    four = block[4].lower()
    for condition in ("missing", "already superseded", "untracked", "locally modified",
                      "canonical", "another day"):
        assert condition in four, f"docstring's exit 4 omits {condition!r}: {block[4]}"
    three = block[3].lower()
    assert "is not a git work tree" in three
    assert "git config user.name is not set" in three
    # The runtime hint for the identity refusal is the same wording, not a
    # different command: doc and stderr say one thing.
    repo = _baseline_repo(tmp_path)
    proc = _decide(repo, *ANSWERED, env=_no_identity_env(tmp_path), identity=None)
    assert proc.returncode == 3, proc.stderr
    assert "git config user.name is not set" in proc.stderr, proc.stderr
    # Same for the timeout hint: the table promises a git probe that timed out is
    # a git problem, and the runtime message says so and names the command.
    module = _decide_module()
    hung = f"git rev-parse timed out after {module.GIT_TIMEOUT}s"
    timed = _decide_in_process(repo, *ANSWERED, env=_identity_env(),
                               failures={"rev-parse": (module.GIT_TIMEOUT_RC, hung)})
    assert timed.returncode == 3, timed.stderr
    assert "timed out" in timed.stderr and "rev-parse" in timed.stderr, timed.stderr


def _no_identity_env(tmp_path: Path) -> dict:
    """An env with no gitconfig anywhere and no author vars: the identity-less run."""
    return {
        "PATH": sys.executable.rsplit("/", 2)[0] + ":/usr/bin:/bin",
        "HOME": str(tmp_path / "no-home"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }


# --- the doc / code contract --------------------------------------------------


def _identity_env() -> dict:
    """The harness git identity, for a test that must add one variable."""
    return dict(_harness_identity_env())


def _decide_ast() -> ast.Module:
    return _script_ast(DECIDE)


def _docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "decide.py has no module docstring"
    return doc


def _module_exit_codes(tree: ast.Module) -> set[int]:
    """The codes the EXIT_* module constants hold, read from the source."""
    codes: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{target.id} is not an int"
                codes.add(value.value)
    assert codes, "decide.py defines no EXIT_* constants"
    return codes


def _doc_exit_codes(doc: str) -> set[int]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Exit codes:")
    except StopIteration:
        raise AssertionError("docstring has no 'Exit codes:' block") from None
    codes: set[int] = set()
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            codes.add(int(head[0]))
    assert codes, "the 'Exit codes:' block lists no codes"
    return codes


def _parser_flags(tree: ast.Module) -> set[str]:
    """The long options the parser declares, read from main()."""
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value.startswith("--"):
                            flags.add(arg.value)
    assert flags, "no add_argument calls found in main()"
    return flags


def _doc_usage_flags(doc: str) -> set[str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Usage:")
    except StopIteration:
        raise AssertionError("docstring has no 'Usage:' block") from None
    flags: set[str] = set()
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, "the 'Usage:' block names no flags"
    return flags


def test_docstring_exit_codes_match_the_exit_constants():
    """The docstring's exit table and the EXIT_* constants are one contract,
    pinned to the settled set 0/2/3/4/5."""
    tree = _decide_ast()
    published = _module_exit_codes(tree)
    documented = _doc_exit_codes(_docstring(tree))
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}"
    )
    assert published == {0, 2, 3, 4, 5}, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block and the block
    names nothing the parser would reject; no --push, --status or --by."""
    tree = _decide_ast()
    parser = _parser_flags(tree) - {"--help"}
    documented = _doc_usage_flags(_docstring(tree))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--status", "--by"):
        assert forbidden not in parser, f"{forbidden} is out of scope for decide.py"


def test_record_field_order_and_null_answer_form_are_the_written_shape(tmp_path):
    """The bytes on disk are the documented shape: the eight fields in order,
    source last when present, and answer null (not absent) for an open
    question."""
    repo = _baseline_repo(tmp_path)
    assert _decide(repo, "--source-issue", "7", "--source-comment", "8").returncode == 0
    body = _record_path(repo, NEW_ID).read_text(encoding="utf-8")
    keys = list(json.loads(body))
    assert keys == [
        "id", "date", "asked_by", "questions", "by", "scope", "status", "supersedes", "source",
    ], keys
    assert '"answer": null' in body, body
    assert body.endswith("\n")


# --- the docs and the skill layout -------------------------------------------


def test_skill_md_documents_the_writer_within_the_line_cap():
    """SKILL.md documents decide.py (Usage, supersede, the declined/open null
    form, the exit table) and stays inside the 400-line cap."""
    text = (REPO / "skills" / "steering-ledger" / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/decide.py" in text, "SKILL.md does not document the writer"
    assert "--supersedes" in text and "--no-commit" in text
    assert "declin" in text.lower(), "SKILL.md must say a declined steer is an open record"
    assert text.count("\n") <= 400, f"SKILL.md is {text.count(chr(10))} lines; the cap is 400"
    for code in (0, 2, 3, 4, 5):
        assert f"| `{code}` |" in text, f"SKILL.md's exit table omits decide.py code {code}"


def test_skill_layout_includes_the_writer_and_its_executable_bit():
    """The skill's layout assertion knows about scripts/decide.py, and the
    writer is executable like census.sh and the other skill scripts."""
    assert (REPO / "skills" / "steering-ledger" / "scripts" / "decide.py").is_file()
    assert (DECIDE).stat().st_mode & 0o111, "decide.py is not executable"
    layout = (REPO / "tests" / "test_skill_scrub.py").read_text(encoding="utf-8")
    assert "scripts/decide.py" in layout, "test_skill_scrub.py does not assert decide.py's presence"


def test_no_doc_still_states_the_answer_absent_form():
    """Every doc that stated the answer-absent form now states the null form.

    The stale wording is a claim about the record ("`answer` absent", "the
    answer absent"), not any sentence containing the words: a ValueError that
    says a verdict "must carry no answer" is about the verdict, not the ledger
    shape. The negative control below pins that the probe is not vacuous — if
    the pattern ever stops matching the wording it exists to catch, this test
    fails too.
    """
    checked = [
        REPO / "skills" / "steering-ledger" / "SKILL.md",
        REPO / "skills" / "steering-ledger" / "references" / "decisions.md",
        REPO / "skills" / "steering-ledger" / "references" / "modes.md",
        REPO / "integrations" / "README.md",
        REPO / "integrations" / "github-issues" / "README.md",
        REPO / "integrations" / "adapter_protocol.py",
    ]
    stale = re.compile(
        r"`answer` (?:is )?absent|\banswer absent\b|the answer absent|"
        r"with (?:no|absent) answer",
        re.IGNORECASE,
    )
    for path in checked:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            assert not stale.search(line), f"{path.relative_to(REPO)}:{lineno}: {line.strip()}"
        if path.suffix == ".md":
            assert "null" in text, f"{path.relative_to(REPO)} never states the null form"
    # The probe bites the wording it was written for.
    for wording in (
        "every question's `answer` absent",
        "persisted with answer absent and status open",
        "persisted as status: open with the answer absent",
        "persisted as status: open with no answer",
    ):
        assert stale.search(wording), f"the probe no longer catches {wording!r}"


def test_the_decline_rule_matches_the_writers_open_chain_root():
    """references/modes.md's decline rule says what the writer does: a declined
    steer that is recorded at all is an open chain-root record, and a supersede
    needs every answer."""
    text = (
        REPO / "skills" / "steering-ledger" / "references" / "modes.md"
    ).read_text(encoding="utf-8")
    assert "chain-root record" in text, "modes.md must name the open chain-root form"
    assert "null" in text, "modes.md must state the null answer form"
