"""Shared builders for the ledger probe's tests.

The kind functions answer ``file_kind``-shaped questions about a path the test
planted, ``_fault_iterdir`` makes a readdir raise (the probe's own read, pinned by
``test_probe_reads_the_ledger_through_the_helper_not_glob`` in
``tests/test_census_ledger_probe_states.py`` and the whole-run version by
``test_the_run_lists_the_ledger_once`` in
``tests/test_census_ledger_reads_once.py``), ``_is_census_written_path`` is the
reduction the scrub rule is stated as, and ``_rows``/``_code`` drive the census for a
fixture repo.

Held in a non-test module so the five probe test files share one definition and
pytest never collects the builders as tests. Copied verbatim from
``tests/test_census_ledger_probe.py``, whose probe-state tests now live in
``tests/test_census_ledger_probe_states.py``.
"""

from __future__ import annotations

from pathlib import Path

import census_ledger


def _kind_dir_ok(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """A classifier that answers "regular" for everything, so these tests turn
    on the listing alone and not on a stat the census's own classifier does."""
    return "regular", None

def _kind_absent(path: Path, kind: str = "file") -> tuple[str, str | None]:
    return "absent", None

def _kind_symlink(path: Path, kind: str = "file") -> tuple[str, str | None]:
    return "symlink", "path is a symlink; the census does not read through links"

def _kind_parent_nonregular(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """``noni/`` is not a directory, the ledger entry itself answers normally."""
    if kind == "dir" and path.name != "decisions":
        return "nonregular", "path is not a directory"
    return "regular", None

def _fault_iterdir(monkeypatch, target: Path, text: str = "readdir denied"):
    """Fault the listing of ``target`` only; every other listing stays honest."""
    real_iterdir = Path.iterdir

    def boom(self):
        if self == target:
            raise OSError(text)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)

def _is_census_written_path(rel: str) -> bool:
    """The predicate the identifier rule reads, spelled out for its own test.

    A path is what the census wrote when it is a plain path below the repo root:
    two or more segments, none empty, none ``.`` or ``..``, the first not opening
    with ``~``, and no segment longer than a directory is ever named. Everything
    else is a path a caller spelled, and the row may print only its last segment.
    """
    parts = rel.rstrip("/").split("/")
    return (len(parts) >= 2 and all(p not in ("", ".", "..") for p in parts)
            and not parts[0].startswith("~")
            and all(len(p) <= census_ledger._ROOT_SEGMENT_MAX for p in parts))

def _valid_record(rec_id="2026-10-01-alpha", status="decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }

def _rows(repo: Path, *args: str) -> list[dict]:
    """The finding rows of an in-process --json run."""
    import io
    import json
    from contextlib import redirect_stderr, redirect_stdout

    import census

    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json", *args]
    with redirect_stdout(out), redirect_stderr(err):
        census.main(argv)
    rows = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == "finding"]

def _code(repo: Path, *args: str) -> int:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import census

    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        return census.main(argv)

def _host_shaped_faults() -> list[tuple[OSError, tuple[str, ...]]]:
    """The faults whose filename the scrubber has kept losing, and their parts.

    Built at runtime, never literals: a tracked file carrying one of these paths
    would trip the census's own hygiene class. Each is the shape a real fault on
    a real host takes -- a service account's home, a directory whose name holds a
    space and characters outside the ASCII alphabet -- and each is a shape the
    path arms of ``census_text._stripped`` cannot be relied on to catch, which is
    why the row is built without the filename instead of scrubbed after it.
    """
    return [
        (OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/"),
         ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir")),
        (OSError(13, "Permission denied", "~deploy"), ("deploy",)),
    ]
