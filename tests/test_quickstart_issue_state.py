"""The quickstart's ``--issue-state`` recipe, run through the census that reads it.

Split out of ``tests/test_quickstart.py`` on the seam the page itself has: that
module launches the page's commands, and this one runs the one command no launcher
can -- the ``gh`` + ``jq`` recipe the census ships no producer for. The recipe's two
halves are checked by different tools, and only their pairing proves the page: ``jq``
turns the tracker's payload into a map, and the census's own ``--issue-state`` reader
decides whether that map is usable.

The recipe is not invented here: it is the golden command the page prints
(:func:`quickstart_runner.recipe_gh_argv`), decomposed into the three parts a
launcher cannot run -- the filter ``jq`` evaluates, the payload ``gh`` would have
fetched, and the file the redirect writes. A change to the printed line reddens the
golden comparison, not this module's reading of it.

The reader is reached only through a real census child run. That is the whole of
the test: ``noni census --repo <tree> --issue-state <file>`` is the census's own
call site (``census_run._load_issue_state``), and the verdict is read off the
child's exit code and its rows. A helper that reached the reader some other way --
by importing it and supplying its own classifier, bounder and JSON reader, or by
reading those arguments off the product's source and replaying them -- would be a
different program, and one whose acceptance proves nothing about the tool the reader
runs: those three arguments are exactly what decides whether a map is usable, so a
recipe that satisfied hand-picked versions of them could still be refused by the
ones the census uses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from docs_promises import issue_state_from_page
from harness_runners import run_noni
from ordering_fixtures import _entry, _repo, _seed
from quickstart_runner import ORDERING_NOW, recipe_gh_argv, run_env

# The verdicts a census run that was asked about ``ordering-closed`` can honestly
# reach: 0 for a map it accepted, 15 (``ordering-malformed``) for a file it
# refused. Anything else means the run never got as far as reading the map -- a
# usage error, a missing tool -- and the assertion below says so rather than
# letting a run that answered nothing look like a run that answered "accepted".
EXIT_MAP_ACCEPTED = 0
EXIT_MAP_REFUSED = 15


def test_the_gh_recipe_line_is_the_command_the_page_prints() -> None:
    """The recipe the tests run is the launcher's golden command, not a paraphrase.

    The decomposer reads a filter, a redirect and a target out of the printed line;
    each part has to be there as the page prints it, or this module would be
    running a recipe of its own invention while reporting the page's verdict.
    """
    argv = recipe_gh_argv()
    assert argv[0] == "gh" and argv[:3] == ["gh", "issue", "list"], argv
    assert argv[3:5] == ["--json", "number,state"], (
        f"the recipe no longer asks gh for the two fields jq reads: {argv}")
    assert argv[5] == "--jq", argv
    assert argv[6] == issue_state_from_page(), (
        "the golden recipe's filter and the filter the page quotes are not the same "
        f"text: {argv[6]!r}")
    assert argv[7:] == [">", "issue-state.json"], (
        f"the recipe no longer redirects into the file --issue-state opens: {argv}")


def test_the_issue_state_recipe_produces_a_map_the_census_accepts(tmp_path: Path) -> None:
    """The gh + jq recipe on the page is run, and the census accepts what it emits.

    ``jq`` runs the page's own filter over a payload shaped like the tracker's
    output (issue numbers as numbers, states upper-case); the file it wrote goes
    to a real ``noni census --issue-state`` over a tree whose ordering artifact
    cites those two issues. The exit code is pinned to one exact value in each
    case -- 0 here, 15 for each broken variant below -- so the run cannot pass by
    never reading the file: a census that refused the map exits 15, and this
    assertion says 0.

    The two refusals the reader makes -- a key that is not the bare decimal
    spelling, a state word outside the two it names -- are the reason the filter
    carries ``tostring`` and ``ascii_downcase``, so both are checked here with the
    conversion removed: a recipe that lost either would pass a reading test and
    fail the census.
    """
    filter_text = issue_state_from_page()
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(12, None))
    payload = tmp_path / "issues.json"
    payload.write_text(json.dumps([{"number": 7, "state": "CLOSED"},
                                   {"number": 12, "state": "OPEN"}]), encoding="utf-8")
    proc = _jq(filter_text, payload)
    _checked(proc, "the page's jq recipe")
    # The map jq produced, read as JSON: the census's exit code below says the
    # tool accepted it, and this says the recipe's own conversions did their work
    # (a numeric key or an upper-case state could not produce these two pairs).
    assert json.loads(proc.stdout) == {"7": "closed", "12": "open"}, proc.stdout
    map_path = tmp_path / "issue-state.json"
    map_path.write_text(proc.stdout, encoding="utf-8")

    rows = _census_verdict(repo, map_path, EXIT_MAP_ACCEPTED)
    closed = [r for r in rows if r.get("check") == "ordering-closed"]
    # The map's two halves, both observed: the issue it says is closed earns the
    # closed finding, and the one it says is open earns no row (an open issue is
    # the answer the class is happy with, not a cannot-tell). A map the census had
    # not read would produce neither, and the exit code pinned above is 0.
    assert [(r["subject"], r["message"].startswith("closed:")) for r in closed] == [
        ("#7", True)], f"the accepted map did not reach the closed class: {rows}"
    assert not [r for r in closed if r["subject"] == "#12"], (
        f"the map says #12 is open, so the closed class owes it no finding: {rows}")
    summary = [r for r in rows if r.get("kind") == "summary"]
    assert summary and summary[0].get("exit") == EXIT_MAP_ACCEPTED, rows

    # Without tostring the keys arrive as numbers and the reader refuses them;
    # without ascii_downcase the state words do. Both are the recipe's job.
    for name, broken in (("tostring", filter_text.replace(".number | tostring", ".number")),
                         ("ascii_downcase",
                          filter_text.replace(".state | ascii_downcase", ".state"))):
        _assert_broken_filter(tmp_path, name, broken, payload, repo)


def _assert_broken_filter(tmp_path: Path, name: str, broken: str, payload: Path,
                          state_repo: Path) -> None:
    """One variant of the recipe, with one required conversion removed.

    The census must refuse it: exit 15 and the malformed row naming the file, on
    the same tree and the same flags that gave the accepted run above. A filter
    that breaks ``jq`` outright is caught at the jq step, since the map the page
    promises would then not exist at all.
    """
    assert broken != issue_state_from_page(), f"the page's filter no longer names {name}"
    faulty = _jq(broken, payload)
    assert faulty.returncode != 0 or faulty.stdout.strip() not in ("", "{}", "{\n}"), (
        f"the recipe without {name} produced no usable map either: "
        f"rc={faulty.returncode} stderr={faulty.stderr.strip()!r}"
    )
    bad = tmp_path / f"bad-{name}.json"
    bad.write_text(faulty.stdout, encoding="utf-8")
    rows = _census_verdict(state_repo, bad, EXIT_MAP_REFUSED)
    malformed = [r for r in rows if r.get("check") == "ordering-malformed"]
    assert malformed and malformed[0]["subject"] == "issue-state", (
        f"a filter without {name} did not come back as the malformed row the "
        f"census owes a file it cannot read: {rows}")


def _jq(filter_text: str, payload: Path):
    return subprocess.run(["jq", filter_text, str(payload)], capture_output=True,
                          text=True, env=run_env(), timeout=60)


def _checked(proc: subprocess.CompletedProcess[str], what: str) -> None:
    """One harness step that must succeed, with both streams in the failure text."""
    assert proc.returncode == 0, (
        f"{what} failed ({proc.returncode})\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def _census_verdict(repo: Path, path: Path, expected: int) -> list[dict]:
    """One census child run over ``path``, pinned to one exact exit code.

    This is the census's own ``--issue-state`` call site: the flag, the tree and
    the fixed clock are the only inputs, and the answer is the child's exit code
    plus the rows on its ``--json`` stream. Nothing here imports the reader or
    rebuilds its arguments -- the classifier, bounder and strict JSON reader are
    whatever the tool uses, because the tool is what runs.

    ``expected`` is a single value, not a range, and the note that says the class
    was never evaluated is refused: both are there to catch a run that answered
    nothing and still looked like a verdict.
    """
    proc = run_noni("census", "--repo", str(repo), "--now", ORDERING_NOW, "--json",
                    "--only", "ordering-closed", "--issue-state", str(path),
                    cwd=repo)
    assert proc.returncode == expected, (
        f"the census answered {proc.returncode}, not {expected}, for the map at "
        f"{path.name}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "ordering-closed was not evaluated" not in proc.stdout, (
        f"the run answered the closed class without reading the file given: "
        f"{proc.stdout!r}")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def test_the_census_run_reads_the_map_the_recipe_produces(tmp_path: Path) -> None:
    """The census answers the closed class only when the recipe's file is given.

    The observable difference the flag makes on one tree: no flag, no closed row;
    the recipe's map, a closed row naming the issue the map says is closed. Both
    runs are pinned to their exit code, so the half that says "the row appeared"
    cannot be vacuous about a run that read nothing.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(12, None))
    path = tmp_path / "issue-state.json"
    path.write_text(json.dumps({"7": "open", "12": "closed"}), encoding="utf-8")
    without = _census_json_run(repo, None)
    assert without.returncode == EXIT_MAP_ACCEPTED, (
        f"the run with no --issue-state did not reach its verdict: "
        f"{without.returncode} {without.stdout!r} {without.stderr!r}")
    assert not [line for line in without.stdout.splitlines()
                if '"check": "ordering-closed"' in line], (
        f"a run with no --issue-state answered the closed class: {without.stdout!r}")
    assert "ordering-closed was not evaluated" not in without.stdout, (
        f"--json mode must not print the human-mode note: {without.stdout!r}")
    with_flag = _census_json_run(repo, str(path))
    assert with_flag.returncode == EXIT_MAP_ACCEPTED, (
        f"the run with the recipe's map did not reach its verdict: "
        f"{with_flag.returncode} {with_flag.stdout!r} {with_flag.stderr!r}")
    rows = [json.loads(line) for line in with_flag.stdout.splitlines() if line.strip()]
    closed = [r for r in rows if r.get("check") == "ordering-closed"]
    assert [r["subject"] for r in closed] == ["#12"], (
        f"the map the recipe's filter produces did not reach the census through "
        f"its own --issue-state flag: {with_flag.stdout!r}")


def _census_json_run(repo: Path, issue_state: str | None):
    """The census's ordering group, as NDJSON, with or without ``--issue-state``."""
    args = ["census", "--repo", str(repo), "--now", ORDERING_NOW, "--json",
            "--only", "ordering-closed"]
    if issue_state:
        args += ["--issue-state", issue_state]
    return run_noni(*args, cwd=repo)
