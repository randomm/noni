"""Core viability: with integrations/ removed, the core still passes.

The ticket's acceptance criterion: "with integrations/ removed, the full core
test suite and the census still pass on a fixture repo with no remote."

Two halves:

1. **The census passes on a fixture repo with no remote and no integrations
   dir.** A throwaway git repo (no remote) carrying a valid ledger record —
   including a tracker-sourced record with the new optional `source` field —
   censuses to exit 0. This is the behavioural half: the census (the
   core's arbiter) does not need integrations/ to be present, and it
   accepts a record that references a tracker issue and comment.

2. **The core test modules do not import integrations/.** A static scan of
   every core test module (the ones that exist without integrations/) for
   imports of the adapter modules proves the core's test suite does not
   depend on the adapter being installed. (The adapter's own test modules —
   test_adapter_interface.py, test_github_issues_adapter.py and the two
   modules split out of it, test_gh_adapter_allowlist.py and
   test_gh_adapter_labels.py — *do* import
   the adapter; they are the integration tests and are excluded here. They
   would be the ones that need integrations/ present.)

test_pi_extension.py is in the set too: it is the suite over the harness hook
under ``integrations/pi/``, so it reads that directory and is excluded from the
import scan the same way (it imports no adapter module, but its subject matter is
integrations/). It is self-contained: the hook is checked as text, so there is no
helper module beside it to name here. The one exception is
``pi_extension_source.py``, the readers that module imports for itself: same
reason, no adapter module behind it, so it joins the exclusion set.

test_codex_hook.py, its page suite ``test_codex_hook_page.py`` and their reader
``codex_hook_source.py`` join the set for the same reason: they are the suite over
the Codex harness hook under ``integrations/codex/``, they read that directory's
page, and neither imports an adapter module.

test_claude_code_hook.py and its reader ``claude_code_hook_source.py`` join the set
for the same reason: they are the suite over the Claude Code harness hook under
``integrations/claude-code/``, they read that directory's page, and neither imports
an adapter module.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import subprocess_env

REPO = Path(__file__).resolve().parent.parent

# Core test modules: every test module that does not import the adapter
# (i.e. the ones the core's test suite runs without integrations/ present).
# The adapter's own test modules are the integration tests; they are the ones
# that need integrations/ and are excluded from this viability scan. The list is
# the complete set: a new adapter suite has to be named here, and one that was
# renamed into the list (test_gh_adapter_allowlist.py, test_gh_adapter_labels.py)
# stays in it, so the scan's scope cannot narrow by accident.
ADAPTER_TEST_MODULES = {
    "test_adapter_interface.py",
    "test_github_issues_adapter.py",
    "test_gh_adapter_allowlist.py",
    "test_gh_adapter_labels.py",
    "test_pi_extension.py",
    # The readers the hook suites use, imported by them and by nothing else: the
    # span readers and the failure line's cap reader. Same reason, no adapter
    # module behind either.
    "pi_extension_source.py",
    "pi_extension_failure_line.py",
    # The two modules split out of test_pi_extension.py: same subject matter, the
    # hook's text, read as text.
    "test_pi_extension_failure_line.py",
    "test_pi_extension_falsifiability.py",
    # The claude-code harness hook (issue #216): its page and the readers over that
    # page. Same subject matter as the pi suite -- integrations/, read as text -- and
    # no adapter module behind either.
    "test_claude_code_hook.py",
    "claude_code_hook_source.py",
    # The suite that runs the Claude Code page's own hand check in a shell (issue
    # #238): same subject matter, that page under integrations/, but launched
    # rather than read, so it lives apart from the checks over the block's text.
    # It is not named by test_claude_code_hook.py, so the scan cannot find it.
    "test_claude_code_hand_check.py",
    # The suite over the Codex harness hook and its reader: same subject matter, the
    # page under integrations/codex/, read as text. The page's checks split in two the
    # way test_pi_extension.py did: the snippet's shape and the page's prose.
    "test_codex_hook.py",
    "test_codex_hook_page.py",
    "codex_hook_source.py",
}
CORE_TEST_MODULES = sorted(
    p for p in (REPO / "tests").glob("test_*.py") if p.name not in ADAPTER_TEST_MODULES
)


def test_census_passes_on_fixture_repo_no_remote_no_integrations(git_repo):
    """The census passes on a fixture repo with no remote and no integrations
    dir: exit 0 for a valid ledger, including a tracker-sourced record with
    the optional source field."""
    repo, commit = git_repo

    # The fixture repo has no remote (git_repo does not add one) and no
    # integrations/ dir (it is a bare tmp repo).
    assert (repo / "integrations").is_dir() is False, "fixture repo unexpectedly has integrations/"

    # A valid record (the golden baseline) censuses clean.
    valid_record = json.loads(
        (REPO / "tests" / "fixtures" / "decision-valid.json").read_text(encoding="utf-8")
    )
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    valid_path = ledger / f"{valid_record['id']}.json"
    valid_path.write_text(json.dumps(valid_record, indent=2), encoding="utf-8")
    commit({f"noni/decisions/{valid_record['id']}.json": valid_path.read_text()}, "record")

    proc = subprocess.run(
        [sys.executable, str(REPO / "skills" / "census" / "scripts" / "census.py"), "--repo", str(repo), "--now", "2026-10-01T12:00:00Z"],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=60,
    )
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"

    # A tracker-sourced record (the adapter's output shape) with the optional
    # source field also censuses clean: the core's census accepts the
    # provenance the adapter adds, without the adapter being present. The
    # supersede chain must resolve to exactly one live record, so the
    # superseded record is marked as such.
    valid_record["status"] = "superseded"
    valid_path.write_text(json.dumps(valid_record, indent=2), encoding="utf-8")
    commit({f"noni/decisions/{valid_record['id']}.json": valid_path.read_text()}, "superseded")

    sourced_record = dict(valid_record)
    sourced_record["id"] = "2026-10-02-steer-order"
    sourced_record["date"] = "2026-10-02T09:10:00Z"
    sourced_record["status"] = "decided"
    sourced_record["supersedes"] = "2026-10-01-alpha"
    sourced_record["source"] = {"issue_number": 42, "comment_id": 9102}
    source_path = ledger / f"{sourced_record['id']}.json"
    source_path.write_text(json.dumps(sourced_record, indent=2), encoding="utf-8")
    commit({f"noni/decisions/{sourced_record['id']}.json": source_path.read_text()}, "sourced record")

    proc = subprocess.run(
        [sys.executable, str(REPO / "skills" / "census" / "scripts" / "census.py"), "--repo", str(repo), "--now", "2026-10-02T12:00:00Z"],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"expected exit 0 for a sourced record on a no-remote fixture repo, got {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


@pytest.mark.parametrize("path", CORE_TEST_MODULES, ids=lambda p: p.name)
def test_core_test_modules_do_not_import_integrations(path):
    """No core test module imports the adapter: the core's test suite runs
    without integrations/ present (only the adapter's own test modules do)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    adapter_modules = {"adapter_protocol", "github_issues_adapter"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in adapter_modules, f"{path} imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            assert module not in adapter_modules, f"{path} imports from {node.module}"
