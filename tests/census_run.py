"""The two ways a census test drives the census.

``_run_census`` runs it in-process, ``_run_census_from`` runs it from another working
directory, and ``_census_main`` is the fresh-import call both build on. All three are
kept together so the run helpers have one owner: a test file that imported
``_census_main`` from one module and ``_run_census`` from another would be reading a
fixture through a fixture. Copied verbatim from ``tests/test_census_unified.py``,
whose census-level exit-code and clean-tree tests now live in
``tests/test_census_exit_codes.py`` and ``tests/test_census_reporting.py``.
"""

from __future__ import annotations

from pathlib import Path


def _run_census(repo: Path, *args: str, json_out: bool = False,
                skip_hygiene: bool = False) -> tuple[int, str, str]:
    """Run census.main in-process and return (exit_code, stdout, stderr).

    ``skip_hygiene`` adds --skip hygiene: tests of the ledger and session
    classes use it so the always-reporting hygiene class (an isolated fixture
    repo has no deny-list) cannot decide the exit code under --strict."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    argv = ["--repo", str(repo)]
    if json_out:
        argv.append("--json")
    if skip_hygiene:
        argv.extend(["--skip", "hygiene"])
    argv.extend(args)
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = _census_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()

def _census_main(argv: list[str]) -> int:
    """Import and call census.main(argv) with a fresh module import."""
    import importlib

    return importlib.import_module("census").main(argv)

def _run_census_from(cwd: Path, repo: Path, *args: str) -> tuple[int, str, str]:
    """``_run_census`` with the process started in a directory that is not the
    state root.

    The census's default ``--repo`` is ``.``, which is the one place its cwd may
    decide anything; a run that names ``--repo`` must not consult the cwd at all.
    So the caller passes ``--repo`` itself and this launches the census with
    ``cwd`` set somewhere else: an in-process launcher cannot move the real
    process without taking every other test with it, and a ``monkeypatch.chdir``
    would not survive the census's own ``Path`` reads being shared with pytest.
    """
    import io
    import os
    from contextlib import redirect_stderr, redirect_stdout

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    previous = os.getcwd()
    os.chdir(cwd)
    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = _census_main(["--repo", str(repo), *args])
    finally:
        os.chdir(previous)
    return rc, out_buf.getvalue(), err_buf.getvalue()
