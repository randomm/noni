"""Public-repo hygiene tests (issue #8).

The scrub check (scripts/public_safety.py) must pass on a clean tree and fail,
naming file and line, on a planted violation of each class: machine-local
absolute home paths, common secret shapes, and deny-list names. Every planted
violation uses a synthetic name — no real operator name, username, host or
tool name appears in this file or its fixtures.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Make the scripts/ directory importable so `import public_safety` resolves
# to scripts/public_safety.py.
_scripts_dir = str(REPO / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import public_safety  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(repo), "-c", "user.name=Synthetic Tester", "-c", "user.email=testing@fixture.invalid", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_first = result.stderr.strip().splitlines()[0] if result.stderr.strip() else "no stderr"
        raise RuntimeError(f"git {args[0]} failed: {stderr_first}")
    return result

@pytest.fixture
def clean_repo(tmp_path, monkeypatch):
    """A throwaway git repo whose tracked files contain no violations."""
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

    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: tmp_path / "absent-denylist.txt")
    monkeypatch.delenv(public_safety.DENYLIST_ENV_VAR, raising=False)
    return repo


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
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: denylist)

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
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: empty)

    result = public_safety.load_denylist()
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

    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: file_denylist)
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, env_denylist.as_posix())

    result = public_safety.load_denylist()
    assert result.source == file_denylist.as_posix()
    assert result.entries == ["synthetic-file-name"]

    file_denylist.unlink()
    result = public_safety.load_denylist()
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
    """The scrub module, its test file, and test_purity.py (which carries
    deny-list vocabulary as regex patterns) are exempt from the scrub, so
    their own literals do not self-match. A planted secret in any *other*
    tracked file is still caught (see
    test_scrub_exemption_does_not_hide_planted_secret)."""
    violations, _, _ = public_safety.scrub_tracked_files(REPO)
    assert not any(v.startswith("scripts/public_safety.py") for v in violations)
    assert not any(v.startswith("tests/test_public_safety.py") for v in violations)
    assert not any(v.startswith("tests/test_purity.py") for v in violations)


def test_scrub_exemption_covers_denylist_vocabulary_file(clean_repo, monkeypatch):
    """The test_purity.py exemption exists because that file carries
    deny-list vocabulary (external project names) as regex literals. Pin the
    rationale: with a deny-list entry matching a literal already present in
    tests/test_purity.py, the scrub must not flag that file (the exemption
    is what keeps it clean), while the same entry in a non-exempt file is
    flagged.
    """
    purity_text = (REPO / "tests" / "test_purity.py").read_text(encoding="utf-8")
    literal = next(name for name in ("pi-rukas", "tehas", "hermes") if name in purity_text)

    denylist = clean_repo / ".denylist"
    denylist.write_text(literal + "\n", encoding="utf-8")
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, denylist.as_posix())

    # The exempt file (in this repo) is not flagged by its own vocabulary.
    violations, _, _ = public_safety.scrub_tracked_files(REPO)
    assert not any(v.startswith("tests/test_purity.py") for v in violations), (
        f"tests/test_purity.py carries deny-list vocabulary; the exemption must keep it clean: {violations}"
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


def test_denylist_corrupt_file_degrades_gracefully(clean_repo, tmp_path, monkeypatch):
    """A non-UTF-8 deny-list file is classified as corrupt (status "corrupt",
    entries empty), so the scrub degrades instead of crashing and the CLI's
    exit-2 guard fires instead of reporting a false clean."""
    corrupt = tmp_path / "corrupt-denylist.bin"
    corrupt.write_bytes(b"\x80\x81\x82 not utf8")
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: corrupt)

    result = public_safety.load_denylist()
    assert result.entries == []
    assert result.status == "corrupt"

    # scrub_tracked_files reports the deny-list class as not active.
    violations, source, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == []
    assert source is None


def test_noni_repo_is_clean():
    """The noni repo itself is clean under the built-in patterns (the local
    deny-list may additionally be present on the operator's machine; the
    built-in run must pass either way)."""
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
