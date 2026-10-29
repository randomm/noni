"""claim.py documents what it exits with: the docstring against the code.

Extracted from the claim suite: the parity checks between the module's docstring
and its argparse surface, its exit constants, and the harness that runs it."""

import ast

from _harness import (
    REPO,
)
from claim_fixtures import (
    _claim_docstring,
    _claim_tree,
    _docstring_exit_codes,
    _docstring_usage_flags,
    _markdown_exit_codes,
    _module_exit_codes,
    _parser_flags,
)


def _parser_dests(tree: ast.Module) -> dict[str, str]:
    """Map each long option string to the attribute name its action writes.

    The dash spelling alone is not the whole contract: claim.py reads
    ``args.no_commit``, so the dest is the other half and is what an alias or a
    renamed dest would silently break.
    """
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    dests: dict[str, str] = {}
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            opts = [
                arg.value for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and arg.value.startswith("--")
            ]
            dest = next(
                (
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)
                ),
                None,
            )
            if dest is None and opts:
                # argparse's own rule: the first long option, dashes to
                # underscores.
                dest = opts[0].lstrip("-").replace("-", "_")
            if dest:
                for opt in opts:
                    dests[opt] = dest
    return dests


def test_docstring_exit_codes_match_the_exit_constants():
    """The docstring's exit table, the markdown tables and the EXIT_* constants
    are one contract: the same set of codes, pinned to PM's settled 0-6."""
    tree = _claim_tree()
    documented = _docstring_exit_codes(_claim_docstring(tree))
    published = _module_exit_codes(tree)
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}"
    )
    # PM's settled table, so a constant that quietly changes code fails here
    # rather than only in the tests that read the number.
    assert published == {0, 1, 2, 3, 4, 5, 6}
    # The two markdown copies are the operator-facing contract; the docstring
    # parity above says nothing about them, so they are parsed against the same
    # set. references/claim.md carries the one full table; SKILL.md keeps its
    # own copy for the operator who reads only the skill.
    for path in (
        REPO / "skills" / "sessions-claims" / "SKILL.md",
        REPO / "skills" / "sessions-claims" / "references" / "claim.md",
    ):
        markdown = _markdown_exit_codes(
            path.read_text(encoding="utf-8"), path.name, only=published
        )
        assert markdown == published, (
            f"{path.name} lists {sorted(markdown)} of the claim codes but the "
            f"constants are {sorted(published)}"
        )


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts is documented in the Usage block,
    the block names nothing the parser would reject, and each flag writes the
    attribute name the code reads."""
    tree = _claim_tree()
    parser = _parser_flags(tree) - {"--help"}
    documented = _docstring_usage_flags(_claim_docstring(tree))
    assert documented == parser, (
        f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    )
    # The dash spelling is only half the contract: claim.py reads
    # args.no_commit and args.session_id, so the dest is asserted too.
    dests = _parser_dests(tree)
    assert dests["--no-commit"] == "no_commit", dests
    assert dests["--session-id"] == "session_id", dests
    assert dests["--push"] == "push", dests


def test_no_commit_is_a_real_option_of_claim_parser():
    """--no-commit is a flag claim.py's own parser declares (so the harness can
    forward it and the --push combination can be refused), read from the product
    rather than from a parser this test builds: the behaviour itself is covered
    by the --no-commit tests and the Usage-block parity test above."""
    flags = _parser_flags(_claim_tree())
    assert "--no-commit" in flags, f"claim.py declares {sorted(flags)}"
    assert "--push" in flags, f"claim.py declares {sorted(flags)}"
