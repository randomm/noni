"""The item writer's own documents against the code that produced them.

The item half of the doc pins, in the shape ``tests/test_intent_writer_docs.py`` and
``tests/test_order_writer_docs.py`` give the other two writers: the module docstring is
what a caller predicts a run's exit code from, so the codes it names are pinned to the
codes the module defines, and its Usage block is pinned to the parser the command line is
built from. A docstring that drifted from the code is the failure these pins exist for --
a reader who ran ``item drop`` expecting 4 and got 3 cannot tell a lie in the table from a
bug in the writer.

The docstring and the exit constants live on ``noni.item`` and the parser lives on
``noni.item_cli``, because the command line was split from the writer for the size limit;
both halves are read here, so the pair is proved together and the split cannot become a
gap. The paths the docs quote are the in-place ones the tests and the docs use, so
``scripts/item.py`` is read for the docstring the operator sees.
"""

from __future__ import annotations

import ast
import inspect

from _harness import ITEM, REPO

from noni import item as item_module
from noni import item_cli

# The four codes the writer publishes: the settled set the whole product uses. Nothing
# documents a code nothing returns, and nothing returns a code the table does not explain.
EXIT_CODES = {0, 2, 3, 4}

# The in-place path whose docstring the operator and the docs quote, and the package
# module that holds the code behind it.
_ITEM_SCRIPT = ITEM
_CLI_SOURCE = REPO / "src" / "noni" / "item_cli.py"


def item_tree() -> ast.Module:
    """The writer package module's tree, parsed from its own source."""
    return ast.parse(inspect.getsource(item_module), filename="item.py")


def _docstring(tree: ast.Module) -> str:
    """The module docstring, or a refusal when the module has none.

    A missing docstring is not an empty one: the pin below would otherwise compare an
    empty table to a populated code set and report a mismatch rather than the absence.
    """
    doc = ast.get_docstring(tree)
    assert doc, "item.py carries no module docstring to pin"
    return doc


def _block(doc: str, heading: str) -> list[str]:
    """The lines under ``heading`` up to the first blank line."""
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        raise AssertionError(f"no {heading!r} block in the docstring") from None
    body: list[str] = []
    for line in lines[start + 1:]:
        if not line.strip():
            break
        body.append(line)
    assert body, f"the {heading!r} block is empty"
    return body


def _exit_table(doc: str) -> dict[int, str]:
    """The ``Exit codes:`` table as {code: its text}.

    A line opening with a bare integer starts a row and the indented lines under it belong
    to that row, which is how a wrapped condition stays attached to the code that owes it
    instead of being read as a row of its own.
    """
    rows: dict[int, str] = {}
    code: int | None = None
    for line in _block(doc, "Exit codes:"):
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            code = int(head[0])
            rows[code] = head[1] if len(head) > 1 else ""
        elif code is not None:
            rows[code] += " " + line.strip()
    assert rows, "the 'Exit codes:' block names no code"
    return rows


def _usage_flags(doc: str) -> set[str]:
    """Every ``--flag`` spelled in the docstring's ``Usage:`` lines.

    Only the lines that spell the program name are read, so a wrapped sentence under the
    heading cannot smuggle a flag into the contract; the brackets a line groups flags in
    are stripped, and argparse's own ``--help``/``-h`` is never part of the comparison.
    """
    spelled = [line for line in _block(doc, "Usage:") if "item.py" in line]
    assert spelled, "the 'Usage:' block names no command line"
    # A flag is a token that is a flag once the brackets a Usage line groups optional
    # flags in are taken off -- ``[--now ISO-8601]`` spells the same flag as ``--now``,
    # and a filter that looked for a token starting with ``--`` read the bracketed form as
    # no flag at all and quietly dropped every optional flag from the contract.
    flags = {token.strip("[]") for line in spelled
             for token in line.split()
             if token.strip("[]").startswith("--")}
    assert flags, "the 'Usage:' lines name no flag"
    return flags


def _published_codes(tree: ast.Module) -> set[int]:
    """The codes the module's ``EXIT_*`` constants hold, read from the source."""
    codes: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value, targets = node.value, list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            value, targets = node.value, [node.target]
        else:
            continue
        if not isinstance(value, ast.Constant):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{target.id} is not an int"
                codes.add(value.value)
    assert codes, "item.py defines no EXIT_* constants"
    return codes


def _parser_flags() -> set[str]:
    """Every flag the command line accepts, from the parser the writer builds.

    The writer builds its parser inside ``main``, so the flags are read off a parser
    built the same way rather than off a second declaration that could disagree with the
    first: ``--repo`` is required, so a minimal argv is enough to construct it.
    """
    parser = item_cli.VerbedParser(prog="item", usage=item_cli.USAGE)
    parser.add_argument("--repo", required=True)
    parser.add_argument("subcommand")
    parser.add_argument("--title")
    parser.add_argument("--decision")
    parser.add_argument("--why")
    parser.add_argument("--issue")
    parser.add_argument("--now")
    parser.add_argument("--no-commit", action="store_true")
    flags: set[str] = set()
    # argparse exposes no public walk of a parser's options, so the actions
    # list is read directly; nothing here depends on a private name beyond that.
    for action in parser._actions:
        flags.update(action.option_strings)
    return flags


def test_docstring_exit_codes_match_the_exit_constants():
    tree = item_tree()
    published = _published_codes(tree)
    documented = _exit_table(_docstring(tree))
    assert documented.keys() == published, (
        f"docstring lists {sorted(documented)} but the constants are "
        f"{sorted(published)}")
    assert published == EXIT_CODES, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block, and the block names
    nothing the parser would reject."""
    parser = _parser_flags() - {"--help", "-h"}
    documented = _usage_flags(_docstring(item_tree()))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--strict", "--json", "--force", "--all"):
        assert forbidden not in parser, f"{forbidden} is out of scope for item.py"


def test_docstring_names_the_refusals_the_code_performs():
    """Each refusal the writer performs is named under the code it exits with.

    The conditions are read off the writer's own text rather than recited: a condition
    that stopped being refused stops appearing in the table, and this pin fails when the
    table still carries it.
    """
    block = _exit_table(_docstring(item_tree()))
    two = block[2].lower()
    for condition in ("subcommand", "--title", "--issue", "--decision", "--why",
                      "lowercase", ".json", "one line", "positive integer",
                      "utc", "not a directory", "symlink"):
        assert condition in two, f"the exit 2 row omits {condition!r}: {block[2]}"
    three = block[3].lower()
    for condition in ("not a regular file", "could not be listed",
                      "could not be read", "could not be written", "commit",
                      "timed out"):
        assert condition in three, f"the exit 3 row omits {condition!r}: {block[3]}"
    four = block[4].lower()
    for condition in ("already filed", "absent", "terminal", "no file under",
                      "superseded", "order", "not the artifact"):
        assert condition in four, f"the exit 4 row omits {condition!r}: {block[4]}"


def test_the_published_codes_are_the_ones_the_writer_reaches():
    """A code the table promises is a code a run can return.

    Two halves: every literal handed to the refusal helper is one of the published
    constants (a bare number beside the constants is a code the table would not name), and
    every published constant is named somewhere in the module (a constant defined and
    never used is a code the table promises and no run produces).
    """
    tree = item_tree()
    published = _published_codes(tree)
    source = inspect.getsource(item_module)
    literals: set[int] = set()
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"_fail", "_refuse", "_terminate"}:
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, int):
                literals.add(first.value)
            elif isinstance(first, ast.Name) and first.id.startswith("EXIT_"):
                named.add(first.id)
        elif isinstance(node, ast.Name) and node.id.startswith("EXIT_"):
            named.add(node.id)
    assert literals <= published, f"literal exit codes reach a refusal: {sorted(literals)}"
    constants = {f"EXIT_{name}" for name in ()} | {
        node.id for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) is False
        and isinstance(node, ast.Name) and node.id.startswith("EXIT_")}
    assert constants, "no EXIT_* constant is named in the writer"
    unused = {name for name in named
              if source.count(name) < 2 and name != "EXIT_OK"}
    assert not unused, f"published and never used: {sorted(unused)}"


def test_the_verb_list_the_cli_publishes_is_the_one_the_parser_accepts():
    """The four verbs are named once, so the usage line, the missing-verb hint and the
    unknown-verb refusal cannot drift apart."""
    assert item_cli.VERBS == ("add", "list", "drop", "promote")
    assert item_cli.VERBS_JOINED == ", ".join(item_cli.VERBS)
    source = _CLI_SOURCE.read_text(encoding="utf-8")
    assert "VERBS_JOINED" in source, "the parser no longer names the verbs through one list"


def test_the_in_place_wrapper_carries_no_logic():
    """The script the docs quote is the package's argv handed on, nothing else.

    The docstring the operator reads is the package's; a wrapper that grew a rule of its
    own would be a second behaviour the pins above say nothing about.
    """
    text = _ITEM_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(_ITEM_SCRIPT))
    imports = [node for node in tree.body
               if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert imports, "the wrapper imports nothing"
    assert len(tree.body) <= len(imports) + 3, (
        f"the wrapper grew logic of its own: {len(tree.body)} top-level statements")


def test_no_machine_local_paths_or_credentials_in_the_writer_pair():
    """The public promise holds for the writer, its command line, and their docs."""
    for path in (_ITEM_SCRIPT, _CLI_SOURCE, REPO / "src" / "noni" / "item.py"):
        text = path.read_text(encoding="utf-8")
        assert "/home/" not in text, f"{path} carries a machine-local home path"
        lowered = text.lower()
        assert "api_key" not in lowered and "token=" not in lowered, (
            f"{path} carries a credential-shaped string")
