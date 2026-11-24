"""SECURITY.md's "What noni reads and runs" section says what the code does.

The page is the statement a pilot team hands an operator, so it has to be
repeatable without drift: an operator who reads it should be able to say the
same sentences to someone else and still be describing the shipped code. That
makes the section a claim about ``src/noni``, not prose, and a claim nothing
checks is free to go false.

Each assertion pairs the page with the source the claim is made about, so a
rewording that drops a fact reddens a test rather than quietly narrowing the
statement. The section body is taken by a heading split (the same route
``tests/docs_promises.py`` uses), never by scanning the whole page for keywords:
the page already carries em dashes elsewhere, and a page-wide check would fail
on day one for a reason this ticket does not own.
"""

from __future__ import annotations

import ast
import re

from _harness import REPO

# The section's own cap. Markdown outside SKILL.md is exempt from the size gate
# (tests/test_file_size_limit.py puts no limit on a .md), so nothing else would
# notice the section growing past a page an operator can repeat.
SECTION_LIMIT = 14

HEADING = "What noni reads and runs"
PAGE = REPO / "SECURITY.md"

# The order the page must keep the section in: it answers "what does this tool
# touch", which belongs after the scope statement and before the report advice.
HEADING_ORDER = ("In scope", "Out of scope", HEADING, "What helps")

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"


def _section_body(text: str, heading_start: str) -> str:
    """The body of the first ``##`` section whose heading starts with ``heading_start``."""
    start = text.find(f"## {heading_start}")
    assert start >= 0, f"the page has no '## {heading_start}...' section"
    rest = text[start:]
    following = re.search(r"\n## ", rest[1:])
    return rest if following is None else rest[:following.start() + 1]


def _page() -> str:
    assert PAGE.is_file(), "SECURITY.md is missing"
    return PAGE.read_text(encoding="utf-8")


def _section() -> str:
    return _section_body(_page(), HEADING)


def _content_lines(body: str) -> list[str]:
    """The section's content lines: non-blank, and the heading counted once."""
    return [line for line in body.splitlines() if line.strip()]


def _git_runs(tree: ast.Module) -> list[ast.Call]:
    """The ``subprocess.run`` calls in one parsed module, wherever they are written.

    Reached by walking, not by a line pattern: a call the section's claim is about
    can sit inside a helper, and a check that only saw the obvious shape would
    pass while the claim went unchecked.
    """
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"]


def _first_argv_token(call: ast.Call) -> str | None:
    """The program name one ``subprocess.run`` call passes, as far as the AST shows.

    ``None`` where the argv is built elsewhere and cannot be read here; the
    caller checks that shape against the module's own command builder instead.
    """
    if not call.args:
        return None
    argv = call.args[0]
    if isinstance(argv, ast.List) and argv.elts and isinstance(argv.elts[0], ast.Constant):
        return argv.elts[0].value if isinstance(argv.elts[0].value, str) else None
    return None


def _module_text(name: str) -> str:
    path = REPO / "src" / "noni" / f"{name}.py"
    assert path.is_file(), f"src/noni/{name}.py is missing"
    return path.read_text(encoding="utf-8")


def _cli_flags(module: str) -> list[str]:
    """The ``--flag`` names one argparse parser declares, in declaration order."""
    tree = ast.parse(_module_text(module), filename=f"{module}.py")
    flags: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            flags.append(node.args[0].value)
    return flags


def test_the_section_sits_between_the_scope_and_the_advice() -> None:
    """The section is the page's fifth heading, in its agreed position.

    Position is the property here, not just presence: the disclosure route and
    the two scope sections are already pinned elsewhere, and a new heading that
    drifted to the top of the page would bury the route a reporter needs first.
    """
    text = _page()
    found = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert found == list(HEADING_ORDER), (
        f"the page's ## headings are {found}, expected {list(HEADING_ORDER)}"
    )
    assert _content_lines(_section()), "the section has no content"


def test_the_section_stays_short_enough_to_be_repeatable() -> None:
    """The section fits its cap, which nothing else on a .md file enforces."""
    lines = _content_lines(_section())
    assert len(lines) <= SECTION_LIMIT, (
        f"the section is {len(lines)} content lines, over the cap of {SECTION_LIMIT}: "
        "the page is meant to be quoted back by an operator"
    )


def test_the_section_names_the_state_files_and_the_path_flags() -> None:
    """Both halves of every read are named: the fixed state names and the flags.

    The fixed names are the ones the census run falls back to, and the flags are
    read off the shipped parser rather than typed here, so a flag rename moves
    the test and the page together instead of leaving the page naming a flag the
    census no longer has.
    """
    body = _section()
    for rel in ("noni/decisions", "noni/direction/order.json",
                "noni/direction/intent.md"):
        assert rel in body, f"the section does not name the state file {rel!r}"
    for flag in _cli_flags("census_cli"):
        if flag not in ("--repo", "--now", "--stale-after", "--strict", "--json",
                        "--only", "--skip", "--list"):
            assert flag in body, f"the census declares {flag} and the page hides it"
    assert "--from" in _cli_flags("intent"), "intent set no longer takes --from"
    assert "--from" in body, "the section does not name intent set's --from"


def test_the_section_names_the_scrub_lists_and_their_variable() -> None:
    """The deny-list file, its override variable and the allowlist are named.

    These are the two files that decide what the hygiene check excuses, so an
    operator who wants to audit what noni reads has to know they are read.
    """
    body = _section()
    assert ".noni-scrub-denylist" in body, "the deny-list file is not named"
    assert "NONI_SCRUB_DENYLIST" in body, "the deny-list override variable is not named"
    assert ".noni-scrub-allowlist" in body, "the tracked allowlist is not named"


def test_the_section_says_the_hygiene_check_reads_every_tracked_file() -> None:
    """The widest read on the page is stated plainly, with its size cap.

    Stated rather than hedged: the scan lists the whole repository and reads the
    bytes at every listing entry, so a page that implied ``noni/`` only would be
    the least accurate sentence on it.
    """
    body = _section()
    assert "git-tracked" in body, "the section does not say the scan reads tracked files"
    assert "not only" in body, (
        "the section does not say the scan reaches beyond noni/ itself"
    )
    assert "cannot read" in body, "the unreadable-tracked-file finding is not stated"


def test_the_section_says_no_credential_file_and_no_network_call() -> None:
    """The two absences an operator asks about first, and the code agrees.

    The claim is about noni's own code: it opens none of the credential files it
    could find, and no module reaches the network. The source check names the
    shipped module that would invalidate the sentence, so a page that outlived
    its own claim says which file to look at.
    """
    body = _section().lower()
    for token in (".env", ".netrc", ".ssh", ".git-credentials"):
        assert token in body, f"the section does not name {token} as unopened"
    assert "network" in body, "the section does not state the absence of a network call"
    banned = ("import socket", "import urllib", "import http", "import smtplib",
              "import ftplib", "import ssl")
    for path in sorted((REPO / "src" / "noni").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for import_form in banned:
            assert import_form not in source, (
                f"{path.relative_to(REPO)} now carries {import_form!r}, which the "
                "section says no code does"
            )


def test_the_section_names_git_as_the_only_program_it_runs() -> None:
    """One program, one call shape, and every hardening flag the section names.

    The subprocess sites are read off the shipped modules, and each argv is
    checked to start with ``git`` followed by ``-C``: that is what "always as
    ``git -C <path>``" claims, and a call that dropped the ``-C`` would answer
    for whatever repository the caller happened to stand in.
    """
    body = _section()
    assert "git -C <path>" in body, "the section does not give git's call shape"
    for hardening in ("hooks", "fsmonitor", "protocol"):
        assert hardening in body, f"the section no longer names {hardening} as switched off"
    assert "time limit" in body, "the section no longer states the time limit"

    for name in ("census_git", "gitwrite", "order_gitwrite", "public_safety_scan"):
        source = _module_text(name)
        runs = _git_runs(ast.parse(source, filename=f"{name}.py"))
        assert runs, f"src/noni/{name}.py has no subprocess.run to check"
        for call in runs:
            assert any(kw.arg == "timeout" for kw in call.keywords), (
                f"src/noni/{name}.py has a git call with no time limit, which the "
                "section says every one carries"
            )
            token = _first_argv_token(call)
            if token is None:
                # The argv comes from the module's own builder, so the builder is
                # where the program name has to be spelled as git.
                assert '"git", "-C"' in source, (
                    f"src/noni/{name}.py builds its git argv somewhere this check "
                    "cannot read the program name from"
                )
                continue
            assert token == "git", (
                f"src/noni/{name}.py runs {token!r}, and the page says git is the "
                "only program noni runs"
            )
    listing = _module_text("public_safety_scan")
    assert '"git", "-C"' in listing, "the hardened ls-files no longer runs as git -C"


def test_the_section_says_HOME_passes_through_and_reads_pin_the_config() -> None:
    """What the children keep, stated as the environment code actually builds.

    The writer children drop every ``GIT_`` name but the allowlist, so the
    allowlist is read off ``gitenv`` and the page has to say what survives; and
    it names ``HOME``, which is the variable an operator would ask about, because
    git resolves its own configuration and credential helpers with it.
    """
    body = _section()
    assert "HOME" in body, "the section no longer says HOME passes through"
    assert "GIT_" in body, "the section no longer says which variables writers drop"

    allowlist = _module_text("gitenv")
    for kept in ("GIT_AUTHOR_NAME", "GIT_CONFIG_GLOBAL", "GIT_SSH_COMMAND"):
        assert kept in allowlist, f"gitenv no longer keeps {kept} for writer children"
    assert "GIT_CONFIG_GLOBAL" in _module_text("public_safety_scan"), (
        "the ls-files scan no longer pins the global git config"
    )


def test_the_section_puts_the_adapter_outside_itself() -> None:
    """One sentence names integrations/ as outside the statement.

    The audit covered the core and the skill scripts; the adapter was not
    audited, so the page says so rather than letting the statement be read as
    covering it too.
    """
    body = _section()
    assert "integrations/" in body, "the section does not name integrations/ as outside"
    assert body.count("integrations/") == 1, (
        "the outside-the-statement sentence should be one sentence, not a caveat section"
    )


def test_the_section_carries_no_em_dash() -> None:
    """The section's prose follows the page's plain-prose rule.

    Scoped to the section body on purpose: the rest of the page predates this
    ticket and carries the character, and a page-wide assertion would fail for a
    reason the ticket does not own.
    """
    body = _section()
    assert EM_DASH not in body, (
        "the section carries an em dash; the project's prose rule is '--' or a new sentence"
    )
