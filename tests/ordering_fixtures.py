"""Shared builders for the census's ordering group tests.

A fixture repo with a ledger and an ordering artifact, the runners that drive the
census for it, and the fault injectors that break one group's read of the ledger
alone. Held in a non-test module so the six ordering test files build the same repo
and pytest never collects the builders as tests. Copied verbatim from
``tests/test_census_ordering.py``, whose tests now live in the six
``tests/test_census_ordering_*.py`` files.

The shape tables are deliberately not here: ``tests/ordering_shapes.py`` is read by
the writer's suite too, so it stays where both sides can see it.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

from _harness import REPO, SRC, _git, _init_repo, git_pin_date, subprocess_env

BASELINE_ID = "2026-10-01-baseline"

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

FRESH = "2026-10-26T00:00:00Z"

NOW = "2026-10-27T12:00:00Z"

ORDERING_CLASSES = ("ordering-malformed", "ordering-stale", "ordering-closed")

ORDER_REL = "noni/direction/order.json"

SCRIPTS = SRC / "noni"

def _canonical(entries: list[dict]) -> str:
    return json.dumps({"schema": "noni.order/1", "entries": entries}, indent=2) + "\n"

def _many_huge_fields() -> str:
    """A well-formed entry that also carries ten unknown fields with huge names.

    The join of the per-entry complaints is where an unbounded row is easiest to
    reach: one problem per unknown field, each naming a value read from the file.
    """
    junk = ", ".join(f'"{"f" * 300}{index}": 1' for index in range(10))
    return ('{"schema": "noni.order/1", "entries": [{"issue": 7, "decision": null, '
            '"confirmed": "' + FRESH + '", ' + junk + "}]}")

def _entry(issue: int, decision: str | None = None, confirmed: str = FRESH) -> dict:
    return {"issue": issue, "decision": decision, "confirmed": confirmed}

def _repo(tmp_path: Path, subdir: str = "repo", records: bool = True) -> Path:
    """A throwaway tree, optionally holding one committed decided record.

    The record exists so a ``decision`` citation can be answerable: the census
    looks an id up by its filename stem, and a test that cites one against an
    empty ledger is testing the missing-record path, not the one it named.
    """
    repo = _init_repo(tmp_path / subdir)
    if records:
        record = {
            "id": BASELINE_ID, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
            "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"], "answer": "a"}],
            "by": "Replay", "scope": "release ordering", "status": "decided",
            "supersedes": None,
        }
        _commit(repo, f"noni/decisions/{BASELINE_ID}.json",
                json.dumps(record, indent=2) + "\n", "2026-10-01T00:00:00Z")
    return repo

def _commit(repo: Path, rel: str, body: str, date: str = NOW) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", f"direction: {rel}")

def _order(repo: Path, body: str, commit: bool = True) -> None:
    if commit:
        _commit(repo, ORDER_REL, body)
        return
    target = repo / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")

def _seed(repo: Path, *entries: dict) -> None:
    _order(repo, _canonical([dict(e) for e in entries]))

ORDERING_CLASSES = ("ordering-malformed", "ordering-stale", "ordering-closed")

def _only_args(extra: tuple[str, ...]) -> list[str]:
    """The argv fragment the run is launched with: every --only/--skip the caller
    named (so a filtering test filters), plus the whole ordering group when the
    caller named no --only at all, plus the caller's remaining flags.

    One pass over ``extra``: a value that belongs to --only or --skip is consumed
    with its flag and never re-added, so the names appear exactly once whoever
    named them. A caller that named only --skip values still gets the group's
    --only set: the helper's job is to confine the run to the ordering group, and
    a bare --skip would otherwise let the ledger, session and hygiene classes in
    beside it.
    """
    args: list[str] = []
    named: list[str] = []
    index = 0
    while index < len(extra):
        arg = extra[index]
        if arg in ("--only", "--skip") and index + 1 < len(extra):
            value = extra[index + 1]
            if arg == "--only":
                named.append(value)
            args += [arg, value]
            index += 2
            continue
        args.append(arg)
        index += 1
    if not named:
        for check in ORDERING_CLASSES:
            args += ["--only", check]
    return args

def _run(repo: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the ordering group only, as NDJSON plus raw streams."""
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--json", "--now", NOW]
    args += _only_args(extra)
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, [r for r in rows if r.get("kind") == "finding"], \
        proc.stdout, proc.stderr

def _code(repo: Path, *extra: str) -> int:
    """The exit code of a run used only as a precondition (root can read a
    000-mode file, where the unreadable-record fault cannot be produced)."""
    return _run(repo, *extra)[0]

def _human(repo: Path, *extra: str) -> tuple[int, str, str]:
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--now", NOW]
    args += _only_args(extra)
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    return proc.returncode, proc.stdout, proc.stderr

@contextlib.contextmanager
def _listing_faults(ledger: Path, text: str = "input/output error"):
    """Make the ORDERING GROUP'S read of ``ledger`` fault for the block.

    Two seams, because the group now reads the ledger through the run's one
    listing and a fault has to reach both halves of a run that does not have one:

    - ``census_ordering.check_ordering`` is patched to hand the readers ``None``
      for ``names``, which is what asks the readers to read the directory
      themselves (the census normally hands them the probe's names, so without
      this the group's read would not exist to fault);
    - ``census_ordering_readers.listing_helper`` is the name that read then
      calls, patched to raise for ``ledger``.

    Patching ``Path.iterdir`` instead would fault every listing of the run at
    once, so the ledger group would report the very same fault with a
    whole-artifact row of its own that survives every ``--only``/``--skip`` set
    (the probe-honesty rule in ``keep``), and no assertion of this file's group
    could name a row of its own without also naming that one. Faulting this
    group's read alone is what lets each test here pin this group's rows
    exactly. The ledger group's own half of the same fault is pinned by
    ``test_an_unlistable_ledger_is_reported_by_the_ledger_group_too``, which
    patches ``Path.iterdir`` instead (same file, below), and by
    ``test_probe_reads_the_ledger_through_the_helper_not_glob`` in
    ``tests/test_census_ledger_probe_states.py`` and
    ``test_the_run_lists_the_ledger_once`` in
    ``tests/test_census_ledger_reads_once.py``.

    The fault is raised as a bare ``OSError(text)``: that is the shape whose
    text the census must render without leaking a path, and the probe carries
    whatever the fault's ``str()`` holds (see
    ``test_probe_records_listing_fault_text_on_the_probe`` in
    ``tests/test_census_ledger_probe_states.py``).

    Used with ``_run_in_process``, not with ``_run``: the census runs as a
    subprocess there, and a patch of this interpreter cannot reach it.
    """
    ordering = importlib.import_module("noni.census_ordering")
    readers = importlib.import_module("noni.census_ordering_readers")
    real_check = ordering.check_ordering
    real_helper = readers.listing_helper
    target = Path(ledger)

    def check_without_names(*args, **kwargs):
        # Ask the group to read the ledger for itself, so the read below exists
        # to fault (see ``names`` on ``check_ordering``).
        kwargs["names"] = None
        return real_check(*args, **kwargs)

    def boom(path):
        if Path(path) == target:
            raise OSError(text)
        return real_helper(path)

    ordering.check_ordering = check_without_names
    readers.listing_helper = boom
    try:
        yield
    finally:
        ordering.check_ordering = real_check
        readers.listing_helper = real_helper

@contextlib.contextmanager
def _ordering_record_read_faults(ledger: Path, text: str = "input/output error"):
    """The same fault as ``_listing_faults``, without the ``names`` override.

    For the test that pins the wiring of the run's one listing: it faults the
    readers' own ``listing_helper`` and leaves the census's names in place, so a
    run that still reached that helper for a group the probe already read fails
    there rather than passing on the probe's names. Kept separate from
    ``_listing_faults`` precisely so that test cannot be satisfied by the seam
    the other tests rely on.
    """
    readers = importlib.import_module("noni.census_ordering_readers")
    real_helper = readers.listing_helper
    target = Path(ledger)

    def boom(path):
        if Path(path) == target:
            raise OSError(text)
        return real_helper(path)

    readers.listing_helper = boom
    try:
        yield
    finally:
        readers.listing_helper = real_helper

@contextlib.contextmanager
def _listing_faults_all_reads(ledger: Path, text: str = "input/output error"):
    """Make EVERY ledger listing of the run fault, for the duration of the block.

    The seam is ``Path.iterdir``, the call every reader of the ledger ends at
    (``census_ledger.listing_helper`` uses ``iterdir`` precisely because ``glob``
    swallows the ``OSError`` a readdir raises and yields nothing). Unlike
    ``_listing_faults``, which faults the ordering group's read alone, this
    reaches the probe, the record pass and the ordering readers at once: it is
    the seam for the tests that pin what the whole run says about one fault.

    Used with ``_run_in_process``, not with ``_run``: the census runs as a
    subprocess there, and a patch of this interpreter cannot reach it.
    """
    real_iterdir = Path.iterdir
    target = Path(ledger)

    def boom(self):
        if self == target:
            raise OSError(text)
        return real_iterdir(self)

    Path.iterdir = boom
    try:
        yield
    finally:
        Path.iterdir = real_iterdir

def _run_in_process(repo: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the ordering group only, driven in this interpreter.

    The file's other runners launch a subprocess, which is what the coverage gate
    measures and what every behavioural test here uses. This one calls
    ``census.main`` directly so a test can reach a fault inside the interpreter --
    a listing that raises -- that no file permission can plant. The argument set
    is built exactly as ``_run`` builds it, so the two differ in one thing only:
    whether the census runs here or there.
    """
    import census

    argv = ["--repo", str(repo), "--json", "--now", NOW]
    argv += _only_args(extra)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(sys.stderr):
        code = census.main(argv)
    rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    return code, [r for r in rows if r.get("kind") == "finding"], buffer.getvalue(), ""

def _ordering_host_faults() -> list[tuple[OSError, tuple[str, ...]]]:
    """The faults whose filename the scrubber keeps losing, and their parts.

    Built at runtime, never literals: a tracked file carrying one of these paths
    would trip the census's own hygiene class. A non-ASCII component with a space
    in it, and the bare home of a service account -- the two shapes the path arms
    of ``census_text._stripped`` cannot be relied on to catch, which is why the
    row is built without the filename rather than scrubbed after it.
    """
    return [
        (OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/"),
         ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir")),
        (OSError(13, "Permission denied", "~deploy"), ("deploy",)),
    ]


@contextlib.contextmanager
def _listing_fault(ledger: Path, fault: OSError):
    """Fault the ordering group's read of ``ledger`` with one given exception.

    ``_listing_faults`` raises a bare ``OSError(text)``, which is the shape every
    other test here wants. This one takes the exception itself, for the test that
    needs the filename a real fault carries.
    """
    ordering = importlib.import_module("noni.census_ordering")
    readers = importlib.import_module("noni.census_ordering_readers")
    real_check = ordering.check_ordering
    real_helper = readers.listing_helper
    target = Path(ledger)

    def check_without_names(*args, **kwargs):
        kwargs["names"] = None
        return real_check(*args, **kwargs)

    def boom(path):
        if Path(path) == target:
            raise fault
        return real_helper(path)

    ordering.check_ordering = check_without_names
    readers.listing_helper = boom
    try:
        yield
    finally:
        ordering.check_ordering = real_check
        readers.listing_helper = real_helper

def _state(repo: Path, mapping: dict[str, str]) -> str:
    path = repo / "issue-state.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return str(path)


def _strict_reader_copy(name: str, filename: str):
    """One module of the strict-reading pair, loaded by path from its own dir.

    The census's reader and the writer's reader are two copies of the same four
    refusals, and each side's suite has traditionally tested its own. Loading
    them by path here lets one assertion cover both without either test file
    importing the other side's package name.
    """
    spec = importlib.util.spec_from_file_location(f"noni_strict_copy_{name}",
                                                  SCRIPTS / filename)
    if spec is None or spec.loader is None:  # pragma: no cover - the path is fixed
        raise AssertionError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
