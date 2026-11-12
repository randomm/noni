"""decide.py documents what it exits with: the docstring against the code.

Extracted from the decide writer suite: the parity checks between the module's
docstring and its argparse surface and exit constants."""

import json

from decide_fixtures import (
    NEW_ID,
    _baseline_repo,
    _decide,
    _decide_ast,
    _doc_exit_codes,
    _doc_usage_flags,
    _docstring,
    _module_exit_codes,
    _parser_flags,
    _record_path,
)


def test_docstring_exit_codes_match_the_exit_constants():
    """The docstring's exit table and the EXIT_* constants are one contract,
    pinned to the settled set 0/2/3/4/5."""
    tree = _decide_ast()
    published = _module_exit_codes(tree)
    documented = _doc_exit_codes(_docstring(tree))
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}"
    )
    assert published == {0, 2, 3, 4, 5}, published


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts appears in the Usage block and the block
    names nothing the parser would reject; no --push, --status or --by."""
    tree = _decide_ast()
    parser = _parser_flags(tree) - {"--help"}
    documented = _doc_usage_flags(_docstring(tree))
    assert documented == parser, f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    for forbidden in ("--push", "--status", "--by"):
        assert forbidden not in parser, f"{forbidden} is out of scope for decide.py"


def test_help_names_repo_the_state_root():
    """``decide --help`` calls ``--repo`` the state root, the word the product uses.

    The flag names the tree the writer commits into, which is not always the tree the caller
    stands in (docs/PRODUCT.md 7): "repository root" made a cold start point the writer at a
    code repository, so the help line says what the flag is and the refusal says what to pass.
    """
    tree = _decide_ast()
    help_text = _parser_repo_help(tree)
    assert "the state root" in help_text, help_text
    assert "repository root" not in help_text, help_text


def _parser_repo_help(tree) -> str:
    """The ``--repo`` help string the parser declares, read out of ``main``.

    Read from the source rather than from a launched ``--help``: the flag's help is a string the
    module holds, and a launch would need a tree, an identity and a git run to answer a question
    about one literal.
    """
    import ast

    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    for node in ast.walk(main):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "--repo"):
            for keyword in node.keywords:
                if keyword.arg == "help":
                    return ast.literal_eval(keyword.value)
    raise AssertionError("the parser declares no --repo help string")


def test_record_field_order_and_null_answer_form_are_the_written_shape(tmp_path):
    """The bytes on disk are the documented shape: the eight fields in order,
    source last when present, and answer null (not absent) for an open
    question."""
    repo = _baseline_repo(tmp_path)
    assert _decide(repo, "--source-issue", "7", "--source-comment", "8").returncode == 0
    body = _record_path(repo, NEW_ID).read_text(encoding="utf-8")
    keys = list(json.loads(body))
    assert keys == [
        "id", "date", "asked_by", "questions", "by", "scope", "status", "supersedes", "source",
    ], keys
    assert '"answer": null' in body, body
    assert body.endswith("\n")
