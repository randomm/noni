"""The throwaway tree every allowlist test runs over, shared by the four modules.

The allowlist tests are split across four files (the 500-line cap in
``tests/test_file_size_limit.py`` has no override, and the seam is a real one: what an
entry exempts, what a stale entry earns, what a refused file does, and what the CLI exits
with). All four run over the same tree, and a copy of the builder in each is how the
fixture and the tests drift -- so it lives here, and ``tests/conftest.py`` re-exports it
as the fixture, which is the only place pytest collects fixtures from outside a test file.

The deny-list is activated because exemption is a property of the scan, not of the
deny-list class: a tree with no deny-list earns the inactive-class row, and a test that
asserts "this fixture produced no violation" would read that row as a violation and fail
for a reason it is not about. ``tests/test_census_hygiene.py`` pins the inactive class.
"""

from __future__ import annotations

import public_safety
import pytest
from _harness import _git, _init_repo
from harness_faults import _home_path_violation, _secret_violation

# The label strings the scan emits, spelled as the product spells them, and the planted
# content assembled at runtime from the pattern tables: a test file that carried a
# token-shaped literal would need an allowlist entry to pass the check it is testing.
SECRET_LABEL = "GitHub classic token"
HOME_LABEL = "machine-local absolute home path (/home/<known identity>)"
SECRET_LINE = f"token {_secret_violation()}"
TOKEN_FIXTURE = SECRET_LINE + "\n"
HOME_VIOLATION = _home_path_violation()


def commit_planted(repo, rel, content):
    """Write one file into ``repo`` and commit it, so the scan's listing holds it."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "-m", f"plant {rel}")


@pytest.fixture
def clean_repo(tmp_path, monkeypatch):
    """A throwaway repo with one clean tracked file, an active deny-list, no allowlist."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean")
    denylist = tmp_path / "denylist"
    denylist.write_text("synthetic-vocab-name\n", encoding="utf-8")
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, str(denylist))
    return repo
