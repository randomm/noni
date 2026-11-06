"""The shared drivers for the ledger schema's cross-entry-point tests.

Two entry points read one schema — ``decide.py``'s flag checks and the unified
census's record pass — and the shell ledger shim is the census run over the
ledger group, so a test that drives the shim and a test that drives the census
ask the same arbiter the long way round and the short way round. The tests that
pin them are split by subject -- the closed key set in
``tests/test_ledger_closed_key_set.py``, the name and marker rules through every
entry point in ``tests/test_ledger_name_and_marker_rules.py`` -- and all of them
drive the same censuses over the same one-record ledger, so the launchers and the
assertions every one of them makes live here.

There used to be a third reader: a jq program beside ``census.sh`` that
re-implemented these rules in a second language. It is gone, and so is the
parity suite that compared its literals against ``ledger_schema`` — one arbiter
has nothing to be parallel to. What remains of that suite is behavioural: the
fixtures each entry point must refuse, and the words each refusal must name.

A helper module, never named ``test_*``: pytest must not collect it as tests.
Its shape follows the other fixture modules in ``tests/`` (``decide_fixtures``,
``census_ledger_fixtures``), which exist for the same reason -- two test files
sharing one definition rather than each keeping a copy that can drift.

Every census run here goes through ``subprocess_env()``: that is what puts this
tree's ``src/`` first on the child's ``sys.path`` (so the child exercises the
tree these tests assert against, not an editable install of another checkout)
and what enables the subprocess half of the coverage gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import REPO, subprocess_env

FIXTURES = REPO / "tests" / "fixtures"
CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
CENSUS_PY = REPO / "skills" / "census" / "scripts" / "census.py"

# Every --now in these modules is pinned: the ledger-empty class reads the clock,
# so a fixture run must not depend on the host's date.
NOW = "2026-10-04T12:00:00Z"

# fixture name -> the junk keys that fixture carries, in the order they appear.
# The counts are the point: 9, 10, 11 and 12 keys, each carrying a key the schema
# does not declare. The count rule the deleted jq program used accepted 10, 11
# and 12 keys outright, and accepted a junk key at 9 beside a real optional
# field; the set test that replaced it refuses all four.
JUNK_FIXTURES: dict[str, list[str]] = {
    "decision-invalid-unknown-keys-nine.json": ["junk"],
    "decision-invalid-unknown-keys-ten.json": ["junk"],
    "decision-invalid-unknown-keys-eleven.json": ["junk", "junk_two"],
    "decision-invalid-unknown-keys-twelve.json": ["junk_a", "junk_b", "junk_c"],
}

# The key count each fixture above must hold. Spelled out rather than derived
# from the loop position: the count IS the regression, so a fixture that drifted
# to another count would stop proving the case it exists for.
EXPECTED_KEYS = {name: 9 + index for index, name in enumerate(JUNK_FIXTURES)}

# The baseline record every planted shape starts from: the fixture's own eight
# fields, copied so a test can add one field and ask about that one field.
BASELINE_FIXTURE = "decision-valid.json"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _baseline() -> dict:
    """A fresh copy of the schema-valid baseline record."""
    return _fixture(BASELINE_FIXTURE)


def _ledger(tmp_path: Path, record: dict) -> Path:
    """A ledger directory holding one record, its bytes on disk verbatim.

    Not a git tree: these fixtures ask the schema question only, and a ledger
    outside git makes the attribution and post-commit-edit checks skip rather
    than answer for a state this fixture did not plant.
    """
    ledger = tmp_path / "decisions"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "one-record.json").write_text(json.dumps(record, indent=2) + "\n",
                                            encoding="utf-8")
    return ledger


def _run_sh(ledger: Path) -> tuple[int, str]:
    """The shell ledger shim over ``ledger``: the census, through the wrapper.

    The wrapper passes every option through, so the run below and ``_run_py``
    differ only in how they reach the census, not in what they ask it.
    """
    proc = subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _run_py(ledger: Path) -> tuple[int, str]:
    """The unified census over the same directory, ledger group only.

    ``--only`` keeps the verdict about the record and nothing else: hygiene has
    no deny-list to read here and ordering has no issue state, and neither is
    this fixture's question.
    """
    argv = [sys.executable, str(CENSUS_PY), "--ledger", str(ledger), "--now", NOW,
            "--only", "ledger-record", "--only", "ledger-empty"]
    proc = subprocess.run(argv, capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _census_verdicts(tmp_path: Path, record: dict,
                     subdir: str = "ledger") -> dict[str, tuple[int, str]]:
    """Each entry point's (code, output) over a ledger holding ``record``.

    One directory per call, named by ``subdir``, so a loop over shapes does not
    read the previous shape's record.
    """
    ledger = _ledger(tmp_path / subdir, record)
    sh_code, sh_out = _run_sh(ledger)
    py_code, py_out = _run_py(ledger)
    return {"census.sh": (sh_code, sh_out), "census.py": (py_code, py_out)}


def _assert_both_refuse(tmp_path: Path, record: dict, phrase: str, label: str,
                        *, subdir: str = "refuse") -> dict[str, tuple[int, str]]:
    """Both entry points answer 10 on ``record``, and name ``phrase``.

    The phrase is asserted as well as the code: an exit 10 raised for some other
    fault in the same record would otherwise certify the rule that is under test
    while refusing for an unrelated reason.
    """
    verdicts = _census_verdicts(tmp_path, record, subdir=subdir)
    for name, (code, out) in verdicts.items():
        assert code == 10, f"{label} via {name}: expected 10, got {code}\n{out}"
        assert phrase in out, f"{label} via {name}: the row must name the fault: {out}"
    return verdicts


def _assert_both_clean(tmp_path: Path, record: dict, label: str,
                       *, subdir: str = "clean") -> dict[str, tuple[int, str]]:
    """Both entry points answer 0 on ``record``.

    The control side of every refusal asserted beside it: without a positive case
    a schema tightened until nothing passed would keep the refusals green while
    refusing the records the writer itself writes.
    """
    verdicts = _census_verdicts(tmp_path, record, subdir=subdir)
    for name, (code, out) in verdicts.items():
        assert code == 0, f"{label} via {name}: expected 0, got {code}\n{out}"
    return verdicts
