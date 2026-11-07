"""What the pages promise about *installing* noni, checked as text over the page set.

The install claims of ``tests/test_docs_promises.py``, kept apart from the deny-list,
recipe and shim claims so each module stays under the 500-line cap in
``tests/test_file_size_limit.py`` and each reads as one promise rather than four. The
page set is shared rather than redeclared: ``tests/docs_promises.py`` owns where the
docs tests look, and both modules read the same pages through it -- the reason
``tests/readme_support.py`` holds the README's reading layer apart from its promises.
The companion ``tests/test_docs_install_promises.py`` holds the other half of the same
reader problem: the precondition sentence a page owes when it puts a ``scripts/*.py``
or ``scripts/*.sh`` entry point in command position.

Four claims, each the residue of a first run that failed on the docs alone:

- **No page sends a reader to a package index.** ``pip install noni`` does not fail:
  it installs somebody else's wheel and leaves a ``noni`` with no census in it, which
  is worse than a message. A page that offers an install route must say the package is
  unpublished and give the form that names this repository.
- **No page installs into a system Python.** The quickstart's old line, ``python3 -m
  pip install ./noni``, stops on a distribution that marks its interpreter
  externally-managed (PEP 668) and leaves no ``noni`` on the path. The offenders here
  are read from argv, not from the prose around it, and on the *base name* of the
  runner: ``/usr/bin/pip``, ``$HOME/sys/bin/pip3`` and a bare ``pip3`` are the system
  pip as plainly as ``pip`` is, so a gate that keyed on the unqualified word alone
  would let the exact failure AC1 exists to prevent walk past it.
- **The README does not print an install command.** It defers to the page that owns
  the install, named by exact path, so one page rather than two has to stay in step
  with the quickstart's golden install list.
- **The offender shape itself is proven.** A gate that passes today on the page as it
  stands is not evidence it fails tomorrow on a page rewritten to look compliant, so
  the shapes it must refuse and the ones it must allow are asserted directly.
"""

from __future__ import annotations

import re

from docs_commands import block_commands, read
from docs_page_set import ALL_PAGES, _label, bash_of
from docs_promises import README

# The install claim a page may not make as an *instruction*: a bare ``pip
# install noni``, which resolves on the public index to a different project
# entirely. Both legitimate shapes -- an install that names a path or a URL, and a
# prose mention that warns the reader away from the command -- are excused by the
# gate below, whose docstring carries the reasoning.
_BARE_PIP_INSTALL = re.compile(r"pip install noni\b(?![-/\w])")


def test_no_page_tells_a_reader_to_install_from_a_package_index() -> None:
    """``pip install noni`` appears nowhere as an instruction.

    The command does not fail, which is the problem: it installs an unrelated
    project's wheel, and the reader's ``noni census`` then names a module that
    does not exist. Every page that offers an install route names the clone or
    the git URL instead.

    Two shapes are legitimate and are excused by position rather than by wording:
    an install that names a path or a URL after the package name, and a mention of
    the bare command inside prose that is warning the reader away from it -- the
    sentence that names the command to tell the reader it does not do what they
    think. The second exemption is what keeps a truthful retraction from being
    flagged as the claim it retracts.

    The exemption is per line, not per page, and it is earned: a line that
    names the bare command has to say in the same breath that it is the wrong
    command. ``fails``, ``not``, ``other`` and ``different`` are the words a
    retraction carries, so a page that simply told the reader to run it is still
    caught. A line that fails this test after a rewrite is a page that lost its
    retraction, which is exactly the drift the check exists for.
    """
    retracting = re.compile(r"\b(not|no |other|different|instead|avoid|never)\b", re.I)
    offenders: list[tuple[str, str]] = []
    for path, text in ALL_PAGES:
        for line in text.splitlines():
            if not _BARE_PIP_INSTALL.search(line):
                continue
            if _BARE_PIP_INSTALL.search(line) and retracting.search(line):
                continue
            offenders.append((_label(path), line.strip()))
    assert not offenders, (
        f"pages tell the reader to install from an index without retracting it: {offenders}")


def test_the_pages_that_install_noni_say_the_index_does_not_have_it() -> None:
    """Whichever page carries an install command also says noni is unpublished.

    Checked over the set rather than hard-coded to one page, so moving the
    install prose cannot satisfy the README test and leave the claim unmade.
    """
    carrying = [(path, text) for path, text in ALL_PAGES
                if re.search(r"pip install[^\n]*\./noni|pip install[^\n]*git\+https", text)]
    assert carrying, "no page gives an install form that names the repository"
    missing = [_label(path) for path, text in carrying
               if "not published" not in text.lower()
               and "no package index" not in text.lower()
               and "pypi" not in text.lower()]
    assert not missing, f"pages give an install form without saying the index lacks noni: {missing}"


def test_no_page_tells_a_reader_to_install_into_the_system_python() -> None:
    """No page runs an installer against an interpreter the reader does not own.

    ``python3 -m pip install ./noni`` was the quickstart's install line, and on a
    distribution that marks its system Python externally-managed (PEP 668) it stops
    with no ``noni`` on the path: the first-run failure the pilot hit. The forms that
    work name a tool that isolates the install (`uv tool install`) or a virtual
    environment's own pip, so the shape of the offender here is any ``pip`` of noni --
    a bare ``pip``/``pip3``, any ``python*`` carrying ``-m pip``, or an interpreter's
    own ``bin/pip``. The check reads argv rather than the line, so rewording the prose
    around the command does not clear it, and the runner is matched on its **base
    name**: an absolute path (``/usr/bin/pip``, ``/usr/bin/python3.12 -m pip``) and an
    expanded-variable path (``$HOME/sys/bin/pip``) name the system interpreter as
    plainly as a bare ``pip`` does, so a gate that keyed on the unqualified word would
    let the exact failure AC1 exists to prevent walk past it. What stays allowed is a
    runner that names a virtual environment the reader made -- a path under a leading
    dot (``.venv/bin/pip``) or one that says so (``$VIRTUAL_ENV/bin/pip``). Being
    *unqualified* is not such a marker, so neither is ``/tmp``: a bare ``pip3`` in a
    temp directory is still the interpreter on the reader's PATH.
    """
    offenders: list[tuple[str, str]] = []
    for path, text in ALL_PAGES:
        for block in bash_of(text):
            for argv in block_commands(block):
                if system_python_install(argv):
                    offenders.append((_label(path), " ".join(argv)))
    assert not offenders, (
        f"pages install noni into an interpreter the reader may not own, which a "
        f"PEP 668 marker stops: {offenders}")


# How a command reaches pip: a ``pip``/``pip3`` program of its own, an interpreter
# asked to run the module, or an interpreter invoked as an installer directly. Each is
# recognised on the program's base name -- ``/usr/bin/pip`` and ``$HOME/sys/bin/pip3``
# are the system pip as surely as a bare ``pip`` is, and an unqualified word is not the
# shape a PEP 668 box reaches its interpreter by.
_PIP_BASENAME = re.compile(r"^pip\d*$")
_PYTHON_BASENAME = re.compile(r"^python\d*(\.\d+)*$")

# Words that mean "install this package" when a program is invoked with them, and the
# wrappers that put the real program further along the same line.
_INSTALL_WORDS = frozenset({"install", "install ./noni"})
_WRAPPERS = frozenset({"sudo", "env", "command", "time"})


def _base_name(token: str) -> str:
    """The program a path token names, with any directory or variable prefix gone."""
    return token.rsplit("/", 1)[-1]


def _pip_runner(argv: list[str]) -> bool:
    """True when the parsed command runs pip, under any runner.

    A wrapper (``sudo``, ``env``) is skipped rather than excused: ``sudo pip install
    ./noni`` is the system pip wearing a hat, and refusing to look past the wrapper
    would let the most forceful form of the PEP 668 failure through the one gate meant
    to stop it.
    """
    while argv and _base_name(argv[0]) in _WRAPPERS:
        argv = [token for token in argv[1:] if token != "="]
    if not argv:
        return False
    runner = _base_name(argv[0])
    if _PIP_BASENAME.match(runner) is not None:
        return True
    if _PYTHON_BASENAME.match(runner) is None:
        return False
    # An interpreter reaches pip either as a module (``-m pip``) or directly
    # (``python install ./noni``, which the gate refused before this rewrite and must
    # go on refusing); either way the interpreter on the reader's PATH is the one that
    # carries the marker.
    return "pip" in argv[1:3] or any(token in _INSTALL_WORDS for token in argv[1:])


def installs_noni(argv: list[str]) -> bool:
    """True when one parsed command installs this project's package from the clone."""
    return "install" in argv and "./noni" in argv


def _names_a_venv(argv: list[str]) -> bool:
    """True when one of the command's path tokens sits inside a virtual environment.

    Two shapes say "the reader's own venv": a path beginning with a dot (``.venv``,
    ``./.venv``, ``./noni/.venv``) and an assignment or expansion that says so
    (``env=/tmp/v``, ``$env/bin/pip``, ``$VIRTUAL_ENV/bin/pip``). Both name a tree the
    reader made and owns, which is the side of the PEP 668 line the page installs on.

    The package argument is not a path token. It is ``./noni`` on every install form
    the page offers, and reading it as one would exempt ``/usr/bin/pip install ./noni``
    -- the very command AC1 exists to refuse -- so the operand is excluded before the
    shapes are read.
    """
    return any(_venv_shape(token) for token in argv if token != _PACKAGE_OPERAND)


# The operand every install form on the page names, and the only token exempt from the
# venv shapes above.
_PACKAGE_OPERAND = "./noni"


def _venv_shape(token: str) -> bool:
    """One token that places the command inside a virtual environment the reader made."""
    return token.startswith(".") or "venv" in token.lower() \
        or _ASSIGNMENT.match(token) is not None \
        or _VENV_VARIABLE in token


# ``env=/tmp/v`` (a variable the reader set for their own venv), as the page may print
# it. An expansion of such a variable ($env, ${env}) counts the same way.
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_VENV_VARIABLE = "$VIRTUAL_ENV"


def system_python_install(argv: list[str]) -> bool:
    """One parsed command that installs noni with pip against a system interpreter.

    Three conditions, all of which have to hold: it installs this package from the
    clone, it reaches pip by one of the two forms, and nothing in the command names a
    virtual environment the reader made. The last is what keeps the page's
    ``.venv/bin/pip install ./noni`` a pass and ``/usr/bin/pip install ./noni`` a
    failure, and it is deliberately about the path tokens rather than the runner
    alone: a bare ``pip3`` is the system pip wherever the command happens to sit, so
    an unqualified runner is never taken for a venv of its own.
    """
    return installs_noni(argv) and _pip_runner(argv) and not _names_a_venv(argv)


def test_the_system_python_gate_refuses_a_runner_written_as_a_path() -> None:
    """The offender shape is proven on runners, not just on the page as it stands.

    The original gate keyed on ``argv[0]`` alone, so ``/usr/bin/pip install ./noni``,
    ``/usr/bin/python3.12 -m pip install ./noni`` and ``pip3 install ./noni`` each
    cleared a page gate whose docstring claimed to cover "a ``python``, or an
    interpreter's own ``bin/pip``": an absolute path is how a reader on a PEP 668
    box reaches the interpreter the marker protects, so the class AC1 exists to stop
    walked straight past it. Each row below is one argv the page might print; the
    first set must be refused and the second accepted, so a gate that broadened or
    narrowed its own shape reddens here rather than silently losing a form.
    """
    refused = [
        ["pip", "install", "./noni"],
        ["pip3", "install", "./noni"],
        ["/usr/bin/pip", "install", "./noni"],
        ["/usr/bin/python3", "-m", "pip", "install", "./noni"],
        ["/usr/bin/python3.12", "-m", "pip", "install", "./noni"],
        ["$HOME/sys/bin/pip", "install", "./noni"],
        ["${PREFIX}/bin/python3", "-m", "pip", "install", "./noni"],
        ["/tmp/pip", "install", "./noni"],
        ["python", "install", "./noni"],
        ["/usr/bin/python3.13", "install", "./noni"],
        ["sudo", "pip", "install", "./noni"],
        ["sudo", "/usr/bin/pip3", "install", "./noni"],
    ]
    for argv in refused:
        assert system_python_install(argv), (
            f"the page gate would let a reader run {' '.join(argv)}, which is a pip "
            "against an interpreter they do not own")
    accepted = [
        ["uv", "tool", "install", "./noni"],
        [".venv/bin/pip", "install", "./noni"],
        ["./.venv/bin/pip", "install", "./noni"],
        [".venv/bin/python", "-m", "pip", "install", "./noni"],
        ["./noni/.venv/bin/pip", "install", "./noni"],
        ["env=/tmp/nv $env/bin/pip", "install", "./noni"],
        ["$VIRTUAL_ENV/bin/pip", "install", "./noni"],
        ["python3", "-m", "venv", ".venv"],
        ["sudo", "uv", "tool", "install", "./noni"],
    ]
    for argv in accepted:
        assert not system_python_install(argv), (
            f"the page gate refuses {' '.join(argv)}, which installs into a virtual "
            "environment the reader made -- the form the quickstart recommends")


def test_the_readme_defers_the_install_to_the_quickstart() -> None:
    """The README points at the page that owns the install, and prints no command itself.

    AC3's testable half, read from the page rather than from the quickstart: the
    pointer names ``docs/QUICKSTART.md`` by exact path, names the *Install noni*
    section it defers to, and keeps the tool name of that section's primary form
    (`uv tool install`) in the same paragraph, so a reader of the README is told which
    install they are being sent to read before they follow the link. The README prints
    no install command of its own: that is what keeps one page, not two, in step with
    the golden install list, and the assertion below is what holds it there. The one
    install-shaped string the page may carry is the retraction sentence ``pip install
    noni`` names as the wrong command, already held to its retraction by the
    package-index gate above.
    """
    readme = read(README)
    assert "docs/QUICKSTART.md" in readme, "the README no longer names the quickstart"
    assert "Install noni" in readme, (
        "the README's install prose no longer points at the section that owns it")
    assert "uv tool install" in readme, (
        "the README's install pointer names no install form, so a reader cannot tell "
        "what the page they are sent to will tell them to run")
    printed = [argv for block in bash_of(readme)
               for argv in block_commands(block) if installs_noni(argv)]
    assert not printed, (
        f"the README prints an install command, so it is a second page to keep in "
        f"step with the quickstart: {printed}")
