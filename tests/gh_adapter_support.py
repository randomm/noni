"""Shared fixture loading and sys.path setup for the GitHub-issues adapter suites.

The adapter lives under ``integrations/github-issues/`` with no package, so the
two importable modules there (``adapter_protocol`` and ``github_issues_adapter``)
are reached by a ``sys.path`` insertion — the established pattern for repo-local
modules. Every adapter suite performs that insertion the same way and reads the
same synthetic fixtures, so it lives here once.

All fixtures under ``tests/fixtures/gh-adapter/`` are synthetic-only (synthetic
users, synthetic repos) and are read offline: the adapter's two seams are pure
functions of (payload, allow-list), so no test touches the network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GH_FIXTURES = REPO / "tests" / "fixtures" / "gh-adapter"

# Make integrations/ and integrations/github-issues/ importable (no package;
# sys.path insertion is the established pattern for repo-local modules).
_INTEGRATIONS = REPO / "integrations"
_GH_ADAPTER = _INTEGRATIONS / "github-issues"
for _p in (str(_INTEGRATIONS), str(_GH_ADAPTER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import adapter_protocol  # noqa: E402,F401
import github_issues_adapter as adapter  # noqa: E402,F401

#: The synthetic allow-list every test in these modules uses. Real operator
#: names live only in the untracked local allow-list file; the test uses
#: synthetic account names.
ALLOWED = {"op-1"}
NOT_ALLOWED = {"stranger-1"}


def _load_fixture(name: str) -> dict:
    return json.loads((GH_FIXTURES / name).read_text(encoding="utf-8"))
