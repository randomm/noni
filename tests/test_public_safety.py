"""Public-repo hygiene tests (issue #8).

The scrub check (scripts/public_safety.py) must pass on a clean tree and fail,
naming file and line, on a planted violation of each class: machine-local
absolute home paths, common secret shapes, and deny-list names. Every planted
violation uses a synthetic name — no real operator name, username, host or
tool name appears in this file or its fixtures.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The package module is the only importable home of the checker; the bare alias
# is registered by _harness from the same package object.
import public_safety  # noqa: E402
from _harness import _git  # noqa: E402


def _clean_repo(tmp_path, monkeypatch):
    """A throwaway git repo whose tracked files contain no violations.

    The body of the fixture below, and the one the sibling module
    ``tests/test_public_safety_non_regular.py`` builds its own ``clean_repo``
    fixture from. The scrub's unit tests and its non-regular-path tests
    (issue #91) are one suite split for the size rule, not two fixtures: a tree
    that reads clean to one file and dirty to the other would make their
    verdicts incomparable, so the tree has exactly one builder.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text(
        "# clean\n\nA generic product note with no personal details.\n",
        encoding="utf-8",
    )
    (repo / "config.json").write_text('{"mode": "default"}\n', encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "add", "config.json")
    _git(repo, "commit", "-q", "-m", "snapshot")

    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: tmp_path / "absent-denylist.txt")
    monkeypatch.delenv(public_safety.DENYLIST_ENV_VAR, raising=False)
    return repo


@pytest.fixture
def clean_repo(tmp_path, monkeypatch):
    """The shared clean-tree fixture (see :func:`_clean_repo`)."""
    return _clean_repo(tmp_path, monkeypatch)

def test_scrub_passes_on_clean_fixture(clean_repo):
    """A clean tracked tree produces no violations (either with or without a
    deny-list)."""
    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []


def test_scrub_fails_on_planted_home_path(clean_repo):
    """A machine-local absolute home path is flagged, naming file and line."""
    (clean_repo / "note.md").write_text("/Users/admin/docs is the path\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant path")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert len(violations) == 1
    assert violations[0].startswith("note.md:1:")
    assert "home path" in violations[0]


def test_scrub_fails_on_planted_linux_home_path(clean_repo):
    """A /home/<well-known identity> path is flagged, naming file and line."""
    (clean_repo / "note.md").write_text("/home/admin/.ssh/id_ed25519\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant linux path")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert len(violations) == 1
    assert violations[0].startswith("note.md:1:")
    assert "home path" in violations[0]


def test_scrub_fails_on_planted_secret(clean_repo):
    """A common secret shape is flagged, naming file and line."""
    (clean_repo / "note.md").write_text("token ghp_synthsynthsynthsynthsynth123\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant secret")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert len(violations) == 1
    assert violations[0].startswith("note.md:1:")
    assert "token" in violations[0]


def test_scrub_fails_on_denylist_entry(clean_repo, tmp_path, monkeypatch):
    """A deny-list entry (loaded from the local untracked file) is flagged."""
    denylist = tmp_path / "absent-denylist.txt"
    denylist.write_text("# comment\n\nsynthetic-project-name\n", encoding="utf-8")
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: denylist)

    (clean_repo / "note.md").write_text("port from synthetic-project-name\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant denylist name")

    violations, source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert source == denylist.as_posix()
    assert len(violations) == 1  # only the deny-list entry matches
    assert "deny-list entry" in violations[0]
    assert violations[0].startswith("note.md:1:")
    assert "deny-list entry" in violations[0]


def test_scrub_notice_when_denylist_absent(clean_repo, capsys):
    """When no deny-list file exists, the deny-list class is skipped with a
    prominent stderr notice while the built-in patterns still run. The notice
    explicitly states that the run is NOT a scrub-clean guarantee."""
    violations, source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []
    assert source is None
    captured = capsys.readouterr()
    assert "deny-list class SKIPPED" in captured.err
    assert "NOT a scrub-clean guarantee" in captured.err


def test_denylist_present_but_empty_is_not_active(clean_repo, tmp_path, monkeypatch):
    """A deny-list file that exists but has zero usable entries (e.g. only
    comments) is present-but-empty: the deny-list class has no entries to
    apply, so it is not active and the CLI refuses to report clean.
    """
    empty = tmp_path / "empty-denylist.txt"
    empty.write_text("# only comments so far\n\n", encoding="utf-8")
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: empty)

    result = public_safety.load_denylist(clean_repo)
    assert result.entries == []
    assert result.status == "ok"
    assert result.source == empty.as_posix()
    assert not public_safety._denylist_active(result)

    # The scrub itself still runs; the file was loaded (source is not None),
    # but with zero entries the class is not active.
    violations, source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []
    assert source == empty.as_posix()


def test_scrub_denylist_env_var_precedence(clean_repo, tmp_path, monkeypatch):
    """The env-var-named deny-list file is used when the default file is
    absent, and the file deny-list takes precedence over the env var."""
    env_denylist = tmp_path / "env-denylist.txt"
    env_denylist.write_text("synthetic-env-name\n", encoding="utf-8")
    file_denylist = tmp_path / "absent-denylist.txt"
    file_denylist.write_text("synthetic-file-name\n", encoding="utf-8")

    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: file_denylist)
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, env_denylist.as_posix())

    result = public_safety.load_denylist(clean_repo)
    assert result.source == file_denylist.as_posix()
    assert result.entries == ["synthetic-file-name"]

    file_denylist.unlink()
    result = public_safety.load_denylist(clean_repo)
    assert result.source == env_denylist.as_posix()
    assert result.entries == ["synthetic-env-name"]


def test_scrub_skips_binary_file_gracefully(clean_repo):
    """A binary tracked file is skipped without crashing the scrub."""
    binary = clean_repo / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02\xff\xfe" + b"not utf8 \x80\x81")
    _git(clean_repo, "add", "blob.bin")
    _git(clean_repo, "commit", "-q", "-m", "binary")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []


def test_scrub_checks_tracked_files_only(clean_repo):
    """Untracked files are not scanned (the scrub covers git ls-files only)."""
    (clean_repo / "untracked.md").write_text("synthetic-untracked secret here\n", encoding="utf-8")
    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []


def test_scrub_excludes_own_source(clean_repo):
    """The scrub module and the scrub test file are exempt from the scrub
    because they carry the built-in pattern literals (home-path regexes, token
    prefixes, the private key block marker) that would otherwise self-match.
    No other test file needs an exemption: tracked files may carry only
    synthetic names, so nothing planted in a test file can hide behind it. A
    planted violation in any *other* tracked file is still caught (see
    test_scrub_exemption_does_not_hide_planted_secret)."""
    violations, _, _ = public_safety.scrub_tracked_files(REPO)
    assert not any(v.startswith("scripts/public_safety.py") for v in violations)
    assert not any(v.startswith("tests/test_public_safety.py") for v in violations)


def test_scrub_exemption_keeps_pattern_literal_file_clean(clean_repo, monkeypatch):
    """The self-file exemption keeps the pattern-definition file (the scrub
    module itself) clean from its own literals, while the same deny-list entry
    planted in a non-exempt file of a throwaway fixture repo is flagged — all
    with a synthetic name, no real external tool/project name anywhere.
    """
    literal = "synthetic-vocab-name"

    denylist = clean_repo / ".denylist"
    denylist.write_text(literal + "\n", encoding="utf-8")
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, denylist.as_posix())

    # The scrub module (in this repo) carries its own pattern literals; the
    # exemption is what keeps it clean under the built-in patterns.
    violations, _, _ = public_safety.scrub_tracked_files(REPO)
    assert not any(v.startswith("scripts/public_safety.py") for v in violations), (
        f"scripts/public_safety.py carries pattern literals; the exemption must keep it clean: {violations}"
    )

    # The same entry in a non-exempt file of the throwaway repo is caught.
    (clean_repo / "note.md").write_text(literal + "\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant vocab")
    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(v.startswith("note.md:1:") and "deny-list entry" in v for v in violations)


def test_scrub_exemption_does_not_hide_planted_secret(clean_repo):
    """The self-file exemption only covers the pattern-definition files;
    a planted secret in any *other* tracked file is still caught."""
    (clean_repo / "note.md").write_text("/home/builder/secret\n", encoding="utf-8")
    _git(clean_repo, "add", "note.md")
    _git(clean_repo, "commit", "-q", "-m", "plant in non-exempt file")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(v.startswith("note.md") for v in violations), (
        "a planted home path in a non-exempt file must be caught"
    )


def test_scrub_exemption_does_not_hide_planted_denylist_entry(clean_repo, monkeypatch):
    """The per-pattern self-file exemption never exempts the deny-list
    class: a deny-list entry planted into a copy of an exempted file path in
    the throwaway fixture repo (an exact match of a _SELF_FILES relative
    path) is still flagged."""
    denylist = clean_repo / ".denylist"
    denylist.write_text("synthetic-planted-name\n", encoding="utf-8")
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, denylist.as_posix())

    (clean_repo / "scripts").mkdir()
    (clean_repo / "scripts" / "public_safety.py").write_text(
        "helper = \"synthetic-planted-name\"\n", encoding="utf-8"
    )
    _git(clean_repo, "add", "scripts/public_safety.py")
    _git(clean_repo, "commit", "-q", "-m", "plant denylist entry in exempt path")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(
        v.startswith("scripts/public_safety.py:1:") and "deny-list entry" in v for v in violations
    ), (f"a deny-list entry in an exempt file path must be caught: {violations}")


def test_scrub_exemption_does_not_hide_planted_secret_in_exempt_file(clean_repo):
    """A secret-shaped token planted into a copy of an exempted file path in
    the throwaway fixture repo is still flagged: only the built-in patterns
    whose fixture literals live in the self files (home-path patterns and
    the ghp_ pattern) are exempted; the AKIA secret-shape pattern is not in
    the exempt set and is therefore still active on self files."""
    (clean_repo / "tests").mkdir()
    token = "AKIA" + "ABCDEFGHIJKLMNOP"
    (clean_repo / "tests" / "test_public_safety.py").write_text(
        f"TOKEN = \"{token}\"\n", encoding="utf-8"
    )
    _git(clean_repo, "add", "tests/test_public_safety.py")
    _git(clean_repo, "commit", "-q", "-m", "plant secret in exempt path")

    violations, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(
        v.startswith("tests/test_public_safety.py:1:") and "AWS access key" in v for v in violations
    ), (f"a secret-shaped token in an exempt file path must be caught: {violations}")


def test_denylist_corrupt_file_degrades_gracefully(clean_repo, tmp_path, monkeypatch):
    """A non-UTF-8 deny-list file is classified as corrupt (status "corrupt",
    entries empty), so the scrub degrades instead of crashing and the CLI's
    exit-2 guard fires instead of reporting a false clean."""
    corrupt = tmp_path / "corrupt-denylist.bin"
    corrupt.write_bytes(b"\x80\x81\x82 not utf8")
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: corrupt)

    result = public_safety.load_denylist(clean_repo)
    assert result.entries == []
    assert result.status == "corrupt"

    # scrub_tracked_files reports the deny-list class as not active.
    violations, source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []
    assert source is None


def test_denylist_corrupt_default_falls_through_to_env_var(clean_repo, tmp_path, monkeypatch, capsys):
    """When the default deny-list file exists but is unreadable, loading
    continues to the env-var-named candidate instead of returning "corrupt"
    immediately — the env-var file (if present) takes effect, and a visible
    notice is printed for the corrupt file."""
    corrupt = tmp_path / "corrupt-denylist.bin"
    corrupt.write_bytes(b"\x80\x81\x82 not utf8")
    env_denylist = tmp_path / "env-denylist.txt"
    env_denylist.write_text("synthetic-env-name\n", encoding="utf-8")

    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: corrupt)
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, env_denylist.as_posix())

    result = public_safety.load_denylist(clean_repo)
    assert result.status == "ok"
    assert result.source == env_denylist.as_posix()
    assert result.entries == ["synthetic-env-name"]

    # A visible notice was printed for the corrupt default file.
    captured = capsys.readouterr()
    assert "unreadable" in captured.err


def test_denylist_is_read_from_the_audited_tree_not_the_cwd(tmp_path, monkeypatch):
    """The default deny-list is sought in the tree being audited, not in the
    process's working directory.

    The scrub is given a tree and the wheel copy of this module sits anywhere on
    the machine, so a default path derived from ``Path.cwd()`` finds the operator
    deny-list only by accident — a publishing gate run from another directory
    silently drops the whole operator-name half and still prints nothing. The
    fixture puts the deny-list at the audited root with a tracked file carrying
    its entry, runs the scan with the process cwd somewhere else, and requires
    the violation to be found."""
    repo = tmp_path / "audited"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "note.md").write_text("port from synthetic-project-name\n", encoding="utf-8")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "snapshot")
    (repo / public_safety.DENYLIST_FILENAME).write_text(
        "synthetic-project-name\n", encoding="utf-8"
    )

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(public_safety.DENYLIST_ENV_VAR, raising=False)

    result = public_safety.load_denylist(repo)
    assert result.status == "ok", f"the audited tree's deny-list was not read: {result}"
    assert result.entries == ["synthetic-project-name"]
    assert result.source == str((repo / public_safety.DENYLIST_FILENAME).resolve())

    violations, source, _ = public_safety.scrub_tracked_files(repo)
    assert source is not None, "the scrub did not activate the deny-list class"
    assert [v for v in violations if v.startswith("note.md:1:")
            and "deny-list entry" in v], violations


def test_denylist_is_loaded_from_the_audited_tree(tmp_path, monkeypatch):
    """A tree that carries its own untracked deny-list is scanned with it, with
    no environment variable involved."""
    repo = tmp_path / "audited"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "note.md").write_text("port from synthetic-project-name\n", encoding="utf-8")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "snapshot")
    (repo / public_safety.DENYLIST_FILENAME).write_text(
        "synthetic-project-name\n", encoding="utf-8"
    )
    monkeypatch.delenv(public_safety.DENYLIST_ENV_VAR, raising=False)

    result = public_safety.load_denylist(repo)
    assert result.entries == ["synthetic-project-name"], result


def test_repo_local_fsmonitor_helper_does_not_run_during_a_scan(clean_repo):
    """The scan's ``git ls-files`` is hardened against the audited tree's own
    config.

    ``core.fsmonitor`` names a program git execs to ask which files changed, so
    a config planted in the tree being scanned turns a read-only listing into
    execution of that tree's code under the scanner's privileges. The helper here
    exits 0 and writes a marker, so the marker's absence is the assertion; the
    scan still returning its violations for the tree is the control that says the
    listing itself happened.
    """
    marker = clean_repo / "FSMONITOR_RAN"
    helper = clean_repo / "fsmonitor-helper.sh"
    helper.write_text(
        "#!/bin/sh\n" + "printf x > " + str(marker) + "\nexit 0\n", encoding="utf-8"
    )
    helper.chmod(0o755)
    _git(clean_repo, "config", "core.fsmonitor", str(helper))
    # A fresh mtime on the index is what asks git to query the monitor: without
    # it the stat cache answers and the helper is never reached, so the
    # assertion would pass for no reason.
    index = clean_repo / ".git" / "index"
    stat_before = index.stat()
    os.utime(index, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 2_000_000_000))

    violations, _source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []
    assert not marker.exists(), "the scrub ran a core.fsmonitor helper it must not run"


def test_noni_repo_is_clean():
    """The noni repo itself is clean under the built-in patterns (the local
    deny-list may additionally be present on the operator's machine; the
    built-in run must pass either way). The self-file exemption covers the
    two files that carry built-in pattern literals (the scrub module and the
    scrub test file); everything else must be violation-free."""
    violations, _, _ = public_safety.scrub_tracked_files(REPO)
    assert violations == []


def test_denylist_path_is_gitignored():
    """The local deny-list path is in .gitignore and git agrees it is
    ignored, so it can never be committed."""
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "/.noni-scrub-denylist" in gitignore
    result = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", ".noni-scrub-denylist"],
        capture_output=True,
    )
    assert result.returncode == 0, ".noni-scrub-denylist is not git-ignored"
