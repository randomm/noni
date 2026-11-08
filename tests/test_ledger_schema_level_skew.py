"""The writer's side of the ledger schema level: a run refuses before it outruns its census.

The drift: a project pins one noni commit for its CI census and runs a newer one
locally. On the day the newer writer emits a field the pinned census does not
declare, the record commits cleanly and the census then refuses it at exit 10 -- in
CI, hours later. The fix is one integer and one committed file:
:data:`noni.ledger_level.LEDGER_SCHEMA_LEVEL` on the writer's side, and
``noni/direction/census-level.json`` holding ``{"schema_level": N}`` on the project's.

This file is the writer's half of that pair, driven through the real subprocess
entry point in ``tests/decide_fixtures``: what a run does with the declaration it
finds, which exit code each answer takes, and what the tree looks like afterwards.
The census's half -- the row that reports an undeclared field -- is
``tests/test_ledger_schema_level_census.py``, and the trees both are run over are in
``tests/ledger_level_fixtures``.

Three shapes, each of which failed before the change:

* **skew** -- a writer above the declared level refuses with exit 4 and names both
  levels and the fix in both directions;
* **malformed** -- a declaration that answers nothing stops the writer with exit 2
  rather than being read as "nothing declared", because a file the run cannot read
  says nothing about the census it was meant to describe;
* **admitted** -- a writer at or above the declared level writes, which is the
  control that keeps the check from being a refusal of every run.

Runs are offline and deterministic: the trees are built with the harness's own git
helpers, and a run that must be observed rather than only heard goes in-process,
where a function can be spy'd.
"""

from __future__ import annotations

import contextlib
import io
import json
import os

import pytest
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_ID,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _decide,
    _decide_module,
    _pin_identity,
    _porcelain,
    _record_path,
)
from ledger_level_fixtures import (
    _bare_repo,
    _census_verdicts_for,
    _older_level,
    _plant_declaration,
    _writer_level,
)

from noni import ledger_level


def _declaration(level: int) -> str:
    """The one document the reader accepts, for a given level.

    Built from the module's own key rather than spelled out, so a test cannot pass
    against a key the product no longer reads.
    """
    return json.dumps({ledger_level.SCHEMA_LEVEL_KEY: level}) + "\n"


# --- the refusal ------------------------------------------------------------

def test_a_writer_newer_than_the_declared_level_refuses_before_it_writes(tmp_path):
    """AC1, the writer half: skew is refused at the write, naming both levels.

    This failed first as exit 0: the record committed, and the only sign of the
    drift was a red census hours later. Exit 4 is this writer's own code for "the
    ledger this run would write is one its arbiter refuses", so no new code is
    introduced and the writer's documented code table is unchanged.
    """
    repo = _baseline_repo(tmp_path)
    _plant_declaration(repo, _declaration(_older_level()))
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    out = proc.stdout + proc.stderr
    assert str(_writer_level()) in out and str(_older_level()) in out, (
        f"the refusal must name both levels: {out}")
    assert ledger_level.SCHEMA_LEVEL_FILE in out, (
        f"the refusal must name the file that declares the level: {out}")
    assert "census pin" in out and "upgrade" in out, (
        f"the refusal must name the fix in both directions: {out}")
    assert not _record_path(repo, NEW_ID).exists(), "a refused run wrote a record"
    assert _porcelain(repo) == "", f"a refused run dirtied the tree: {_porcelain(repo)}"


def test_a_supersede_is_refused_by_the_same_check(tmp_path):
    """The refusal covers a supersede too, and leaves the target's bytes alone.

    A supersede writes two files, one of them an existing record whose status flips,
    so a check that sat on the new record's path alone would let an older-census
    write through on this route.
    """
    repo = _baseline_repo(tmp_path)
    _plant_declaration(repo, _declaration(_older_level()))
    target = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    before = target.read_bytes()
    proc = _decide(repo, *ANSWERED, "--supersedes", BASELINE_ID)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert target.read_bytes() == before, "a refused supersede rewrote the target"
    assert _porcelain(repo) == "", _porcelain(repo)


def test_the_level_check_asks_before_the_target_is_read(tmp_path):
    """Where the check sits in the run, asserted rather than trusted to a comment.

    A supersede is the only route that reads a target, so if the level question
    slipped below it, a run whose census is older would read (and then be free to
    rewrite) the record the pinned census would refuse. The witness is the writer's
    own target seam: the run must refuse with exit 4 without ever asking it.

    In-process, because a subprocess cannot spy a function. The witness raises rather
    than answering, so a run that reached the target would be heard as a traceback
    and not as a green test; the assertion of the refusal is the assertion that the
    witness never spoke.
    """
    repo = _baseline_repo(tmp_path)
    _plant_declaration(repo, _declaration(_older_level()))
    asked: list[str] = []
    writer = _decide_module()
    original = writer._load_target

    def _witness(repos, ledger, target_id):
        asked.append(target_id)
        raise AssertionError(f"the target {target_id} was read despite the skew")

    writer._load_target = _witness
    _pin_identity(repo, "Replay")
    argv = ["--repo", str(repo), "--no-commit", "--slug", "witness", "--date",
            BASELINE_ID[:10], *BASE, *QUESTION, *OPTIONS, *ANSWERED,
            "--supersedes", BASELINE_ID]
    saved = os.environ.pop(writer.FAIL_COMMIT_ENV_VAR, None)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = writer.main(argv)
    finally:
        writer._load_target = original
        if saved is not None:
            os.environ[writer.FAIL_COMMIT_ENV_VAR] = saved
    assert code == 4, f"{code}: {out.getvalue()}{err.getvalue()}"
    assert asked == [], f"a refused run still read the target: {asked}"


def test_a_refused_run_never_creates_the_tree_it_was_refused_for(tmp_path):
    """The check is asked ahead of the allocation, not beside the write.

    The same ordering rule the state-root check follows, and the reason both live in
    one module: a refused run that had already mkdir'd ``noni/decisions`` would leave
    a code repository holding empty noni state, which is the wrong-path artifact
    docs/PRODUCT.md 7 refuses in the first place.
    """
    repo = _bare_repo(tmp_path, "refuse-creates")
    _plant_declaration(repo, "not json\n")
    proc = _decide(repo, "--no-commit", "--slug", "probe", *ANSWERED)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert not (repo / "noni" / "decisions").exists(), (
        "a refused run created the ledger directory it was refused for")


def test_the_writer_never_creates_the_declaration(tmp_path):
    """The writer reads the declaration and never makes it.

    The file is the census-pinner's statement about their own census. A writer that
    wrote it would be asserting a level its author never declared, and would hand a
    refused run a half-truth on disk to be read as a declaration next time.
    """
    repo = _baseline_repo(tmp_path)
    assert not (repo / ledger_level.SCHEMA_LEVEL_REL).exists()
    assert _decide(repo, *ANSWERED).returncode == 0
    assert not (repo / ledger_level.SCHEMA_LEVEL_REL).exists(), (
        "the writer wrote the project's declaration")
    assert _porcelain(repo) == "", _porcelain(repo)


# --- the fail-closed answer -------------------------------------------------

@pytest.mark.parametrize("body", [
    "not json at all\n", "{\n", "[]\n", "{}\n", '"a string"\n', "null\n", "5\n",
    '{"schema_level": null}\n', '{"schema_level": -3}\n',
    '{"schema_level": true}\n', '{"schema_level": "1"}\n',
    '{"schema_level": 1.5}\n', '{"schema_level": 1e9}\n',
])
def test_a_malformed_declaration_fails_closed_at_the_writer(tmp_path, body):
    """AC3: a declaration that answers nothing stops the write with exit 2.

    Thirteen shapes that are none of them "no declaration": bytes that are not JSON,
    a document that is not an object, a missing ``schema_level``, and a value that is
    not an integer at or above the floor the module declares -- including ``true``,
    which Python calls an ``int``, and ``1e9``, which it calls a ``float``. Each is
    refused rather than read as silence, because a file the run cannot read says
    nothing about the census it was meant to describe, and writing into that
    uncertainty is the silent drift the check exists to close. ``0`` is deliberately
    absent from this list: it is the level of a census predating the first declared
    set, which is a readable answer and takes the skew code, not the usage code.
    """
    repo = _baseline_repo(tmp_path, f"bad-{abs(hash(body))}")
    _plant_declaration(repo, body)
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 2, (
        f"{body!r}: expected the usage code, got {proc.returncode}: {proc.stderr}")
    assert ledger_level.SCHEMA_LEVEL_FILE in proc.stderr, (
        f"{body!r}: the refusal must name the file: {proc.stderr}")
    assert not _record_path(repo, NEW_ID).exists(), f"{body!r}: a record landed"
    assert _porcelain(repo) == "", f"{body!r}: {_porcelain(repo)}"


# --- the admitted cases -----------------------------------------------------

def test_a_writer_at_or_above_the_declared_level_writes(tmp_path):
    """The control that keeps the check from being a refusal of every run.

    Two levels, both admitted: the one the writer itself declares (the pair in step,
    which is the practice the descriptor records), and one above it (a project whose
    census is newer than its writer, which is not this drift). The record lands and
    both census entry points call the ledger clean.
    """
    for label, declared in (("equal", _writer_level()), ("newer", _writer_level() + 3)):
        repo = _baseline_repo(tmp_path, f"level-{label}")
        _plant_declaration(repo, _declaration(declared))
        proc = _decide(repo, *ANSWERED)
        assert proc.returncode == 0, f"{label}: {proc.returncode}: {proc.stderr}"
        assert _record_path(repo, NEW_ID).is_file(), f"{label}: no record landed"
        landed = json.loads(_record_path(repo, NEW_ID).read_text(encoding="utf-8"))
        verdicts = _census_verdicts_for(tmp_path / f"clean-{label}", landed,
                                        subdir=label)
        for name, (code, out) in verdicts.items():
            assert code == 0, f"{label} via {name}: expected 0, got {code}\n{out}"


def test_a_project_with_no_declaration_writes_exactly_as_before(tmp_path):
    """AC2, the writer half: no declaration file, and the run behaves as it always did.

    The ordinary attached project, which is the common case and the one a fail-closed
    check most easily breaks. The record lands at exit 0 and nothing about the tree
    or the census report mentions a level: no cause clause, no schema-level wording,
    no refusal. The census half of the same claim -- the ``not_evaluated`` list and
    the absence of a new row -- is in
    ``tests/test_ledger_schema_level_census.py``.
    """
    repo = _baseline_repo(tmp_path)
    assert not (repo / ledger_level.SCHEMA_LEVEL_REL).exists()
    proc = _decide(repo, *ANSWERED)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert _record_path(repo, NEW_ID).is_file(), "no record landed"
    combined = proc.stdout + proc.stderr
    for phrase in ("unknown field", "census pin", ledger_level.SCHEMA_LEVEL_FILE,
                   ledger_level.SCHEMA_LEVEL_KEY):
        assert phrase not in combined, f"a new phrase appeared: {phrase!r}: {combined}"
