"""The census's git layer is hardened against the repository it reads.

Every git call the census makes runs under a pinned environment and a fixed
``-c`` block, so a repository someone else prepared cannot turn a read into
execution of a program that repository names. Nothing else in the suite pins
that block: the writers' own pins (``tests/test_order_writer_git_layer.py``,
``tests/test_intent_writer_arbiter.py``) sit on the writer helper the census
never calls, so a regression that dropped one override from the census's
``-c`` list would pass the whole suite.

There is no marker-file test here. The census reads history with ``rev-parse``,
``log`` and ``cat-file``, and none of those verbs consults ``core.fsmonitor``,
so a helper planted in an audited tree is never execed by this run whatever it
passes: such a test would pass on unhardened code and prove nothing. The
override is defence in depth and consistency with the writer paths and the
hygiene listing, which already carry it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import census
from _harness import REPO, _commit_file, _init_repo
from census_fixtures import _valid_record
from census_run import _run_census

# The three overrides, in the order the builder returns them. protocol.ext.allow
# closes the external transport helper, core.hooksPath moves hooks out of the
# audited tree, core.fsmonitor stops git execing the tree's file-system monitor.
HARDENING = ["-c", "protocol.ext.allow=never",
             "-c", f"core.hooksPath={os.devnull}",
             "-c", "core.fsmonitor=false"]

# The verbs of the census's own git calls, one per subprocess site: _git_top,
# Git.__init__ (once for HEAD, once for the history walk), Git.added_paths_under
# and Git.blob_content_sha1.
CENSUS_VERBS = (["rev-parse", "--show-toplevel"], ["rev-parse", "HEAD"],
                ["log", "--all"], ["cat-file", "blob"])

RECORD_REL = "noni/decisions/2026-10-01-alpha.json"


def _ledger_repo(tmp_path: Path) -> Path:
    """A state root with one committed decision record.

    The record is what makes the census read history at all: with no path under
    ``noni/decisions/`` the edit check has nothing to digest and the run makes
    no ``cat-file`` call for the spy to record.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, RECORD_REL, json.dumps(_valid_record(), indent=2))
    return repo


def _census_git_call(cmd: object, repo: Path) -> bool:
    """Whether ``cmd`` is one of the census's own git calls, not the harness's.

    The spy wraps subprocess.run, which the fixture's own git calls (init, add,
    commit) pass through too. The harness pins an identity as its first ``-c``
    pair and the census never does, so the shape of the ``-c`` block tells the
    two apart, along with the tree each call names.
    """
    if not isinstance(cmd, list) or cmd[:2] != ["git", "-C"] or len(cmd) < 4:
        return False
    if cmd[2] != str(repo):
        return False
    return cmd[3] != "-c" or not cmd[4].startswith("user.name=")


def _verb(cmd: list[str]) -> list[str]:
    """The git arguments of one census call: everything past the ``-c`` block."""
    index = 3
    while index + 1 < len(cmd) and cmd[index] == "-c":
        index += 2
    return cmd[index:]


def test_the_census_carries_three_hardening_overrides() -> None:
    """The census's own ``-c`` block, asserted on its one builder.

    The three sites that shell out (``Git._run``, ``Git.blob_content_sha1``,
    ``_git_top``) all spread this list into their argv and none builds its own,
    so the builder is where the contract lives. Membership and order are both
    pinned, not a subset test: a fourth setting is not this ticket's to add and
    a dropped one is the hole the pin exists to close.
    """
    assert census._git_config_args() == HARDENING


def test_the_skill_names_the_settings_the_builder_carries() -> None:
    """The skill's read-only git bullet names every setting the builder carries.

    The bullet is the operator-facing promise about what a census run pins, so
    it must say ``core.fsmonitor=false`` where the code applies it. The list is
    read from the builder rather than typed a second time, so a setting that
    joins one side and not the other is caught here.
    """
    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    for pair in HARDENING[1::2]:
        assert pair in text, f"SKILL.md does not name {pair} in its read-only git bullet"


def test_every_census_git_call_carries_the_fsmonitor_override(tmp_path, monkeypatch):
    """Every git argv the census builds disables the tree's file-system monitor.

    The argv pin above proves the builder; this proves the sites. A call that
    built its own ``-c`` list, or dropped the spread, would still pass the
    builder assertion and would hand the audited tree a way to name a program
    for git to exec. The harness's fixture calls are filtered out by their
    identity ``-c`` pair, so only the census's own command lines are asserted.
    """
    repo = _ledger_repo(tmp_path)
    seen: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *args, **kwargs):
        argv = [str(part) for part in cmd]
        if _census_git_call(argv, repo):
            seen.append(argv)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(census.subprocess, "run", spy)
    _run_census(repo, "--now", "2026-10-02T00:00:00Z", "--skip", "hygiene")

    assert seen, f"the census made no git call of its own in {repo}"
    for expected in CENSUS_VERBS:
        assert any(_verb(cmd)[:len(expected)] == expected for cmd in seen), (
            f"the census made no {' '.join(expected)} call of its own: {seen}"
        )
    for cmd in seen:
        joined = " ".join(cmd)
        assert cmd[:2] == ["git", "-C"] and cmd[2] == str(repo), joined
        for pair in ("protocol.ext.allow=never", f"core.hooksPath={os.devnull}",
                     "core.fsmonitor=false"):
            assert f"-c {pair}" in joined, f"-c {pair} missing from {joined}"
