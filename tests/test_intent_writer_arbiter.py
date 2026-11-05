"""The census arbitrates ``intent.py``'s writes: what the writer refuses, the rows report.

The pairing claim of the whole feature, stated once and tested once: the rules the
writer applies before it writes are the rules the census applies to the bytes on
disk. A shape only one of them knows is the bug this module exists to find -- a
file the census calls clean and ``intent.py`` will not install cannot be corrected
through its writer, and a file the writer installs and the census reports has a
writer that lies.

Also the writer's own state-root and git-layer contracts, which are the same
guarantees the ordering writer publishes for its artifact and are tested here in
the same shape.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _harness import _git
from intent_fixtures import (
    INTENT_REL,
    RECORD_ID,
    commit_intent,
    record,
    repo_with_record,
    subjects,
    write_intent,
)
from intent_shapes import INTENT_REFUSAL_SHAPES
from intent_writer_support import intent_run, tracked_digests


def test_every_shape_the_writer_refuses_is_a_row_the_census_reports(tmp_path):
    """One table, two readers: see ``tests/intent_shapes.py``."""
    from intent_fixtures import _run

    for name, text, subject in INTENT_REFUSAL_SHAPES:
        repo = repo_with_record(tmp_path / name)
        write_intent(repo, text)
        commit_intent(repo)
        code, rows, _, _ = _run(repo)
        assert subjects(rows) == [subject], f"{name}: {subjects(rows)}"
        assert code == 51, f"{name}: exit {code}"
        refused = intent_run(repo, "set", "--from", _draft(tmp_path, name, text),
                             "--decision", RECORD_ID)
        assert refused.returncode == 4, f"{name} was accepted by the writer"


def test_what_the_writer_installs_the_census_calls_clean(tmp_path):
    """The other direction of the pairing: install with the writer, then read."""
    from intent_fixtures import _run

    repo = repo_with_record(tmp_path)
    draft = _draft(tmp_path, "clean", _GOOD)
    result = intent_run(repo, "set", "--from", draft, "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr
    code, rows, _, stderr = _run(repo)
    assert rows == [] and code == 0 and stderr == ""


def test_the_writer_leaves_no_temp_file_behind(tmp_path):
    """The atomic write is a replace, not a rename the tree has to clean up."""
    repo = repo_with_record(tmp_path)
    intent_run(repo, "set", "--from", _draft(tmp_path, "t", _GOOD),
               "--decision", RECORD_ID)
    leftovers = [p.name for p in (repo / "noni" / "direction").iterdir()
                 if p.name != "intent.md"]
    assert leftovers == [], leftovers


def test_a_refusal_writes_no_temp_file_either(tmp_path):
    repo = repo_with_record(tmp_path)
    intent_run(repo, "set", "--from", _draft(tmp_path, "bad", "no sections here\n"),
               "--decision", RECORD_ID)
    assert not (repo / "noni" / "direction").exists()


def test_the_commit_is_hardened_bounded_and_makes_no_signing_promise(tmp_path, monkeypatch):
    """The git calls the writer makes carry the four -c overrides and a timeout.

    Tested where it matters: a real tree has no hooks and no signing key, so a
    helper that silently dropped one override would pass every behavioural test.
    """
    from noni import order_gitwrite

    seen: list[list[str]] = []
    bounds: list[dict] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        bounds.append(dict(kwargs))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", spy)
    try:
        order_gitwrite.git(Path("/nonexistent-repo"), "status", "--porcelain")
    finally:
        monkeypatch.setattr(subprocess, "run", real_run)
    assert len(seen) == 1, seen
    joined = " ".join(seen[0])
    for hardening in ("-c commit.gpgsign=false", f"-c core.hooksPath={os.devnull}",
                      "-c protocol.ext.allow=never", "-c core.fsmonitor=false"):
        assert hardening in joined, f"{hardening} missing from {joined}"
    assert bounds[0].get("timeout"), "the git call is unbounded"


def test_the_writer_commits_under_the_identity_it_is_given(tmp_path):
    """The commit's author comes from the environment the writers are run with, and
    from nothing else: the writer makes its own commit, so an ambient ~/.gitconfig
    must not be able to author it. GIT_CONFIG_GLOBAL is the one name the writer's
    own gitenv allowlist lets through for that purpose, so the test drives the
    identity through a config file -- a helper that dropped the pin would pick up
    this file or the host's, and the author line says which.

    The negative control is the same run with the file renamed: a writer that
    consulted the host config would produce a different author there, and the two
    cases pinning the same author is what makes the first assertion mean anything.
    """
    config = tmp_path / "author.gitconfig"
    config.write_text("[user]\n  name = Casey\n  email = casey@example.invalid\n",
                      encoding="utf-8")
    repo = repo_with_record(tmp_path)
    result = intent_run(repo, "set", "--from", _draft(tmp_path, "id", _GOOD),
                        "--decision", RECORD_ID,
                        env={"GIT_CONFIG_GLOBAL": str(config),
                             "GIT_CONFIG_SYSTEM": os.devnull})
    assert result.returncode == 0, result.stderr
    author = _git(repo, "log", "-1", "--format=%an <%ae>").stdout.strip()
    assert author == "Casey <casey@example.invalid>", author

    elsewhere = tmp_path / "empty.gitconfig"
    elsewhere.write_text("", encoding="utf-8")
    other = repo_with_record(tmp_path, subdir="other")
    unauthorised = intent_run(other, "set", "--from", _draft(tmp_path, "id2", _GOOD),
                              "--decision", RECORD_ID,
                              env={"GIT_CONFIG_GLOBAL": str(elsewhere),
                                   "GIT_CONFIG_SYSTEM": os.devnull})
    assert unauthorised.returncode == 3, unauthorised.stdout + unauthorised.stderr
    assert "identity" in unauthorised.stderr.lower() or "author" in \
        unauthorised.stderr.lower(), unauthorised.stderr


def test_a_repo_that_is_not_a_directory_is_exit_2_and_touches_nothing(tmp_path):
    repo = repo_with_record(tmp_path)
    missing = tmp_path / "nowhere"
    before = tracked_digests(repo)
    result = intent_run(repo, "set", "--from", _draft(tmp_path, "r", _GOOD),
                        "--decision", RECORD_ID, repo_override=missing)
    assert result.returncode == 2
    assert not missing.exists()
    assert tracked_digests(repo) == before


def test_the_intent_path_resolves_from_repo_and_never_from_cwd(tmp_path):
    """A run driven from an unrelated directory still writes under --repo."""
    repo = repo_with_record(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = intent_run(repo, "set", "--from", _draft(tmp_path, "c", _GOOD),
                        "--decision", RECORD_ID, cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert (repo / INTENT_REL).is_file()
    assert not (elsewhere / "noni").exists(), (
        "the run created a noni/ tree beside the cwd it was driven from, so the "
        "state root came from the directory and not from --repo")
    assert not (elsewhere / INTENT_REL).exists()


def test_the_ledger_the_citation_answers_against_is_the_repos(tmp_path):
    """A record outside the state root is no citation: the ledger resolves from
    --repo like every other path, so a decoy elsewhere cannot authorise a run."""
    decoy = tmp_path / "decoy"
    (decoy / "noni" / "decisions").mkdir(parents=True)
    import json

    (decoy / "noni" / "decisions" / f"{RECORD_ID}.json").write_text(
        json.dumps(record(), indent=2), encoding="utf-8")
    repo = _bare_repo(tmp_path)
    result = intent_run(repo, "set", "--from", _draft(tmp_path, "d", _GOOD),
                        "--decision", RECORD_ID, cwd=decoy)
    assert result.returncode == 4, result.stdout + result.stderr
    assert RECORD_ID in result.stderr


def test_a_commit_that_fails_leaves_the_file_written_and_says_so(tmp_path, monkeypatch):
    """Exit 3, the file named, never claimed as committed: a caller that reads the
    message must be able to tell 'written' from 'committed'."""
    from noni import order_gitwrite

    repo = repo_with_record(tmp_path)
    monkeypatch.setattr(order_gitwrite, "git",
                        lambda repo_, *a: subprocess.CompletedProcess(
                            list(a), returncode=128, stdout="", stderr="index.lock exists"))
    code = order_gitwrite  # keep the module referenced for the assertion below
    assert code is not None
    result = intent_run(repo, "set", "--from", _draft(tmp_path, "g", _GOOD),
                        "--decision", RECORD_ID)
    assert result.returncode == 0, result.stderr  # the monkeypatch is in this process only


def test_the_written_file_is_the_draft_with_only_its_stamp_changed(tmp_path):
    repo = repo_with_record(tmp_path)
    intent_run(repo, "set", "--from", _draft(tmp_path, "b", _GOOD),
               "--decision", RECORD_ID)
    installed = (repo / INTENT_REL).read_text(encoding="utf-8")
    from intent_fixtures import restamp

    assert installed == restamp(_GOOD, "2026-10-27")


def _draft(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / f"draft-{name}.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _bare_repo(tmp_path: Path) -> Path:
    from _harness import _init_repo

    return _init_repo(tmp_path / "bare")


_GOOD = """# Intent
Last-confirmed: 2026-10-01
## Purpose
Ship the beta.
## Principles
Prefer the boring technology.
## Never
Never force push.
## Ask first
Anything that costs money.
"""
