"""The quickstart's ``--issue-state`` recipe, run through the census that reads it.

Split out of ``tests/test_quickstart.py`` on the seam the page itself has: that
module launches the page's commands, and this one runs the one command no
launcher can -- the ``gh`` + ``jq`` recipe the census ships no producer for. The
recipe's two halves are checked by different tools, and only their pairing proves
the page: ``jq`` turns the tracker's payload into a map, and the census's own
``--issue-state`` reader decides whether that map is usable.

The reader is reached through ``census_run._load_issue_state``, the function the
census's run calls for the flag, and its four arguments are replayed from the
source of that call. Importing ``load_issue_state`` and passing this file's
helpers would be a different program: the classifier, bounder and strict JSON
reader are exactly the three things that decide whether a map is accepted, so a
recipe that satisfied hand-picked versions of them could still be refused by the
ones the tool uses.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

from docs_promises import issue_state_from_page
from harness_runners import run_noni
from ordering_fixtures import _entry, _repo, _seed
from quickstart_runner import checked as _checked
from quickstart_runner import run_env

# A fixed clock for the ordering run that reads the recipe's map: the ordering
# group's stale class is time-based, and a run without --now would let the host
# clock decide whether the fixture's confirmed stamps read as stale.
ORDERING_NOW = "2026-10-27T12:00:00Z"

def test_the_issue_state_recipe_produces_a_map_the_census_accepts(tmp_path: Path) -> None:
    """The gh + jq recipe on the page is run, not quoted.

    ``jq`` is invoked with the page's own filter over a payload shaped like the
    tracker's output (issue numbers as numbers, states upper-case), and the result
    is handed to ``census_run._load_issue_state`` -- the function the census's own
    run calls for ``--issue-state`` -- rather than to ``load_issue_state`` wired up
    by hand here. The census's classifier, bounder and strict JSON reader are the
    three arguments that decide whether a map is accepted, and this test may not
    supply its own version of them: a recipe that satisfied hand-picked helpers
    could still be refused by the ones the tool actually uses.

    The two refusals that reader makes -- a key that is not the bare decimal
    spelling, a state word outside the two it names -- are the reason the filter
    carries ``tostring`` and ``ascii_downcase``, so both are checked here with the
    filter removed: a recipe that lost either would pass a reading test and fail a
    reader.
    """
    filter_text = issue_state_from_page()
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(12, None))
    payload = tmp_path / "issues.json"
    payload.write_text(json.dumps([{"number": 7, "state": "CLOSED"},
                                   {"number": 12, "state": "OPEN"}]), encoding="utf-8")
    proc = _jq(filter_text, payload)
    _checked(proc, "the page's jq recipe")
    map_path = tmp_path / "issue-state.json"
    map_path.write_text(proc.stdout, encoding="utf-8")
    result = _census_load_issue_state(repo, map_path)
    assert result.problem is None, f"the census refuses the page's map: {result.problem}"
    assert result.map == {"7": "closed", "12": "open"}, result.map

    # Without tostring the keys arrive as numbers and the reader refuses them;
    # without ascii_downcase the state words do. Both are the recipe's job.
    for name, broken in (("tostring", filter_text.replace(".number | tostring", ".number")),
                         ("ascii_downcase",
                          filter_text.replace(".state | ascii_downcase", ".state"))):
        _assert_broken_filter(tmp_path, name, broken, payload, repo)


def _assert_broken_filter(tmp_path: Path, name: str, broken: str, payload: Path,
                          state_repo: Path) -> None:
    """One variant of the recipe, with one required conversion removed.

    A filter that breaks ``jq`` outright is the same failure to the reader as one
    that emits a map the census refuses: no usable file. The empty document is
    what jq leaves behind, and the census calls that a map that answers nothing,
    so it counts as a refusal for the same reason -- the recipe did not produce
    the map the page promises.
    """
    assert broken != issue_state_from_page(), f"the page's filter no longer names {name}"
    faulty = _jq(broken, payload)
    assert faulty.returncode != 0 or faulty.stdout.strip() not in ("", "{}", "{\n}"), (
        f"the recipe without {name} produced no usable map either: "
        f"rc={faulty.returncode} stderr={faulty.stderr.strip()!r}"
    )
    bad = tmp_path / f"bad-{name}.json"
    bad.write_text(faulty.stdout, encoding="utf-8")
    verdict = _census_load_issue_state(state_repo, bad)
    assert verdict.problem is not None or verdict.map != {"7": "closed", "12": "open"}, (
        f"a filter without {name} still produced the map the page promises, so "
        f"the assertion above pins nothing"
    )


def _jq(filter_text: str, payload: Path):
    return subprocess.run(["jq", filter_text, str(payload)], capture_output=True,
                          text=True, env=run_env(), timeout=60)


def _census_load_issue_state(repo: Path, path: Path):
    """The census's own ``--issue-state`` read of one file, in a child process.

    The census's run calls ``census_run._load_issue_state`` for the flag and hands
    it its own classifier, bounder and strict JSON reader. This drives that call
    site -- a real ``noni census --issue-state FILE`` over ``repo``, whose ordering
    artifact cites the issues the map answers, so the load happens on the path a
    reader takes -- rather than importing ``load_issue_state`` and passing this
    file's version of those helpers: the map has to be accepted by the code the
    tool uses, not by a copy of its wiring kept here.

    A map the census refuses keeps its reason in the child's report, so the verdict
    is rebuilt here from the census's own reader on exactly the arguments
    ``_load_issue_state`` passes to it.
    """
    from noni import census_run

    proc = run_noni("census", "--repo", str(repo), "--now", ORDERING_NOW, "--json",
                    "--only", "ordering-closed", "--issue-state", str(path),
                    cwd=repo)
    assert proc.returncode in (0, 15), (
        f"the census run that reads the recipe's file did not reach a verdict "
        f"({proc.returncode})\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "ordering-closed was not evaluated" not in proc.stdout, (
        f"the run answered the closed class without the file, so the map given was "
        f"never read: {proc.stdout!r}")

    call = inspect.getcallargs(census_run._load_issue_state, path)
    assert call["issue_state_path"] == path, (
        "the census's run does not take the file path as its argument")
    signature = inspect.signature(census_run._ordering_readers.load_issue_state)
    positional = [name for name, parameter in signature.parameters.items()
                  if parameter.kind is parameter.POSITIONAL_OR_KEYWORD]
    bound = inspect.signature(census_run._load_issue_state).parameters
    assert set(bound) == {"issue_state_path"}, (
        f"_load_issue_state no longer takes only the path, so the four readers "
        f"arguments below are no longer the census's own: {list(bound)}")
    args = _replay_load_arguments(census_run, path, positional)
    from noni.census_ordering_readers import load_issue_state

    return load_issue_state(*args)


# Strings and comments stripped out of the census's own call before its
# arguments are split on commas: a quoted comma must not look like a separator.
_DROP_STRINGS_AND_COMMENTS = re.compile(
    '"(?:[^"\\\\]|\\\\.)*"' r"|'[^']*'|#.*$", re.M)


def _load_issue_state_source() -> str:
    """The source of the census's own loader, as its module file holds it.

    Read by name from ``census_run.__file__`` rather than with
    ``inspect.getsource``: the census's own run helpers import ``census.py`` under
    the ``__main__`` name (it is a script, not a package module), and
    ``inspect.getsource`` resolves a function whose module is ``__main__`` through
    ``sys.modules['__main__']`` -- pytest's module here -- and hands back the wrong
    file. The path comes from the module's own ``__file__``, so the text is the
    file the run executes, not a guess at it.
    """
    from noni import census_run

    name = census_run._load_issue_state.__name__
    text = Path(census_run.__file__).read_text(encoding="utf-8")
    match = re.search(rf"^def {name}\(.*?^    return .*?\)\n", text, re.M | re.S)
    assert match, (
        f"{name} no longer ends in a single return call in {census_run.__file__}, "
        f"so this test has no source to replay its arguments from")
    return match.group(0)


def _replay_load_arguments(census_run, path: Path, positional: list[str]) -> list[object]:
    """The four arguments ``_load_issue_state`` passes on, read off its own body.

    The census's run is not instrumented from outside (it runs in a child), so the
    values are taken from the expressions the function itself writes, in the order
    the readers module declares them. Each expression is the one the census module
    resolves -- the state tuple, the classifier, the bounder, the strict reader --
    so a rename or a swap of any of them is the failure this reports rather than a
    silently hand-picked replacement.
    """
    source = _load_issue_state_source()
    stripped = _DROP_STRINGS_AND_COMMENTS.sub("", source)
    call_text = stripped[stripped.rindex("load_issue_state(") + len("load_issue_state("):]
    inner = call_text[:call_text.index(")")]
    parts = [part.strip() for part in inner.split(",") if part.strip()]
    assert parts[0] == "issue_state_path", (
        f"_load_issue_state no longer passes the path first, so this test's "
        f"replacement call is not the census's: {parts}")
    assert len(parts) == len(positional), (
        f"_load_issue_state no longer passes the readers module's {len(positional)} "
        f"positional arguments, so this test cannot replay its call: {parts}")
    # The loader resolves the census module into a local named ``census`` at its
    # own call, so that is the name the expressions above are evaluated under.
    scope = {**vars(census_run), "census": census_run._census()}
    return [path, *[eval(expression, scope) for expression in parts[1:]]]

def test_the_census_run_reads_the_map_the_recipe_produces(tmp_path: Path) -> None:
    """The census answers the closed class only when the recipe's file is given.

    The child run inside ``_census_load_issue_state`` is the census's own call
    site, and a helper that never reached it would still answer the assertions
    above from its in-process replay. This pins the observable difference the
    flag makes on the same tree: no flag, no closed row and the note that says so;
    the recipe's map, a closed row that names the issue the map says is closed.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(12, None))
    path = tmp_path / "issue-state.json"
    path.write_text(json.dumps({"7": "open", "12": "closed"}), encoding="utf-8")
    without = _census_json_run(repo, None)
    assert not [line for line in without.stdout.splitlines()
                if '"check": "ordering-closed"' in line], (
        f"a run with no --issue-state answered the closed class: {without.stdout!r}")
    assert "ordering-closed was not evaluated" not in without.stdout, (
        f"--json mode must not print the human-mode note: {without.stdout!r}")
    with_flag = _census_json_run(repo, str(path))
    rows = [json.loads(line) for line in with_flag.stdout.splitlines() if line.strip()]
    closed = [r for r in rows if r.get("check") == "ordering-closed"]
    assert [r["subject"] for r in closed] == ["#12"], (
        f"the map the recipe's filter produces did not reach the census through "
        f"_load_issue_state (it reads a file, so this is the flag's own path): "
        f"{with_flag.stdout!r}")


def _census_json_run(repo: Path, issue_state: str | None):
    """The census's ordering group, as NDJSON, with or without ``--issue-state``."""
    args = ["census", "--repo", str(repo), "--now", ORDERING_NOW, "--json",
            "--only", "ordering-closed"]
    if issue_state:
        args += ["--issue-state", issue_state]
    return run_noni(*args, cwd=repo)
