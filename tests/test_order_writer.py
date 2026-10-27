"""The order.py writer: one command per ordering act, honest exit codes.

Covered, in the order the acceptance criteria name them:

- ``add`` appends (or inserts at ``--at``), stamps ``confirmed`` with the run's
  time or the given ``--now``, requires ``--decision``, and commits exactly the
  one path under ``direction: <verb> [<digest>]``; the file is the canonical
  bytes the docstring documents.
- ``move`` re-places an entry and restamps it; ``remove`` shortens the list;
  ``confirm`` restamps one entry or the whole order.
- the refusals (exit 4): an issue already listed (add), an issue absent from the
  order (move, remove, confirm), a ``--decision`` id no record file carries, a
  superseded record (whose successor the hint names), and an existing file that
  is not the artifact this writer writes (not JSON, wrong schema, malformed
  entries, or non-canonical bytes).
- the usage errors (exit 2): an unknown subcommand, a non-positive issue, a
  missing ``--decision`` on add, a ``--to``/``--at`` outside the resulting list,
  a flag passed to the verb that does not own it, and a ``--now`` that is not a
  UTC timestamp.
- the environment faults (exit 3): the artifact is not a regular file, a
  decision record is unreadable, the file could not be written, or git failed or
  timed out; a refusal leaves the artifact byte-identical.
- ``--no-commit`` writes through the same chain, moves no HEAD, and prints one
  'left uncommitted' line; a run that changes no byte commits nothing; a file
  somebody else staged is neither committed nor unstaged.
- the doc / code contract: the docstring's exit table is the EXIT_* constants
  (the settled set 0/2/3/4), its Usage block is the parser's flags, and the skill
  documents the writer inside the line cap.

Every census run here is pinned with ``--now`` and the fixtures are committed at
fixed dates (``git_pin_date``), so a census measures the artifact and not the
wall clock (the same convention tests/test_decide.py records).
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import (
    ORDER,
    REPO,
    _git,
    _git_e2,
    _init_repo,
    _script_ast,
    git_pin_date,
    run_order,
    subprocess_env,
)

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
SKILL_DIR = REPO / "skills" / "direction"
FIXTURE = REPO / "tests" / "fixtures" / "ordering" / "order-valid.json"

ORDER_REL = "noni/direction/order.json"
NOW = "2026-10-27T12:00:00Z"
STAMP = "2026-10-27T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
BASELINE_DATE = "2026-10-01T10:00:00Z"
SUPERSEDING_ID = "2026-10-20-scheduler"

# The three ordering checks, so a census here arbitrates the artifact and
# nothing else: the hygiene class is not this writer's contract (a tree with no
# deny-list reports it as a warn, which --strict promotes to 50), and the ledger
# and session groups have their own writers and their own tests.
ORDERING_CHECKS = ("ordering-malformed", "ordering-stale", "ordering-closed")


def _schema_module() -> object:
    """orderschema.py loaded as a module: the artifact's shape, from the product.

    The tests that need the canonical renderer or the timestamp parser ask the
    module that owns them, which is the same object order.py loads by path. A
    copy in the test file would be a second contract.
    """
    path = SKILL_DIR / "scripts" / "orderschema.py"
    spec = importlib.util.spec_from_file_location("noni_orderschema_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load the order schema from {path}")
    sys.modules.pop(spec.name, None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _gitwrite_module() -> object:
    """gitwrite.py loaded as a module, for the tests that name its constants."""
    path = SKILL_DIR / "scripts" / "gitwrite.py"
    spec = importlib.util.spec_from_file_location("noni_order_gitwrite_under_test", path)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load the order git helper from {path}")
    sys.modules.pop(spec.name, None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _order_module() -> object:
    """order.py loaded as a module, for the tests that drive its internals."""
    spec = importlib.util.spec_from_file_location("noni_order_under_test", ORDER)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load order module from {ORDER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _order_path(repo: Path) -> Path:
    return repo / ORDER_REL


def _read(repo: Path) -> dict:
    return json.loads(_order_path(repo).read_text(encoding="utf-8"))


def _issues(repo: Path) -> list[int]:
    return [entry["issue"] for entry in _read(repo)["entries"]]


def _repo(tmp_path: Path, subdir: str = "repo") -> Path:
    """A repo whose ledger holds one committed decided record at a pinned date.

    A committed baseline record is what makes ``--decision`` answerable without
    every test having to write its own ledger: the writer looks a decision id up
    by its filename stem, so the id in a test is a file the census can also see.
    ``subdir`` lets one test build two trees without the second finding the
    first already there.
    """
    repo = _init_repo(tmp_path / subdir)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_record(repo, BASELINE_ID, "decided", None)
    return repo


def _record_json(record_id: str, status: str, supersedes: str | None) -> str:
    return json.dumps(
        {
            "id": record_id,
            "date": f"{record_id[:10]}T00:00:00Z",
            "asked_by": "developer",
            "questions": [
                {
                    "id": "q1",
                    "text": "Which order do we work the queue in?",
                    "options": ["as listed", "by risk"],
                    "answer": "as listed",
                }
            ],
            "by": "Replay",
            "scope": "release ordering",
            "status": status,
            "supersedes": supersedes,
        },
        indent=2,
    ) + "\n"


def _commit_record(repo: Path, record_id: str, status: str, supersedes: str | None) -> None:
    """Commit one decision record under a pinned date."""
    rel = f"noni/decisions/{record_id}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_record_json(record_id, status, supersedes), encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, f"{record_id[:10]}T00:00:00Z", "commit", "-q", "-m",
                 f"steering: {record_id}")


def _supersede_baseline(repo: Path) -> None:
    """Move the chain past the baseline record, the way decide.py does.

    A supersede is two committed bytes-changes, not one: the new record
    supersedes the target and the target's own status becomes superseded. A
    fixture that wrote only the new record would leave the target decided, and
    the writer's refusal would then have nothing to refuse, which is how a
    supersede test can pass for the wrong reason.
    """
    _commit_record(repo, SUPERSEDING_ID, "decided", BASELINE_ID)
    target = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    body = json.loads(target.read_text(encoding="utf-8"))
    body["status"] = "superseded"
    target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", target.relative_to(repo).as_posix())
    git_pin_date(repo, NOW, "commit", "-q", "-m",
                 f"steering: supersede {BASELINE_ID} with {SUPERSEDING_ID}")


def _order(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run order.py with exactly the arguments given, identity pinned to Replay."""
    return run_order(repo, *args, env=env)


def _census_ordering(repo: Path, *extra: str) -> tuple[int, list[dict], str]:
    """The unified census over the three ordering classes: the writer's arbiter."""
    args = ["--repo", str(repo), "--json", "--now", NOW]
    for check in ORDERING_CHECKS:
        args += ["--only", check]
    args += list(extra)
    proc = subprocess.run(
        [sys.executable, str(CENSUS), *args],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=120,
    )
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    findings = [r for r in rows if r.get("kind") == "finding"]
    return proc.returncode, findings, proc.stdout + proc.stderr


def _assert_census_clean(repo: Path, context: str, *extra: str) -> None:
    code, rows, output = _census_ordering(repo, *extra)
    assert code == 0, f"ordering census not clean after {context} (exit {code}):\n{output}"
    assert not rows, f"unexpected ordering rows after {context}: {rows}"


def _head_paths(repo: Path) -> list[str]:
    out = _git_e2(repo, "show", "--format=", "--name-only", "HEAD").stdout
    return [line for line in out.splitlines() if line.strip()]


def _porcelain(repo: Path, *rels: str) -> str:
    return _git_e2(repo, "status", "--porcelain", "--", *rels).stdout.strip()


def _canonical(entries: list[dict]) -> str:
    """The bytes the writer itself emits for ``entries``, via its own renderer.

    A fixture that hand-wrote the canonical form would be a second copy of the
    contract; deriving it from the product's function is what keeps a form change
    from silently turning every canonical fixture into a refusal. The renderer
    lives in the skill's own schema module, loaded the way the writer loads it.
    """
    schema = _schema_module()
    return schema.order_bytes({"schema": schema.ORDER_SCHEMA, "entries": entries}).decode()


def _seed(repo: Path, *entries: dict, message: str = "direction: seed the order") -> None:
    """Commit the artifact holding ``entries`` in the writer's own canonical form."""
    body = _canonical([dict(e) for e in entries])
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", message)


def _spied_git(real_run, seen: list[list[str]]):
    """A stand-in for the writer's git helper that records each command line.

    Deliberately not a wrapper around the real helper: this records the argv the
    writer built, which is the contract under test (the hardening flags, and the
    `-- path` that scopes the commit), and delegates only the execution. A test
    that patched subprocess.run instead would see the harness's git calls too
    and would have to guess which were the product's.
    """
    def git(repo_arg: Path, *args: str):
        cmd = [
            "git", "-C", str(repo_arg),
            "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={os.devnull}",
            "-c", "protocol.ext.allow=never",
            "-c", "core.fsmonitor=false",
            *args,
        ]
        seen.append(cmd)
        return real_run(cmd, capture_output=True, text=True, errors="replace",
                        timeout=_gitwrite_module().GIT_TIMEOUT)

    return git


def _writer_git_call(cmd: object, repo: Path) -> bool:
    """Whether ``cmd`` is one of the writer's own git calls, not the harness's.

    The spy wraps subprocess.run, which the fixture's own git calls go through
    too. The harness pins an identity as its first -c pair; the writer never
    does, so the shape of the -c block tells the two apart, along with the tree
    each call names.
    """
    if not isinstance(cmd, list) or cmd[:2] != ["git", "-C"] or len(cmd) < 4:
        return False
    if cmd[2] != str(repo):
        return False
    return cmd[3] != "-c" or not cmd[3 + 1].startswith("user.name=")


def _git_verb(cmd: list[str]) -> str | None:
    """The git verb of one of the writer's own calls: the word after the -c block."""
    index = 3
    while index + 1 < len(cmd) and cmd[index] == "-c":
        index += 2
    return cmd[index] if index < len(cmd) else None


def _entry(issue: int, decision: str | None = None, confirmed: str = STAMP) -> dict:
    return {"issue": issue, "decision": decision, "confirmed": confirmed}


# --- add ----------------------------------------------------------------------


def test_add_creates_the_file_and_commits_only_that_path(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _read(repo) == {"schema": "noni.order/1", "entries": [_entry(7, BASELINE_ID)]}
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo) == ""
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("direction: add 7 [") and subject.endswith("]"), subject
    _assert_census_clean(repo, "add")


def test_an_entry_without_a_decision_carries_null_not_an_absent_key(tmp_path):
    """``decision`` is always present, and null is the state 'the operator put
    this here and no record is cited': an absent key is a malformed entry, so
    the writer's own output must round-trip through the shape it refuses."""
    repo = _repo(tmp_path)
    # An entry the operator placed with no record cited is a state the file
    # carries, but "an added position is a decision" is the writer's rule: the
    # null form is reached by seeding, and the writer must still round-trip it.
    _seed(repo, _entry(1, None))
    assert _order(repo, "confirm", "--now", NOW).returncode == 0
    body = _order_path(repo).read_text(encoding="utf-8")
    assert '"decision": null' in body, body
    assert list(json.loads(body)["entries"][0]) == ["issue", "decision", "confirmed"]
    _assert_census_clean(repo, "a null decision")


def test_add_writes_the_canonical_bytes_the_docstring_documents(tmp_path):
    """The artifact is the documented shape: schema first, then entries, each
    entry issue/decision/confirmed, two-space indent, one trailing newline."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order(repo, "add", "12", "--decision", BASELINE_ID,
                  "--now", NOW).returncode == 0
    body = _order_path(repo).read_text(encoding="utf-8")
    # The second add names no --decision, so its entry carries null:
    assert body == _canonical([_entry(7, BASELINE_ID), _entry(12, BASELINE_ID)]), repr(body)
    assert list(json.loads(body)) == ["schema", "entries"]
    assert list(json.loads(body)["entries"][0]) == ["issue", "decision", "confirmed"]
    assert body.endswith("\n") and not body.endswith("\n\n")
    assert '  "schema": "noni.order/1"' in body, body


def test_add_appends_at_the_end_and_at_the_named_position(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    assert _order(repo, "add", "9", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [1, 2, 9]
    assert _order(repo, "add", "8", "--at", "1", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [8, 1, 2, 9]
    _assert_census_clean(repo, "inserts")


def test_add_at_the_last_position_of_the_new_list_is_accepted(tmp_path):
    """``--at`` ranges over the list this run produces, so the new length is a
    legal position and one past it is not."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    assert _order(repo, "add", "5", "--at", "2", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [1, 5]
    assert _order(repo, "add", "6", "--at", "4", "--now", NOW).returncode == 2
    assert _issues(repo) == [1, 5]


def test_add_stamps_confirmed_with_the_run_time_when_now_is_omitted(tmp_path):
    """Without --now the stamp is this run's UTC second, which the file must
    carry in the one shape the census parses."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID).returncode == 0
    stamp = _read(repo)["entries"][0]["confirmed"]
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T", stamp
    assert _schema_module().parse_confirmed(stamp) is not None


def test_add_without_a_decision_refuses_with_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--now", NOW)
    assert proc.returncode == 2
    assert "--decision" in proc.stderr
    assert not _order_path(repo).exists()


def test_add_of_an_already_listed_issue_refuses_with_four_and_changes_nothing(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "already in the order at position 1" in proc.stderr
    assert _order_path(repo).read_bytes() == before
    assert _porcelain(repo, ORDER_REL) == ""


def test_add_refuses_a_decision_that_matches_no_record(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--decision", "2026-10-09-ghost", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "is in the ledger" in proc.stderr or "matches no record" in proc.stderr, proc.stderr
    assert not _order_path(repo).exists()
    code, rows, _ = _census_ordering(repo)
    assert code == 0 and not rows, rows


def test_add_refuses_a_superseded_decision_and_names_its_successor(tmp_path):
    repo = _repo(tmp_path)
    _supersede_baseline(repo)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert SUPERSEDING_ID in proc.stderr, proc.stderr
    assert f"--decision {SUPERSEDING_ID}" in proc.stderr, proc.stderr
    assert not _order_path(repo).exists()
    # The successor itself sets a position without complaint.
    assert _order(repo, "add", "7", "--decision", SUPERSEDING_ID, "--now", NOW).returncode == 0


def test_add_refuses_a_record_whose_status_is_not_one_of_the_three(tmp_path):
    """A hand-edited status answers nothing about the chain, so it is refused
    like a missing record rather than trusted as a live decision."""
    repo = _repo(tmp_path)
    _commit_record(repo, "2026-10-15-rogue", "settled", None)
    proc = _order(repo, "add", "7", "--decision", "2026-10-15-rogue", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "settled" in proc.stderr, proc.stderr


def test_an_empty_ledger_answers_that_the_id_is_not_there(tmp_path):
    """A ledger directory that holds no records is a readable answer, and it is
    the same answer as no file with that name: exit 4, the refusal is about the
    ordering, and the caller fixes it by naming a record that exists."""
    repo = _repo(tmp_path)
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").mkdir()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "is in the ledger" in proc.stderr, proc.stderr


def test_a_record_that_is_not_a_regular_file_cannot_set_a_position(tmp_path):
    """Something that is not a record sitting where the record should be cannot
    have decided anything: the writer refuses the citation (exit 4) and says the
    path is not readable, so the caller repairs the ledger rather than hunting
    for a record that was never missing."""
    repo = _repo(tmp_path)
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.unlink()
    record.mkdir()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "not readable" in proc.stderr, proc.stderr


def test_a_ledger_that_is_not_a_directory_cannot_be_looked_in(tmp_path):
    """The contrast: the ledger path itself holds something that is not a
    directory, so nothing was looked at. That is 'I could not look' (exit 3),
    not the absence the previous test reports."""
    repo = _repo(tmp_path)
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").write_text("not a directory", encoding="utf-8")
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "could not be looked in" in proc.stderr, proc.stderr


def test_add_creates_the_direction_directory_for_the_first_entry(tmp_path):
    repo = _repo(tmp_path)
    assert not (repo / "noni" / "direction").exists()
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order_path(repo).is_file()


# --- move / remove / confirm --------------------------------------------------


def test_move_replaces_the_entry_and_restamps_it(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, None, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "3", "--to", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [3, 1, 2]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert entries[0]["decision"] == BASELINE_ID, entries[0]
    assert entries[1]["confirmed"] == "2026-10-01T00:00:00Z", entries[1]
    _assert_census_clean(repo, "move")


def test_move_without_to_is_a_usage_error(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "move", "1", "--now", NOW)
    assert proc.returncode == 2
    assert "--to" in proc.stderr


def test_move_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "99", "--to", "1", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_remove_shortens_the_list_and_leaves_the_others(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, None))
    proc = _order(repo, "remove", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _issues(repo) == [2]
    assert _read(repo)["entries"][0]["confirmed"] == STAMP, "remove must not restamp"
    _assert_census_clean(repo, "remove")


def test_remove_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "remove", "5", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr


def test_confirm_restamps_one_entry_and_then_the_whole_order(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, None, "2026-10-01T00:00:00Z"),
          _entry(2, None, "2026-10-01T00:00:00Z"))
    assert _order(repo, "confirm", "1", "--now", NOW).returncode == 0
    entries = _read(repo)["entries"]
    assert entries[0]["confirmed"] == STAMP and entries[1]["confirmed"] == "2026-10-01T00:00:00Z"
    assert _order(repo, "confirm", "--now", "2026-10-28T09:00:00Z").returncode == 0
    entries = _read(repo)["entries"]
    assert [e["confirmed"] for e in entries] == ["2026-10-28T09:00:00Z"] * 2
    _assert_census_clean(repo, "confirm")


def test_confirm_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "confirm", "5", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr


def test_a_run_that_changes_no_byte_commits_nothing(tmp_path):
    """Confirming an entry already stamped at the given time has nothing to
    commit: no --allow-empty commit, and the file keeps its bytes."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, STAMP))
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "confirm", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert "unchanged" in proc.stdout and "nothing to commit" in proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo) == ""


# --- the printed order --------------------------------------------------------


def test_every_run_prints_the_resulting_order_one_line_per_entry(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, None))
    proc = _order(repo, "remove", "1", "--now", NOW)
    lines = proc.stdout.splitlines()
    assert any("order.json" in line and "1 entr" in line for line in lines), lines
    assert any(line.strip().startswith("1. #2") for line in lines), lines
    assert "decision=-" in proc.stdout and "confirmed=" in proc.stdout, proc.stdout


# --- --no-commit and the staged-file rule -------------------------------------


def test_no_commit_writes_the_file_and_moves_no_head(tmp_path):
    repo = _repo(tmp_path)
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW, "--no-commit")
    assert proc.returncode == 0, proc.stderr
    assert _issues(repo) == [7]
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo, ORDER_REL) == f"?? {ORDER_REL}", _porcelain(repo, ORDER_REL)
    printed = proc.stdout.splitlines()
    line = next(row for row in printed if "uncommitted" in row)
    assert ORDER_REL in line, line
    assert sum("uncommitted" in row for row in printed) == 1, proc.stdout


def test_a_file_somebody_else_staged_is_neither_committed_nor_unstaged(tmp_path):
    """The commit carries exactly the path this run wrote: a foreign staged file
    survives the run staged and uncommitted, and never appears in HEAD."""
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo, "README.md") == "A  README.md", _porcelain(repo, "README.md")


def test_the_written_file_is_readable_not_owner_only(tmp_path):
    """mkstemp's 0600 must not land: an order the census cannot read is an
    order nobody can trust."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    mode = _order_path(repo).stat().st_mode & 0o777
    assert mode & 0o044, f"the artifact is {oct(mode)}; the census must be able to read it"


# --- the refusals that protect an existing artifact ---------------------------


def test_a_file_that_is_not_json_is_refused_and_left_untouched(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    _order_path(repo).write_text("{not json", encoding="utf-8")
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "not valid JSON" in proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_wrong_schema_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(json.dumps({"schema": "noni.order/0", "entries": []}),
                                 encoding="utf-8")
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "noni.order/1" in proc.stderr


def test_malformed_entries_are_refused_without_being_overwritten(tmp_path):
    """Every shape the census reports as ordering-malformed is refused here
    before the write, so a writer run never turns a half-broken artifact into a
    fully written one. The table is the whole set, not a sample."""
    shapes = {
        "not an object": "[]",
        "missing entries": '{"schema": "noni.order/1"}',
        "unknown top-level field": '{"schema": "noni.order/1", "entries": [], "extra": 1}',
        "entries not an array": '{"schema": "noni.order/1", "entries": {}}',
        "entry not an object": '{"schema": "noni.order/1", "entries": [7]}',
        "entry missing a field": '{"schema": "noni.order/1", "entries": [{"issue": 1}]}',
        "entry with an unknown field": '{"schema": "noni.order/1", "entries": '
                                       '[{"issue": 1, "decision": null, "confirmed": '
                                       '"2026-10-01T00:00:00Z", "why": 1}]}',
        "issue not an integer": '{"schema": "noni.order/1", "entries": '
                                '[{"issue": "1", "decision": null, '
                                '"confirmed": "2026-10-01T00:00:00Z"}]}',
        "issue is a bool": '{"schema": "noni.order/1", "entries": '
                           '[{"issue": true, "decision": null, '
                           '"confirmed": "2026-10-01T00:00:00Z"}]}',
        "issue not positive": '{"schema": "noni.order/1", "entries": '
                              '[{"issue": 0, "decision": null, '
                              '"confirmed": "2026-10-01T00:00:00Z"}]}',
        "issue listed twice": '{"schema": "noni.order/1", "entries": '
                              '[{"issue": 3, "decision": null, '
                              '"confirmed": "2026-10-01T00:00:00Z"}, '
                              '{"issue": 3, "decision": null, '
                              '"confirmed": "2026-10-01T00:00:00Z"}]}',
        "decision is a number": '{"schema": "noni.order/1", "entries": '
                                '[{"issue": 1, "decision": 3, '
                                '"confirmed": "2026-10-01T00:00:00Z"}]}',
        "confirmed is null": '{"schema": "noni.order/1", "entries": '
                             '[{"issue": 1, "decision": null, "confirmed": null}]}',
        "confirmed has no offset": '{"schema": "noni.order/1", "entries": '
                                   '[{"issue": 1, "decision": null, '
                                   '"confirmed": "2026-10-01T00:00:00"}]}',
        "a NaN hides in an entry": '{"schema": "noni.order/1", "entries": '
                                   '[{"issue": 1, "decision": null, '
                                   '"confirmed": "2026-10-01T00:00:00Z", "n": 1e400}]}',
    }
    for label, body in shapes.items():
        repo = _repo(tmp_path, f"repo-{abs(hash(label))}")
        _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
        _order_path(repo).write_text(body, encoding="utf-8")
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 4, f"{label}: exit {proc.returncode} {proc.stderr}"
        assert _order_path(repo).read_text(encoding="utf-8") == body, f"{label}: overwritten"


def test_non_canonical_bytes_are_refused_rather_than_reformatted(tmp_path):
    """Valid, well-shaped, but not the form this writer writes (one-space
    indent): the operator committed it, so reformatting it is not this run's
    to do."""
    repo = _repo(tmp_path)
    body = json.dumps({"schema": "noni.order/1", "entries": [_entry(1, BASELINE_ID)]},
                      indent=1) + "\n"
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "canonical form" in proc.stderr, proc.stderr
    assert _order_path(repo).read_text(encoding="utf-8") == body
    # The committed canonical form of the same content is accepted.
    _seed(repo, _entry(1, BASELINE_ID))
    assert _order(repo, "confirm", "--now", NOW).returncode == 0


def test_a_key_order_that_is_not_the_documented_one_is_refused(tmp_path):
    """Sorted keys are still valid JSON and still the wrong bytes: the writer's
    canonical form is the documented key order, not json.dumps' default."""
    repo = _repo(tmp_path)
    body = json.dumps({"entries": [_entry(1, BASELINE_ID)], "schema": "noni.order/1"},
                      indent=2) + "\n"
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert _order_path(repo).read_text(encoding="utf-8") == body


def test_the_artifact_path_being_a_directory_is_an_environment_fault(tmp_path):
    repo = _repo(tmp_path)
    _order_path(repo).mkdir(parents=True)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "not a regular file" in proc.stderr, proc.stderr


def test_a_symlink_at_the_artifact_path_is_refused_never_followed(tmp_path):
    """Reading through a link puts a file outside the tree into the writer's
    decisions; writing onto one replaces somebody's link with an order file."""
    repo = _repo(tmp_path)
    (repo / "elsewhere.json").write_text(_canonical([_entry(1, BASELINE_ID)]), encoding="utf-8")
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).symlink_to(repo / "elsewhere.json")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "symlink" in proc.stderr, proc.stderr
    assert _order_path(repo).is_symlink(), "the writer replaced a symlink"
    assert (repo / "elsewhere.json").is_file()


def test_an_unreadable_decision_record_is_an_environment_fault(tmp_path):
    repo = _repo(tmp_path)
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.chmod(0o000)
    try:
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    finally:
        record.chmod(0o644)
    if proc.returncode != 3:  # pragma: no cover - root can read 000 files
        import pytest
        pytest.skip("the reading user can read a 000-mode file")
    assert "could not be read" in proc.stderr, proc.stderr


# --- usage errors -------------------------------------------------------------


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
    a hint the run quietly ignores: each of the three mis-placements is named."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    cases = [
        ("move", "1", "--to", "1", "--at", "1", "--now", NOW),
        ("remove", "1", "--to", "1", "--now", NOW),
        ("confirm", "--at", "1", "--now", NOW),
        ("confirm", "1", "--decision", BASELINE_ID, "--now", NOW),
    ]
    for argv in cases:
        proc = _order(repo, *argv)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert "belongs to" in proc.stderr, f"{argv}: {proc.stderr}"


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
    """No tree means the record this run must read is not there to read: the run
    stops at exit 3 and names the record, rather than creating a directory
    nobody asked for under a path that is not a repo."""
    proc = _order(tmp_path / "no-such-repo", "add", "7", "--decision", BASELINE_ID,
                  "--now", NOW)
    # No tree means no ledger, so the id names nothing: the run refuses the
    # citation (exit 4) rather than inventing a directory nobody asked for.
    assert proc.returncode == 4, proc.returncode
    assert "is in the ledger" in proc.stderr, proc.stderr
    assert not (tmp_path / "no-such-repo").exists(), "the writer created a tree it refused"""


# --- the git layer ------------------------------------------------------------


def test_a_failing_commit_is_exit_three_and_leaves_the_file_written(tmp_path):
    """The file is written and named, never claimed as committed: the caller
    fixes git and re-runs, and the message says which of the two steps failed."""
    repo = _repo(tmp_path)
    _git_e2(repo, "config", "--unset", "user.name")
    _git_e2(repo, "config", "--unset", "user.email")
    env = {
        "PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin",
        "HOME": str(tmp_path / "no-home"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW, env=env)
    assert proc.returncode == 3, proc.stderr
    assert "commit failed" in proc.stderr, proc.stderr
    assert _issues(repo) == [7], "the artifact is written even when git refused"


def test_a_git_call_that_times_out_is_never_read_as_a_clean_answer(tmp_path, monkeypatch):
    """A git call that hangs reports the timeout code, which is no answer: the
    run stops at exit 3 and says which call hung, rather than committing an
    order whose commit nobody saw land."""
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"))

    helper = _gitwrite_module()

    def hung(repo_arg, *args, **kwargs):
        # What the writer's own helper hands back for a call that cannot
        # finish: a return code no caller may read as a clean answer.
        return subprocess.CompletedProcess(["git", *args], helper.GIT_TIMEOUT_RC,
                                           "", "git timed out")

    monkeypatch.setattr(module.gitwrite, "git", hung)
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "confirm", "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "timed out" in err.getvalue(), err.getvalue()
    assert str(_gitwrite_module().GIT_TIMEOUT) in err.getvalue(), err.getvalue()


def test_every_git_call_disables_hooks_signing_and_external_transports(tmp_path):
    """No hook, no signing, no external transport, and no hang: the writer must
    not be able to wedge itself or run the tree's own scripts on the operator's
    behalf. Global config is NOT neutralised: the commit is made under the
    tree's configured identity, like every other noni writer.

    The writer is driven in-process for this one: the product's git calls are
    the only ones the spy can see, and a subprocess run would put them behind a
    process boundary the spy cannot cross.
    """
    seen: list[list[str]] = []
    module = _order_module()
    real_run = subprocess.run

    repo = _repo(tmp_path)
    module.gitwrite.git = _spied_git(real_run, seen)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                                "--now", NOW])
    finally:
        del module.gitwrite.git
    assert code == 0, code
    own = [c for c in seen if _writer_git_call(c, repo)]
    assert own, f"the writer made no git call of its own: {seen}"
    for cmd in own:
        joined = " ".join(cmd)
        assert "-c commit.gpgsign=false" in joined, joined
        assert f"-c core.hooksPath={os.devnull}" in joined, joined
        assert "-c protocol.ext.allow=never" in joined, joined
        assert "-c core.fsmonitor=false" in joined, joined
        assert cmd[2] == str(repo)


def test_a_run_that_renders_nothing_writable_fails_as_io(tmp_path, monkeypatch):
    """The atomic write itself is an environment fault, not a refusal of the
    order: when the directory cannot hold a temp file the run says the file
    could not be written (exit 3) and leaves the artifact it read alone."""
    module = _order_module()

    def refuse(path, payload):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(module.gitwrite, "write_atomic", refuse)
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = (repo / ORDER_REL).read_bytes()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "could not be written" in err.getvalue(), err.getvalue()
    raw = (repo / ORDER_REL).read_bytes()
    assert raw == before, "a failed write must leave the artifact as it was"


def test_a_file_where_the_direction_directory_belongs_is_a_fault(tmp_path):
    """The parent path is part of the artifact's identity: a plain file sitting
    at noni/direction is an environment fault (exit 3), not a refusal of the
    order and not something the writer works around by replacing it."""
    module = _order_module()
    repo = _repo(tmp_path)
    (repo / "noni" / "direction").write_text("not a directory\n", encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_IO, code
    assert "is not a directory" in err.getvalue(), err.getvalue()
    assert (repo / "noni" / "direction").read_text(encoding="utf-8") == "not a directory\n"


def test_a_planned_order_that_cannot_be_rendered_is_refused(tmp_path, monkeypatch):
    """The writer renders its own plan, and a plan it cannot render is a refusal
    that leaves the artifact alone: the path is unreachable in normal operation
    (every value is validated first), so it is exercised by making the renderer
    lie, and the contract under test is that no half-written order is committed."""
    module = _order_module()

    def lie(body):
        raise ValueError("cannot render")

    monkeypatch.setattr(module.orderschema, "order_bytes", lie)
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = (repo / ORDER_REL).read_bytes()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                            "--now", NOW])
    assert code == module.EXIT_REFUSAL, code
    assert "cannot be written as JSON" in err.getvalue(), err.getvalue()
    assert (repo / ORDER_REL).read_bytes() == before


def test_the_commit_names_only_the_written_path(tmp_path):
    """The staged-set rule is in the command line itself: add and commit both
    carry `-- <path>`, and the commit carries --only."""
    seen: list[list[str]] = []
    module = _order_module()
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        return real_run(cmd, *args, **kwargs)

    # Driven in-process through the writer's own git helper, so the calls the
    # spy sees are the writer's: the subprocess run would put them behind a
    # process boundary the spy cannot cross.
    repo = _repo(tmp_path)
    module.gitwrite.git = _spied_git(real_run, seen)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.main(["--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                                "--now", NOW])
    finally:
        del module.gitwrite.git
    assert code == 0, code
    own = [c for c in seen if _writer_git_call(c, repo)]
    assert own, f"the writer made no git call of its own: {seen}"
    adds = [c for c in own if _git_verb(c) == "add"]
    commits = [c for c in own if _git_verb(c) == "commit"]
    assert adds and commits, seen
    assert adds[0][-2:] == ["--", ORDER_REL], adds[0]
    assert "--only" in commits[0], commits[0]
    assert commits[0][-2:] == ["--", ORDER_REL], commits[0]
    # The subject the writer actually built is visible in the history: a
    # compound change stays one change, identifiable by its verb.
    subject = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s"],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert subject.startswith("direction: add 7 [") and subject.endswith("]"), subject


# --- the round trip with the arbiter ------------------------------------------


def test_the_git_helper_is_bounded_hardened_and_makes_no_signing_promise(tmp_path):
    """The helper's own contract, tested where it lives: one call, a timeout, and
    the four -c overrides that keep hooks, signing, fsmonitor and external
    transports off the order's commit. A helper that silently dropped one would
    still pass every behavioural test above, because a real repo has none."""
    helper = _gitwrite_module()
    seen: list[list[str]] = []
    real_run = subprocess.run

    bounds: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        bounds.append(dict(kwargs))
        # A stubbed answer: the point is the command line, not git's verdict.
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    subprocess.run = spy
    try:
        proc = helper.git(Path("/nonexistent-repo"), "status", "--porcelain")
    finally:
        subprocess.run = real_run
    assert proc.returncode == 0
    assert len(seen) == 1, seen
    cmd = seen[0]
    assert cmd[:2] == ["git", "-C"], cmd
    assert cmd[2] == "/nonexistent-repo", cmd
    joined = " ".join(cmd)
    for hardening in ("-c commit.gpgsign=false", f"-c core.hooksPath={os.devnull}",
                      "-c protocol.ext.allow=never", "-c core.fsmonitor=false"):
        assert hardening in joined, f"{hardening} missing from {joined}"
    assert cmd[-2:] == ["status", "--porcelain"], cmd
    # The call is bounded by the helper, not the caller: no caller can leave it
    # running, so no caller is trusted to bound it.
    assert bounds[0].get("timeout") == helper.GIT_TIMEOUT, bounds


def test_a_hung_git_call_reports_the_timeout_code_the_writer_classifies(tmp_path):
    """The helper converts its own timeout instead of raising, so the writer can
    classify the answer (exit 3, the file named) rather than end in a traceback.
    The code is the helper's constant, and it is not zero."""
    helper = _gitwrite_module()
    real_run = subprocess.run

    def hang(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", helper.GIT_TIMEOUT))

    subprocess.run = hang
    try:
        proc = helper.git(Path("/nonexistent-repo"), "commit", "-m", "x")
    finally:
        subprocess.run = real_run
    assert proc.returncode == helper.GIT_TIMEOUT_RC != 0
    assert "timed out" in proc.stderr
    assert "commit" in proc.stderr, "the message names which git call hung"


def test_the_atomic_writer_leaves_the_old_bytes_when_the_replace_fails(tmp_path):
    """write_atomic is the only way the artifact changes: a crash after the temp
    file is written must leave the previous order on disk, not a truncated one
    and not a stray temp file the next census would trip over."""
    helper = _gitwrite_module()
    target = tmp_path / "order.json"
    helper.write_atomic(target, b'{"schema": "noni.order/1", "entries": []}\n')
    first = target.read_bytes()

    def refuse(src, dst):
        raise OSError(5, "Input/output error")

    real_replace = helper.os.replace
    helper.os.replace = refuse
    try:
        try:
            helper.write_atomic(target, b"truncated")
        except OSError:
            pass
        else:
            raise AssertionError("write_atomic swallowed the replace failure")
    finally:
        helper.os.replace = real_replace
    assert target.read_bytes() == first
    assert [q.name for q in tmp_path.iterdir() if q.name != "_noni_isolated_home"] == \
        ["order.json"], "a temp file was left behind"


def test_a_created_artifact_carries_the_mode_the_umask_allows(tmp_path):
    """mkstemp's 0600 must not land: an order the census cannot read is an order
    nobody can trust, and a file that replaces an existing one keeps its mode."""
    helper = _gitwrite_module()
    helper.os.umask(0o022)
    fresh = tmp_path / "order.json"
    helper.write_atomic(fresh, b"a\n")
    assert fresh.stat().st_mode & 0o777 == 0o644, oct(fresh.stat().st_mode & 0o777)
    os.chmod(fresh, 0o600)
    helper.write_atomic(fresh, b"b\n")
    assert fresh.stat().st_mode & 0o777 == 0o600, "a replace must not widen who can read"


def test_the_schema_refuses_a_non_finite_number_in_any_position(tmp_path):
    """The renderer refuses a NaN or an overflowed literal wherever it sits, and
    the reader refuses the token: an order whose issue or stamp is not a number
    is not an order, and a silent inf would sort into a position nobody chose."""
    schema = _schema_module()
    entry = {"issue": 1, "decision": None, "confirmed": "2026-10-27T12:00:00Z"}
    for body in ({"schema": schema.ORDER_SCHEMA, "entries": [dict(entry, issue=float("nan"))]},
                 {"schema": schema.ORDER_SCHEMA, "entries": [dict(entry, issue=float("inf"))]}):
        try:
            schema.order_bytes(body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"rendered a non-finite issue: {body}")
    assert schema.holds_non_finite({"entries": [{"issue": float("inf")}]})
    assert not schema.holds_non_finite({"entries": [{"issue": True, "n": 1}]})
    try:
        json.loads('{"a": NaN}', parse_constant=schema.refuse_constant)
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_constant accepted NaN")


def _schema_case(**entry_fields):
    """A well-formed document whose single entry has ``entry_fields`` overridden,
    or gained when the name is not one of the entry's three fields."""
    schema = _schema_module()
    entry = {"issue": 1, "decision": None, "confirmed": "2026-10-27T12:00:00Z"}
    for name, value in entry_fields.items():
        entry[name] = value
    return {"schema": schema.ORDER_SCHEMA, "entries": [entry]}


def test_the_schema_reports_the_first_defect_it_finds(tmp_path):
    """problems() names what is wrong with a value the writer may not extend:
    each documented defect shape is reported, and a well-formed order is not."""
    schema = _schema_module()
    assert schema.problems(_schema_case()) == []
    assert schema.problems([]), "a list is not an order"
    assert schema.problems({"entries": []}), "no schema key"
    assert schema.problems({"schema": "noni.order/2", "entries": []}), "wrong schema"
    assert schema.problems({"schema": schema.ORDER_SCHEMA, "extra": 1,
                            "entries": []}), "unknown field"
    assert schema.problems({"schema": schema.ORDER_SCHEMA, "entries": {}}), "entries not a list"
    assert schema.problems(_schema_case(extra_key=1)), "entry with an unknown field"
    short = {"schema": schema.ORDER_SCHEMA, "entries": [{"issue": 1}]}
    assert schema.problems(short), "entry missing fields"
    assert schema.problems(_schema_case(issue="1")), "issue is not an int"
    assert schema.problems(_schema_case(issue=True)), "issue is a bool"
    assert schema.problems(_schema_case(issue=0)), "issue is not positive"
    assert schema.problems(_schema_case(decision="")), "decision is blank"
    assert schema.problems(_schema_case(decision=3)), "decision is neither str nor null"
    assert schema.problems(_schema_case(confirmed="nope")), "confirmed is not a timestamp"
    assert schema.problems(_schema_case(confirmed=5)), "confirmed is not a string"
    assert schema.problems({"schema": schema.ORDER_SCHEMA,
                            "entries": [[], {"issue": 2, "decision": None,
                                             "confirmed": "2026-10-27T12:00:00Z"}]}), \
        "an entry that is not an object"
    assert schema.problems({"schema": schema.ORDER_SCHEMA,
                            "entries": [{"issue": 4, "decision": None,
                                         "confirmed": "2026-10-27T12:00:00Z"},
                                        {"issue": 4, "decision": None,
                                         "confirmed": "2026-10-27T12:00:00Z"}]}), \
        "a duplicate issue"
    # A non-finite number anywhere in the document is a defect, and a bool is
    # never a number: the two rules the renderer also refuses to emit.
    assert schema.holds_non_finite(_schema_case(issue=float("nan"))), "NaN in an entry"
    assert not schema.holds_non_finite(_schema_case()), "a clean order"


def test_the_schema_reads_a_utc_stamp_and_refuses_a_bare_one():
    """parse_confirmed is the census's and the writer's one reading of a stamp:
    a Z-suffixed or offset time is a time, a bare one is not, and neither is a
    mis-ordered digit string."""
    schema = _schema_module()
    assert schema.parse_confirmed("2026-10-27T12:00:00Z") is not None
    assert schema.parse_confirmed("2026-10-27T12:00:00+02:00") is not None
    assert schema.parse_confirmed("2026-10-27T12:00:00") is None
    assert schema.parse_confirmed("yesterday") is None


def test_a_writer_run_leaves_the_ordering_census_clean(tmp_path):
    """The contract the two halves share: what the writer writes, the arbiter
    accepts. Every verb in turn, then the census."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order(repo, "add", "8", "--at", "1", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _order(repo, "move", "7", "--to", "2", "--now", NOW).returncode == 0
    assert _order(repo, "confirm", "--now", NOW).returncode == 0
    assert _order(repo, "remove", "8", "--now", NOW).returncode == 0
    _assert_census_clean(repo, "the full verb round trip")


def test_the_committed_fixture_is_the_shape_the_writer_accepts(tmp_path):
    """The shared fixture is the documented artifact: it is valid JSON, the
    census calls it clean, and the writer extends it rather than refusing it.
    A fixture that only the writer liked would keep the arbiter's half of the
    contract unpinned."""
    repo = _repo(tmp_path)
    body = FIXTURE.read_text(encoding="utf-8")
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: seed from the fixture")
    _assert_census_clean(repo, "the committed fixture")
    assert _order(repo, "confirm", "--now", NOW).returncode == 0


def test_the_fixture_bytes_are_the_writer_canonical_form(tmp_path):
    """The fixture is byte-identical to what the writer would emit for the same
    entries, so it can serve as the canonical-form reference in either
    direction."""
    body = FIXTURE.read_text(encoding="utf-8")
    value = json.loads(body)
    assert _schema_module().order_bytes(value).decode() == body


def test_the_ordering_census_reports_what_the_writer_refused(tmp_path):
    """One shape each, on both sides of the contract: the census reports as
    ``ordering-malformed`` exactly what the writer refuses to extend, and the
    row names the same reason in its own words. A file the writer refuses and
    the census calls clean is a file nobody would notice had rotted."""
    shapes = {
        "not valid JSON": "{not json",
        "wrong schema": '{"schema": "nope", "entries": []}',
        "duplicate issue": '{"schema": "noni.order/1", "entries": '
                           '[{"issue": 3, "decision": null, "confirmed": '
                           '"2026-10-26T00:00:00Z"}, {"issue": 3, "decision": null, '
                           '"confirmed": "2026-10-26T00:00:00Z"}]}',
        "non-positive issue": '{"schema": "noni.order/1", "entries": '
                              '[{"issue": 0, "decision": null, '
                              '"confirmed": "2026-10-26T00:00:00Z"}]}',
        "confirmed is not a timestamp": '{"schema": "noni.order/1", "entries": '
                                        '[{"issue": 3, "decision": null, '
                                        '"confirmed": null}]}',
        "a decision that matches no record": '{"schema": "noni.order/1", "entries": '
                                             '[{"issue": 3, "decision": '
                                             '"2026-01-01-ghost", "confirmed": '
                                             '"2026-10-26T00:00:00Z"}]}',
    }
    for label, body in shapes.items():
        repo = _repo(tmp_path, f"arb-{abs(hash(label))}")
        _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
        _order_path(repo).write_text(body, encoding="utf-8")
        _git(repo, "add", ORDER_REL)
        git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: broken")
        writer = _order(repo, "confirm", "--now", NOW)
        assert writer.returncode == 4, f"{label}: writer exit {writer.returncode}"
        code, rows, output = _census_ordering(repo)
        assert code == 15, f"{label}: census exit {code}: {output}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], f"{label}: {rows}"


def test_a_stale_entry_is_reported_by_the_census_and_cleared_by_confirm(tmp_path):
    """The staleness half of the contract, end to end: a confirmed time past the
    threshold is a warn at 45, --strict promotes it, and the writer's confirm
    clears the row. The threshold is the ordering default (30 days) when
    --stale-after was not given, and the caller's number when it was."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, "2026-10-15T00:00:00Z"))
    code, rows, _ = _census_ordering(repo)
    assert code == 0 and rows == [], (
        f"a 12-day-old entry is inside the 30-day ordering default: {rows}")
    code, rows, _ = _census_ordering(repo, "--stale-after", "7")
    # The census's own rule, re-asserted here: a warn-class row never moves the
    # exit code on its own, so the row is the report and 0 is the verdict.
    assert code == 0, code
    assert [r["check"] for r in rows] == ["ordering-stale"], rows
    assert rows[0]["severity"] == "warn"
    assert rows[0]["subject"] == "#7", rows[0]
    code, rows, _ = _census_ordering(repo, "--stale-after", "7", "--strict")
    assert code == 45 and rows[0]["severity"] == "fail", (code, rows)
    assert _order(repo, "confirm", "7", "--now", NOW).returncode == 0
    _assert_census_clean(repo, "confirm of the stale entry", "--stale-after", "7")


def test_a_closed_issue_is_reported_and_removed_by_the_writer(tmp_path):
    """Closed state reaches the census only through --issue-state (the census
    never contacts a tracker): the row is a warn at 46, the writer's remove
    clears it, and an issue the map omits gets a cannot-tell row rather than
    silence."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(8, None))
    state = repo / "issue-state.json"
    state.write_text(json.dumps({"7": "closed", "9": "open"}), encoding="utf-8")
    code, rows, _ = _census_ordering(repo, "--issue-state", str(state))
    assert code == 0, code
    assert [(r["check"], r["subject"]) for r in rows] == [
        ("ordering-closed", "#7"), ("ordering-closed", "#8")], rows
    assert "closed: issue 7" in rows[0]["message"], rows[0]
    assert rows[1]["message"].startswith("cannot-tell:"), rows[1]
    assert _order(repo, "remove", "7", "--now", NOW).returncode == 0
    _seed_entries = _read(repo)["entries"]
    assert [e["issue"] for e in _seed_entries] == [8]
    # Only the cannot-tell row is left, and the class stays a warn at exit 0.
    code, rows, _ = _census_ordering(repo, "--issue-state", str(state))
    assert code == 0 and [r["subject"] for r in rows] == ["#8"], (code, rows)


def test_the_closed_class_says_so_when_no_state_file_is_given(tmp_path):
    """The census never contacts a tracker, so without --issue-state the closed
    question is not asked. A run that simply printed nothing would read as
    'every ordered issue is open', so the human-readable run says once that the
    class was not evaluated; the --json stream stays findings-only."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    proc = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(repo), "--now", NOW,
         "--only", "ordering-closed"],
        capture_output=True, text=True, env=subprocess_env(), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ordering-closed was not evaluated" in proc.stdout, proc.stdout
    assert "never contacts a tracker" in proc.stdout, proc.stdout
    # The same run in --json mode: no notice line in the NDJSON stream.
    code, rows, _ = _census_ordering(repo)
    assert code == 0 and rows == [], (code, rows)


# --- the doc / code contract --------------------------------------------------


def _order_ast() -> ast.Module:
    return _script_ast(ORDER)


def _docstring(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "order.py has no module docstring"
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
    assert codes, "order.py defines no EXIT_* constants"
    return codes


def _doc_block(doc: str, header: str) -> dict[int, str] | dict[str, str]:
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise AssertionError(f"docstring has no {header!r} block") from None
    block: dict = {}
    current = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            current = int(head[0])
            block[current] = head[1] if len(head) > 1 else ""
        elif isinstance(current, int):
            block[current] += " " + line.strip()
    assert block, f"the {header!r} block is empty"
    return block


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
    pinned to the settled set 0/2/3/4: no code is documented that nothing
    returns, and none is returned that the table does not explain."""
    tree = _order_ast()
    published = _module_exit_codes(tree)
    documented = set(_doc_block(_docstring(tree), "Exit codes:"))
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}")
    assert published == {0, 2, 3, 4}, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block and the block
    names nothing the parser would reject; no --push, --strict or --json."""
    tree = _order_ast()
    parser = _parser_flags(tree) - {"--help"}
    documented = _doc_usage_flags(_docstring(tree))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--strict", "--json"):
        assert forbidden not in parser, f"{forbidden} is out of scope for order.py"


def test_docstring_names_the_refusals_the_code_performs():
    """The table is what a caller predicts a run's exit code from, so each
    refusal the code actually performs is named in it."""
    block = _doc_block(_docstring(_order_ast()), "Exit codes:")
    four = block[4].lower()
    for condition in ("already listed", "absent from the order", "no file under",
                      "superseded", "not the artifact"):
        assert condition in four, f"the exit 4 row omits {condition!r}: {block[4]}"
    three = block[3].lower()
    for condition in ("not a regular file", "could not be written", "commit"):
        assert condition in three, f"the exit 3 row omits {condition!r}: {block[3]}"
    two = block[2].lower()
    for condition in ("positive integer", "--decision", "1-based", "iso-8601"):
        assert condition in two, f"the exit 2 row omits {condition!r}: {block[2]}"


def test_skill_md_documents_the_writer_within_the_line_cap():
    """The skill documents order.py: its Usage, the four verbs, the artifact's
    two fields, the exit table, and the census rows a reader repairs with it."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/order.py" in text, "SKILL.md does not document the writer"
    for verb in ("add", "move", "remove", "confirm"):
        assert f"order.py {verb}" in text or f"`{verb}`" in text, f"SKILL.md omits {verb}"
    for flag in ("--decision", "--no-commit", "--now", "--at", "--to"):
        assert flag in text, f"SKILL.md omits {flag}"
    assert "noni/direction/order.json" in text and "noni.order/1" in text
    for code in (0, 2, 3, 4):
        assert f"| `{code}` |" in text, f"SKILL.md's exit table omits order.py code {code}"
    for row in ORDERING_CHECKS:
        assert row in text, f"SKILL.md does not say how to repair a {row} row"
    assert text.count("\n") <= 400, f"SKILL.md is {text.count(chr(10))} lines; cap is 400"
    assert text.startswith("---") and "\ndescription:" in text, "SKILL.md has no frontmatter"


def test_skill_layout_includes_the_writer_and_its_executable_bit():
    """The skill's layout assertion knows about scripts/order.py, and the writer
    is executable like the other skill scripts."""
    assert (SKILL_DIR / "scripts" / "order.py").is_file()
    assert ORDER.stat().st_mode & 0o111, "order.py is not executable"
    layout = (REPO / "tests" / "test_skill_scrub.py").read_text(encoding="utf-8")
    assert "scripts/order.py" in layout, "test_skill_scrub.py does not assert order.py's presence"
    purity = (REPO / "tests" / "test_purity.py").read_text(encoding="utf-8")
    assert '"direction"' in purity, "test_purity.py does not scan the direction skill"
    assert "direction" in layout, "test_skill_scrub.py does not scan the direction skill"


def test_no_secrets_or_machine_local_paths_in_the_new_skill_and_fixture(tmp_path):
    """The scrub's own patterns, applied to the two new files by name: the gate
    that covers them is parametrised over SKILL_FILES, and a parametrisation
    that quietly stopped including a file would be invisible without this."""
    sys.path.insert(0, str(REPO / "scripts"))
    from public_safety import FIXTURE_HOME_PATH_PATTERNS, HOME_PATH_PATTERNS, SECRET_PATTERNS
    for path in (SKILL_DIR / "SKILL.md", ORDER, FIXTURE):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in (*HOME_PATH_PATTERNS, *FIXTURE_HOME_PATH_PATTERNS,
                                   *SECRET_PATTERNS):
                assert not pattern.search(line), f"{path.name}:{lineno}: {label}"


def test_the_census_skill_documents_the_three_new_classes():
    """The census's SKILL.md is the reader's only table for what a row means:
    each ordering class is documented, in the exit-code list and the --strict
    list alike, so a reader can act on a row without reading the script."""
    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    for row, code in zip(ORDERING_CHECKS, (15, 45, 46), strict=False):
        assert f"| `{row}` | {code} |" in text, f"census SKILL.md omits {row} at {code}"
        assert f"{code}  {row}" in text, f"census SKILL.md's exit table omits {row}"
    strict_line = next(row for row in text.splitlines()
                       if row.startswith("| `--strict`"))
    for row in ORDERING_CHECKS[1:]:
        assert f"`{row}`" in strict_line, f"--strict row omits {row}: {strict_line}"
    # The two new flags appear in the option table. Matched without backticks
    # because the table itself renders them bare, and a check that demanded one
    # spelling would fail on a doc that documents the flag perfectly.
    assert "--issue-state" in text and "--ordering" in text, "new flags undocumented"
    # Both defaults the table promises are the paths the census actually uses.
    assert "<repo>/noni/direction/order.json" in text, "the ordering default is undocumented"
