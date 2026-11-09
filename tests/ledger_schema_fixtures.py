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

from noni import ledger_schema

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

# The field a record carries when the point is that a census older than the writer
# does not declare it: what a newer writer emits and a pinned census then refuses.
# Not in the closed set, by design -- see ``tests/test_ledger_schema_level_skew.py``.
SKEW_FIELD = "decided_by_next_era"

# The rationale field, and its bound, both read from the product rather than spelled
# here: the three modules that drive a ``why`` through the censuses ask the schema for
# the key and :func:`noni.itemschema.WHY_MAX` for the number, so a bound that moves
# reddens them instead of certifying a shape nothing enforces any more. The key is
# reached through the ledger's own module and not the item store's, because the ledger
# census is the arbiter these tests are asking.
WHY_FIELD = ledger_schema.WHY_FIELD
WHY_MAX = ledger_schema.why_max()

# Each of the three separators json escapes and ``str.splitlines`` breaks a line on,
# and each of the three json writes into the bytes unescaped. Shared because the name
# rule, the marker rule and the rationale rule all refuse the same ten characters: a
# ``why`` carrying one is one JSON string and two lines, which is what the single-line
# rule was written for.
FILE_GROUP_RECORD = ("\x1c", "\x1d", "\x1e")
RAW_SEPARATORS = ("\x85", "\u2028", "\u2029")
# A value made of nothing but a character the blank rule refuses, and one ordinary
# value that must stay accepted: the positive control of every shape table here.
BLANK_WHY = "   "
# The committed fixture's own reason, so the fixture and the in-process cases read
# one value rather than each keeping a copy of a sentence.
ORDINARY_WHY = "the train leaves at six and nothing else is ready"


def why_over_bound(char: str = "a") -> str:
    """A rationale one code point past the bound the product states, in ``char``.

    A function and not a constant so the bound is read at the moment the caller asks:
    a module-level ``"a" * (WHY_MAX + 1)`` would be a copy of the number taken at
    import time, which is the thing these fixtures exist to stop.
    """
    return char * (WHY_MAX + 1)


def why_at_bound(char: str = "a") -> str:
    """A rationale of exactly the bound: the longest value both sides must accept."""
    return char * WHY_MAX


def product_why_max() -> int:
    """The rationale bound as the product states it, read at the moment of the call.

    The one spelling of the number any test may compare against. A module constant is
    taken at import time, so a suite that imported it kept a copy of its own -- and a
    copy is what the acceptance criterion for issue #122 refuses: the day the bound
    moves, every module holding one fails to notice. This reads
    :data:`noni.itemschema.WHY_MAX` through the package, which is the route the writer,
    the ledger census and the ordering arbiter all take.
    """
    from noni.itemschema import WHY_MAX as owner

    return owner


def arbiter_why_max() -> int:
    """The ordering arbiter's own copy of the bound, read from the loaded module.

    ``census_ordering`` is loaded by path and imports nothing from the writer's package,
    so it holds the number as a module constant on purpose (see its comment). That copy
    is the one legitimate second spelling in the product, and the only way to hold it to
    the owner is to read it back and compare -- which is what the suites driving the
    shared shape table do.
    """
    from harness_module import load_package_module

    return load_package_module("census_ordering").WHY_MAX


def _with_skew_field(record: dict, value: str = "future-writer") -> dict:
    """``record`` plus one field no census at an older level declares.

    The shape a writer ahead of its pinned census produces: same eight fields, one
    extra key. It is the fixture side of the drift, so the census half of the
    contract (the row that names the cause) and the writer half (the refusal before
    the write) are asked about one and the same record.
    """
    record[SKEW_FIELD] = value
    return record


def isolated_python_stub(tmp_path: Path, name: str) -> Path:
    """A ``python3`` that cannot import ``noni``, on a PATH of its own.

    The wrapper resolves its interpreter with ``command -v``, so PATH must still
    hold a real program, and a package installed into the venv is reached by a
    ``.pth`` in that venv's ``site-packages`` -- which no ``PYTHONPATH`` can
    hide. So the interpreter the caller names is a *script* that starts the real
    one ``-S -I`` (no ``site``, hence no ``.pth``, no ``site-packages``, no
    ``PYTHONPATH``): a process with neither route to the package, which is the
    half-installed machine the wrapper must refuse rather than trace.
    """
    python = Path(sys.executable)
    fake_bin = tmp_path / name / "isolated-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    stub = fake_bin / "isolated-python"
    stub.write_text("#!/bin/sh\nexec " + str(python) + " -S -I \"$@\"\n",
                    encoding="utf-8")
    stub.chmod(0o755)
    return stub


def no_package_env(tmp_path: Path, name: str) -> dict:
    """An env for a machine whose interpreter cannot import ``noni``.

    The guard is the point: it proves the premise before the caller asserts the
    refusal, so an exit-3 assertion cannot pass by accident on a host where the
    package hides somewhere else.
    """
    stub = isolated_python_stub(tmp_path, name)
    empty_site = tmp_path / name / "empty-site"
    empty_site.mkdir(parents=True, exist_ok=True)
    env = subprocess_env({
        "HOME": str(tmp_path),
        "NONI_PYTHON": str(stub),
        "PYTHONPATH": str(empty_site),
    })
    probe = subprocess.run([str(stub), "-c", "import noni.census_wrapper"],
                           capture_output=True, text=True, env=env, timeout=60)
    assert probe.returncode != 0, (
        "the fixture did not make the package unimportable, so the exit-3 "
        f"assertions below prove nothing: {probe.stdout}{probe.stderr}")
    return env


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
