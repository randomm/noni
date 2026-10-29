"""decide.py run from a separate state root: no write lands in the cwd.

Extracted from the decide writer suite: the writer driven from a decoy cwd and a
decoy ledger, so a path leak is a refusal rather than a stray record."""

import json

from _harness import (
    _git_e2,
)
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_DATE,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _census_py,
    _commit_tree,
    _decide,
    _decide_case,
    _decide_from,
    _decide_snapshot,
    _porcelain,
    _read,
    _record_json,
    _record_path,
    _run,
)

# decide.py is the ledger's only writer, so a run that resolved its ledger from
# the cwd rather than --repo would silently steer a different project. The three
# trees: a separate state repository (a git repo holding only the ledger), a
# decoy ledger under the cwd with a record of its own, and an empty cwd a stray
# write would show up in. The decoy's record is committed, so the census's
# edited-after-commit and chain checks pass on it either way: a run that read it
# would not be stopped, only caught.

DECIDE_STATE_DIR = "decide-state-root"
DECIDE_CWD_DIR = "decide-cwd"
DECIDE_DECOY_DIR = "decide-decoy"
DECIDE_DECOY_ID = "2026-10-05-decoy-stands"
def test_decide_writes_the_state_root_and_nothing_beside_the_cwd(tmp_path):
    """One steering act lands in the state repository and leaves the decoy and
    the cwd exactly as they were."""
    root, decoy, cwd = _decide_case(tmp_path)
    before = _decide_snapshot(decoy)

    proc = _decide_from(
        cwd, root, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
        *QUESTION, *OPTIONS, *ANSWERED,
    )
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    written = _record_path(root, NEW_ID)
    assert written.is_file(), "the record did not land in the state root"
    assert _read(root, NEW_ID)["id"] == NEW_ID
    assert NEW_ID in _git_e2(root, "log", "--format=%s").stdout, \
        "the record was not committed in the state repository"
    assert _decide_snapshot(decoy) == before, (
        "the run touched the decoy ledger beside its cwd, so the ledger resolved "
        "from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"
    # The state root's own ledger still censuses clean: the run wrote one record
    # and moved nobody else's bytes.
    code, out = _census_py(root)
    assert code == 0, f"census not clean after the isolated run ({code}):\n{out}"


def test_decide_supersede_writes_only_the_state_roots_two_paths(tmp_path):
    """A supersede flips the state root's own target and leaves the decoy's live
    record live: the two ledgers never meet.

    The decoy record shares no id with the state root's, so a writer that read
    the wrong ledger would fail to find its target — and a writer that wrote to
    both would flip a decoy byte."""
    root, decoy, cwd = _decide_case(tmp_path)
    before = _decide_snapshot(decoy)
    superseding_id = f"{BASELINE_ID[:10]}-scheduler"

    proc = _decide_from(
        cwd, root, "--slug", "scheduler", "--date", BASELINE_ID[:10], *BASE,
        *QUESTION, *OPTIONS, *ANSWERED, "--supersedes", BASELINE_ID,
    )
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert _read(root, BASELINE_ID)["status"] == "superseded", (
        "the state root's own target was not flipped"
    )
    assert _read(root, superseding_id)["supersedes"] == BASELINE_ID
    decoy_record = json.loads(
        (decoy / "noni" / "decisions" / f"{DECIDE_DECOY_ID}.json").read_text(
            encoding="utf-8"))
    assert decoy_record["status"] == "decided", (
        "the supersede flipped a record in the decoy ledger, not the state root's"
    )
    assert _decide_snapshot(decoy) == before
    assert not (cwd / "noni").exists()


def test_decide_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is refused as a state-root problem (exit 3,
    with the path named), before the ledger's directory probe and before any
    git write, from a cwd that holds a complete decoy ledger.

    The decoy is the tempting target: it is a whole ledger a run driven by the
    cwd could have written into. The refusal must name the path the caller
    passed and leave both the decoy's bytes and the cwd untouched. Exit 3 is
    decide.py's existing code for a --repo that is not a work tree — the state
    root is not a git problem for the other writers and is not one for this one
    either, and the existing exit-3 contract is the test above.
    """
    _root, decoy, cwd = _decide_case(tmp_path)
    before = _decide_snapshot(decoy)
    missing = tmp_path / "no-such-state-root"

    proc = _decide_from(
        cwd, missing, "--slug", "scheduler", "--date", NEW_DATE, *BASE,
        *QUESTION, *OPTIONS, *ANSWERED,
    )
    assert proc.returncode == 3, (
        f"a missing state root must be the not-a-work-tree refusal, not "
        f"{proc.returncode}: {proc.stderr}"
    )
    assert "no-such-state-root" in proc.stderr, (
        f"the refusal must name the state root it was given: {proc.stderr}"
    )
    assert _decide_snapshot(decoy) == before, (
        "a refused run wrote the decoy ledger beside its cwd"
    )
    assert not (cwd / "noni").exists(), (
        "a refused run created noni/ under the cwd"
    )


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
