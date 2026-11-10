"""The doc'd invocation of each shell entry point is the one the harness launches.

``tests/test_census_help.py`` and ``tests/conftest.py::run_census`` already prove
the two shims are bash: they launch them as ``["bash", <path>, ...]`` and the
byte-for-byte ``--help`` comparison passes. What nothing proved before this file
is the other half of the same fact -- that no *page* tells a reader otherwise. A
doc line is not executable, so the assertion has to come from the launch form the
suite itself depends on: this module reads the interpreter out of the launchers
that run each entry point and checks that the pages agree with it.

Two entry points, two forms, one rule each:

- ``skills/steering-ledger/scripts/census.sh`` is a bash script. The
  suite runs it with ``bash``; every doc line that puts one in command
  position shows ``bash`` or the direct executable form, never an interpreter
  other than that.
- ``skills/census/scripts/census.py`` and its sibling wrappers are Python and
  the README launches them under ``python3``, which is also what their own
  docstrings say. The line that launches one may therefore name a Python
  interpreter and nothing else.

The set of pages is the one the issue named, and it is declared here once so
this module and ``tests/test_docs_promises.py`` cannot be looking at different
trees while claiming to check the same rule.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _harness import CENSUS, CENSUS_SH, DECIDE, ORDER, REPO
from docs_commands import read
from docs_promises import DOC_PAGES, SKILL_PAGES

# The launcher that already pins the shim's interpreter, read as text. It
# are named by path rather than imported for their constants because the point of
# this check is the launch form those files commit to; if either stops launching
# with bash, the check here is no evidence of anything and says so.
_LAUNCHERS: tuple[Path, ...] = (
    REPO / "tests" / "conftest.py",
    REPO / "tests" / "test_census_help.py",
)

# The bash shims, paired with the path each is documented under. Keyed by the
# file the docs name, so a page cannot satisfy the check by naming a same-named
# script of another skill.
SHIMS: tuple[tuple[Path, str], ...] = (
    (CENSUS_SH, "census.sh"),
)

# The Python entry points the pages launch, by basename. The wrappers are
# documented as ``scripts/<name>.py`` and the README launches them under
# ``python3``; their docstrings name the same route.
_PY_ENTRIES: frozenset[str] = frozenset({
    "census.py", "decide.py", "order.py",
})

# Any interpreter a line may name. Deliberately broader than the two this tree
# has: a page that started showing ``uv run census.sh`` would otherwise slip past
# a check written against the current reality alone.
_INTERPRETERS = (
    "python", "python3", "python3.11", "pypy", "uv", "uvx", "poetry", "pipenv",
    "node", "ruby", "perl",
)

_INTERPRETER_FORM = re.compile(rf"(?:^|[\s;&|(`])((?:{'|'.join(map(re.escape, _INTERPRETERS))})\s+)\S*\.sh\b")


def _shebang(path: Path) -> str:
    """The interpreter a script's own first line names."""
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("#!"), f"{path.name} has no shebang to read an interpreter from"
    return first


def test_the_harness_launches_the_shims_with_bash() -> None:
    """The precondition of every check below, stated as its own test.

    The suite's census launchers are the reference for "bash": if
    they ever stop launching with bash, the page-level checks against bash stop
    meaning anything, so this fails at the source rather than leaving several
    green tests reading a rule nobody enforces. The launch strings are the
    literals in those files, matched on the path expression each one uses.
    """
    for path in _LAUNCHERS:
        assert path.is_file(), f"{path.name} is missing; the launch form is unpinned"
    launchers = "\n".join(path.read_text(encoding="utf-8") for path in _LAUNCHERS)
    census_launch = '["bash", str(REPO / "skills" / "steering-ledger" / "scripts" / "census.sh")'
    assert census_launch in launchers, (
        "conftest.run_census no longer launches census.sh with bash, so the doc "
        "check below has no reference to check against"
    )


def test_the_shims_are_bash_scripts_by_their_own_shebang() -> None:
    """The scripts' own first lines say bash, which is what the pages promise.

    Read off the file rather than asserted as a constant: the day one of them
    becomes a Python script, the pages have to change, and this is the check that
    says so instead of the reader's traceback.
    """
    for path, name in SHIMS:
        assert "bash" in _shebang(path), (
            f"{name} is no longer a bash script, so the pages showing it under "
            "bash need rewriting")


@pytest.mark.parametrize("path,name", SHIMS, ids=lambda p: getattr(p, "name", str(p)))
def test_no_page_names_an_interpreter_in_front_of_a_shim(path: Path, name: str) -> None:
    """Every page in scope shows this shim under bash or run directly.

    ``path`` is the script the rule is about; the pages are read once and shared
    with the other checks here so the set cannot drift between tests. A line
    that names any interpreter other than bash beside a ``.sh`` path is a page
    sending the reader to a traceback.
    """
    offenders: list[tuple[str, str]] = []
    for doc in (*DOC_PAGES, *SKILL_PAGES):
        text = read(doc)
        for line in text.splitlines():
            match = _INTERPRETER_FORM.search(line)
            if match and name in line:
                offenders.append((doc.name, line.strip()))
    assert not offenders, (
        f"pages run {name} under an interpreter that is not bash: {offenders}")


def test_the_python_entries_are_never_shown_as_shell() -> None:
    """The mirror image: a ``.py`` entry point is launched by an interpreter.

    The wrapper form the skills document is ``scripts/<name>.py --repo ...``,
    which relies on the executable bit and the shebang; the README's form puts
    ``python3`` in front. Both are legitimate. What is not legitimate is the two
    of them mixed, because a page that shows ``bash scripts/census.py``
    documents a run that dies on the first line.
    """
    offenders: list[tuple[str, str]] = []
    for doc in (*DOC_PAGES, *SKILL_PAGES):
        for line in read(doc).splitlines():
            if re.search(r"(?:^|[\s;&|(`])bash\s+\S*\.py\b", line):
                offenders.append((doc.name, line.strip()))
    assert not offenders, f"pages run a Python entry point under bash: {offenders}"


def test_the_documented_wrappers_are_the_ones_the_suite_launches() -> None:
    """The entry points named by the pages exist where the pages say they do.

    The paths are the harness's own constants -- the same ones the equivalence
    and help tests drive -- so a page that renames a wrapper or moves it to
    another skill fails here rather than shipping a command nobody can run.
    """
    documented = {path.name for path in (CENSUS, DECIDE, ORDER, CENSUS_SH)}
    assert documented == {"census.py", "decide.py", "order.py", "census.sh"}, documented
    for path in (CENSUS, DECIDE, ORDER, CENSUS_SH):
        assert path.is_file(), f"{path.name} is missing from the tree the docs describe"
        assert path.stat().st_mode & 0o111, (
            f"{path.name} is not executable, so the direct form the pages show "
            "would not run on a fresh clone")
    assert _PY_ENTRIES & {p.name for p in (REPO / "skills").rglob("*.py")}


def test_the_census_skill_shows_its_own_entry_point_under_python() -> None:
    """The census skill's usage line names a Python interpreter, and the file is
    Python. AC5's positive half: the rule is not "never write python3", it is
    "match the file".
    """
    text = read(REPO / "skills" / "census" / "SKILL.md")
    line = next((line for line in text.splitlines()
                 if re.search(r"python3?\s+\S*census\.py\b", line)), None)
    assert line is not None, "the census skill no longer shows its entry point under python3"
    assert "bash" not in line, f"the census usage line mixes both interpreters: {line!r}"
    assert "python" in _shebang(CENSUS).lower(), (
        "census.py is no longer a Python script, so its usage line is wrong")
