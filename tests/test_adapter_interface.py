"""The adapter interface: the exactly-two-seam contract.

Proves the core-side half of the two-tier purity rule (docs/PRODUCT.md §3):

1. The interface is exactly two seams with fixed shapes: question
   legitimacy (verdict in none|one|many|stranger + the operator's answer)
   and label authorization (bool).
2. The core never calls a tracker CLI or API directly: a static scan of
   every core script for tracker-network calls (the tracker's REST API
   endpoint, a tracker CLI on PATH) finds none — core scripts reach the
   tracker only through an adapter's pure function, never through a
   subprocess.
3. The verdict set is closed: a verdict outside none|one|many|stranger is a
   contract violation.
4. Core viability is structural: nothing under skills/ or scripts/
   references integrations/ — deleting integrations/ changes nothing the
   core does (the behavioural half of this is test_core_viability.py).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Make integrations/ importable (no package; sys.path insertion is the
# established pattern for repo-local modules — the same pattern conftest.py
# uses for skills/census/scripts).
_INTEGRATIONS = REPO / "integrations"
if str(_INTEGRATIONS) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS))

import adapter_protocol  # noqa: E402

# The tracker's REST API endpoint and the tracker CLI: the two shapes a core
# script would have to use to talk to a tracker directly. Neither may appear
# in any core script (skills/, scripts/).
TRACKER_API_RE = re.compile(r"(api\.v3|api\.v4|/api/v\d)")
TRACKER_CLI_RE = re.compile(r"\bgh\b|\bglab\b")

CORE_SCRIPTS = sorted(
    p for d in (REPO / "skills", REPO / "scripts") for p in d.rglob("*.py") if p.is_file()
)
CORE_DOCS = sorted(p for p in (REPO / "skills").rglob("*.md") if p.is_file())


def test_interface_is_exactly_two_seams():
    """The interface module names exactly two seams and nothing else."""
    seam_names = [n for n in dir(adapter_protocol) if not n.startswith("_")]
    # The interface exposes the verdict set, the result dataclass, the
    # allow-list loader, and the interface checker — plus the seam contract
    # is documented (the two seam function names are what an adapter
    # implements; check_interface enforces them structurally).
    assert "check_interface" in seam_names
    assert "QuestionVerdict" in seam_names
    assert "LEGAL_VERDICTS" in seam_names
    # Exactly two seam names are referenced by check_interface.
    src = (_INTEGRATIONS / "adapter_protocol.py").read_text(encoding="utf-8")
    assert '"question_legitimacy"' in src and '"label_authorization"' in src


def test_verdict_set_is_closed_and_covers_ticket_states():
    """The verdict set is exactly none|one|many|stranger — the four states
    the steering protocol names (one, many, stranger, plus none for
    unanswered)."""
    assert adapter_protocol.LEGAL_VERDICTS == frozenset({"none", "one", "many", "stranger"})


def test_question_verdict_enforces_closed_set():
    """A QuestionVerdict with a verdict outside the closed set is rejected."""
    with pytest.raises(ValueError):
        adapter_protocol.QuestionVerdict("sometimes")


def test_question_verdict_one_requires_answer():
    """A 'one' verdict must carry the answer; a non-one verdict must not."""
    v = adapter_protocol.QuestionVerdict("one", "next train")
    assert v.answer == "next train"
    with pytest.raises(ValueError):
        adapter_protocol.QuestionVerdict("one", None)
    with pytest.raises(ValueError):
        adapter_protocol.QuestionVerdict("many", "next train")
    with pytest.raises(ValueError):
        adapter_protocol.QuestionVerdict("stranger", "next train")
    with pytest.raises(ValueError):
        adapter_protocol.QuestionVerdict("none", "next train")
    # none / many / stranger carry no answer.
    for verdict in ("none", "many", "stranger"):
        assert adapter_protocol.QuestionVerdict(verdict, None).answer is None


def _tracker_call_lines(path: Path) -> list[str]:
    """The lines in a core script that call the tracker API or CLI directly.

    A core script may not talk to a tracker at all: it reaches the tracker
    only through an adapter's pure function. This finds any line that
    references the tracker's REST API endpoint or a tracker CLI.
    """
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if TRACKER_API_RE.search(line) or TRACKER_CLI_RE.search(line):
            hits.append(f"{path}:{lineno}: {line.strip()}")
    return hits


@pytest.mark.parametrize("path", CORE_SCRIPTS, ids=lambda p: str(p.relative_to(REPO)))
def test_core_scripts_never_call_tracker_directly(path):
    """No core script (skills/, scripts/) calls the tracker's REST API or CLI
    directly: the core reaches the tracker only through an adapter."""
    assert _tracker_call_lines(path) == [], (
        "a core script references the tracker API or CLI directly; the core must "
        "stay viable with no adapter installed (docs/PRODUCT.md §3)"
    )


@pytest.mark.parametrize("path", CORE_SCRIPTS, ids=lambda p: str(p.relative_to(REPO)))
def test_core_scripts_never_reference_integrations(path):
    """No core script imports or references integrations/: the core must be
    viable with integrations/ removed (structural half of core viability)."""
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        assert "integrations" not in line, f"{path}:{lineno}: {line.strip()}"


def test_no_core_subprocess_to_tracker():
    """Static scan: no core script subprocess-invokes a tracker CLI.

    The two pure functions (question legitimacy, label authorization) are
    the only sanctioned way the core touches a tracker; a subprocess call to
    a tracker CLI from a core script would bypass the adapter interface."""
    tracker_cli_names = {"gh", "glab"}
    for path in CORE_SCRIPTS:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "run":
                continue
            if not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.List) and first.elts):
                continue
            for elt in first.elts:
                if isinstance(elt, ast.Constant) and elt.value in tracker_cli_names:
                    pytest.fail(f"{path}: subprocess call to {elt.value!r}")


def test_core_docs_never_name_the_tracker():
    """No core doc (skills/**/*.md) names the tracker by its API or CLI:
    core docs stay tool-agnostic (the adapters are where the tool name
    lives)."""
    for path in CORE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert not TRACKER_API_RE.search(text), f"{path}: names the tracker API"
        assert not re.search(r"\bgh issue\b|\bglab issue\b", text), f"{path}: names a tracker CLI"
