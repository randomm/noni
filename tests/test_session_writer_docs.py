"""The two new writers' docstrings, tables and EXIT_* constants are one contract.

close.py and release.py publish their exit codes three times: as ``EXIT_*``
constants, in the module docstring's ``Exit codes:`` block, and in the operator-
facing markdown (``skills/sessions-claims/SKILL.md`` and the lifecycle section of
``references/register.md``). Nothing but the checks below keeps the three
copies in step, which is why the reviewer's finding that both writers collapsed
the rebase codes into exit 3 while their tables omitted 5 and 6 was invisible to
the suite.

The readers parse the source with ``ast`` rather than importing it, mirroring
``tests/test_claim_validation.py``: these are scripts the suite otherwise drives
as subprocesses, and an import would let a module-level side effect run inside
the test process.

Claim's own parity test is ``test_claim_validation.py``'s; the ``{0..6}`` set
asserted here is that same PM-settled table, restated for the two verbs that
now share it.
"""

from __future__ import annotations

import ast
import re

from _harness import CLOSE, RELEASE, REPO, _script_ast

# The four writers share the git-write helper and, for the push path, claim's
# exit-code split; the docs that carry their tables are the operator contract.
SKILL_MD = REPO / "skills" / "sessions-claims" / "SKILL.md"
REGISTER_REF = REPO / "skills" / "sessions-claims" / "references" / "register.md"

WRITERS: tuple[tuple[str, object], ...] = (("close", CLOSE), ("release", RELEASE))

# The codes both writers publish: 0-4 for their own faults and 5/6 for the two
# rebase verdicts fetch_rebase_push classifies (claim.py's settled split, #22).
PUBLISHED: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5, 6})


def _docstring(tree: ast.Module, origin: str) -> str:
    """The module docstring, typed before use (ast returns Optional[str])."""
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), f"{origin} has no module docstring"
    return doc


def _module_exit_codes(tree: ast.Module, origin: str) -> set[int]:
    """The codes the ``EXIT_*`` module constants hold.

    Read from the syntax tree so a constant that drifted to ``True`` (a bool is
    an int subclass) is caught rather than counted: ``type() is int``.
    """
    codes: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{origin}: {target.id} is not an int"
                codes.add(value.value)
    assert codes, f"{origin} defines no EXIT_* constants"
    return codes


def _block_lines(doc: str, header: str, origin: str) -> list[str]:
    """The indented lines directly under ``header`` in the docstring."""
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        raise AssertionError(f"{origin} docstring has no {header!r} block") from None
    body: list[str] = []
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        body.append(line)
    assert body, f"{origin} docstring's {header!r} block is empty"
    return body


def _docstring_exit_codes(doc: str, origin: str) -> set[int]:
    """The leading numbers of the 'Exit codes:' block's rows."""
    codes: set[int] = set()
    for line in _block_lines(doc, "Exit codes:", origin):
        if not line.strip():
            continue
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            codes.add(int(head[0]))
    assert codes, f"{origin}: the 'Exit codes:' block lists no codes"
    return codes


def _docstring_usage_flags(doc: str, origin: str) -> set[str]:
    """Every ``--flag`` token in the 'Usage:' block."""
    flags: set[str] = set()
    for line in _block_lines(doc, "Usage:", origin):
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, f"{origin}: the 'Usage:' block names no flags"
    return flags


def _parser_flags(tree: ast.Module, origin: str) -> set[str]:
    """The long option strings main()'s argparse parser declares."""
    main = next((n for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main is not None, f"{origin} has no top-level main()"
    flags: set[str] = set()
    for node in ast.walk(main):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value)
    assert flags, f"{origin}: main() declares no arguments"
    return flags


def _skill_exit_codes(verb: str) -> set[int]:
    """The codes of the one 'Exit codes:' sentence under the verb's own heading."""
    text = SKILL_MD.read_text(encoding="utf-8")
    heading = {"close": "## Closing a session", "release": "## Releasing a claim"}[verb]
    start = text.index(heading)
    rest = text[start:]
    nxt = rest.find("\n## ", len(heading))
    section = rest[:nxt] if nxt > 0 else rest
    match = re.search(r"^Exit codes:(.*?)(?:\n\n|\Z)", section,
                      re.MULTILINE | re.DOTALL)
    assert match, f"SKILL.md's {heading} section has no 'Exit codes:' sentence"
    codes = {int(n) for n in re.findall(r"`(\d)`", match.group(1))}
    assert codes, f"SKILL.md's {heading} exit sentence names no codes"
    return codes


def _register_ref_lifecycle_codes() -> set[int]:
    """The rebase codes the lifecycle section of references/register.md names."""
    text = REGISTER_REF.read_text(encoding="utf-8")
    start = text.index("## Lifecycle")
    section = text[start:]
    return {int(n) for n in re.findall(r"exit (\d)", section)}


def _test_writer(verb: str, script) -> ast.Module:
    """Shared body: constants, docstring table and Usage flags for one writer."""
    tree = _script_ast(script)
    doc = _docstring(tree, f"{verb}.py")
    published = _module_exit_codes(tree, f"{verb}.py")
    documented = _docstring_exit_codes(doc, f"{verb}.py")
    assert documented == published, (
        f"{verb}.py's docstring lists {sorted(documented)} but its EXIT_* "
        f"constants are {sorted(published)}"
    )
    # Both verbs share claim.py's contract, so a code that quietly disappeared
    # from either writer fails here before it fails an agent scripting on it.
    assert published == set(PUBLISHED), (
        f"{verb}.py publishes {sorted(published)}, expected the shared "
        f"{sorted(PUBLISHED)}"
    )
    return tree


def test_close_docstring_table_matches_its_exit_constants():
    """close.py's EXIT_* set, its docstring table and the PM-settled 0-6 are one."""
    _test_writer("close", CLOSE)


def test_release_docstring_table_matches_its_exit_constants():
    """release.py's EXIT_* set, its docstring table and the PM-settled 0-6 are one."""
    _test_writer("release", RELEASE)


def test_close_usage_flags_match_its_parser():
    """Nothing in close.py's Usage block is a flag its parser would reject, and
    nothing the parser accepts is missing from the block."""
    tree = _script_ast(CLOSE)
    parser = _parser_flags(tree, "close.py") - {"--help"}
    documented = _docstring_usage_flags(_docstring(tree, "close.py"), "close.py")
    assert documented == parser, f"Usage {sorted(documented)} vs parser {sorted(parser)}"


def test_release_usage_flags_match_its_parser():
    """The same parity for release.py, whose --task is the flag the pair adds."""
    tree = _script_ast(RELEASE)
    parser = _parser_flags(tree, "release.py") - {"--help"}
    documented = _docstring_usage_flags(_docstring(tree, "release.py"), "release.py")
    assert documented == parser, f"Usage {sorted(documented)} vs parser {sorted(parser)}"


def test_skill_md_exit_sentences_publish_the_rebase_codes():
    """The operator-facing sentences name 5 and 6, not just 0-4.

    The docstring parity above says nothing about the markdown, which is the
    half an operator reads; a table that omits the rebase codes while the code
    returns them sends an agent to retry a push it should not retry.
    """
    for verb in ("close", "release"):
        codes = _skill_exit_codes(verb)
        assert codes == set(PUBLISHED), (
            f"SKILL.md's {verb} exit sentence lists {sorted(codes)}, expected "
            f"{sorted(PUBLISHED)}"
        )


def test_register_reference_names_the_rebase_codes_for_both_verbs():
    """references/register.md's lifecycle section points both verbs at 5 and 6."""
    codes = _register_ref_lifecycle_codes()
    assert {3, 5, 6} <= codes, (
        f"references/register.md's Lifecycle section names {sorted(codes)}; the "
        f"push contract needs 3, 5 and 6 for both verbs"
    )


def test_the_rebase_verdicts_are_passed_through_not_collapsed():
    """The two writers hand the helper three distinct codes.

    Passing EXIT_PUSH_FAILED for all three arguments is the exact shape the
    reviewer found: the helper classifies the two rebase verdicts and the
    writer throws the distinction away before the operator sees it.
    """
    for verb, script in WRITERS:
        tree = _script_ast(script)
        call = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "fetch_rebase_push"), None)
        assert call is not None, f"{verb}.py never calls fetch_rebase_push"
        given = {kw.arg: kw.value for kw in call.keywords
                 if kw.arg in ("exit_push_failed", "exit_rebase_conflict",
                               "exit_rebase_refused")}
        assert set(given) == {"exit_push_failed", "exit_rebase_conflict",
                              "exit_rebase_refused"}, (
            f"{verb}.py calls fetch_rebase_push with {sorted(given)}")
        named = {arg: getattr(given[arg], "attr", None) or getattr(
            given[arg], "id", None) for arg in given}
        assert named["exit_rebase_conflict"] == "EXIT_REBASE_CONFLICT", (
            f"{verb}.py passes {named['exit_rebase_conflict']} for the conflict "
            "code instead of its own EXIT_REBASE_CONFLICT")
        assert named["exit_rebase_refused"] == "EXIT_REBASE_REFUSED", (
            f"{verb}.py passes {named['exit_rebase_refused']} for the refusal "
            "code instead of its own EXIT_REBASE_REFUSED")


def test_the_push_exit_constants_agree_with_claims_across_the_writers():
    """One number per verdict for all three writers that push.

    An agent that scripts ``rc == 5 -> resolve the file`` against claim.py must
    get the same answer from close.py and release.py, so the three constants
    are compared rather than each being pinned to a literal a fourth time.
    """
    from noni import claim as claim_mod
    from noni import close as close_mod
    from noni import release as release_mod

    for name in ("EXIT_REBASE_CONFLICT", "EXIT_REBASE_REFUSED"):
        values = {getattr(mod, name) for mod in (claim_mod, close_mod, release_mod)}
        assert len(values) == 1, f"{name} differs across writers: {values}"
    # And the settled numbers, so a rename that kept them equal but moved both
    # off claim's published table is still caught.
    assert claim_mod.EXIT_REBASE_CONFLICT == 5
    assert claim_mod.EXIT_REBASE_REFUSED == 6


def test_the_writers_publish_their_constants_without_importing_them():
    """No writer re-exports claim's constants: each owns its own table.

    A shared import would make close.py's exit table change when claim.py's
    did, which is the coupling the per-writer EXIT_* constants exist to avoid.
    """
    for verb, script in WRITERS:
        source = _script_ast(script)
        imported = {alias.name for node in ast.walk(source)
                    if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert "EXIT_REBASE_CONFLICT" not in imported, (
            f"{verb}.py imports the conflict code instead of publishing it")
