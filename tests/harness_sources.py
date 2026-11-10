"""Reading the product source behind a wrapper for the test harness.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there. The bootstrap (``src/`` on ``sys.path`` plus the bare
package aliases) lives in ``harness_module`` and in ``tests/_harness.py``, which
is the one module that imports it: by the time this file's body runs that import
has finished, so the product source this file reads is this tree's. A helper
module: never named ``test_*``.

"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from harness_paths import SRC


def _script_constant(tree: ast.Module, name: str, origin: str) -> object:
    """One module-level ``NAME = <literal>`` read from an already-parsed script.

    The route for a fixture or an assertion that must hold the value the
    product owns (a row grammar, a set of directory names): the literal is read
    from the shipped file rather than copied, so the two cannot drift.

    Tuples are returned too, not just scalars: a set the product owns (the
    rebase state directories) is a tuple literal, and an assertion set copied
    from it by hand is exactly the drift this helper exists to prevent.
    """
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Constant) or (
            isinstance(value, ast.Tuple) and all(isinstance(e, ast.Constant) for e in value.elts)
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(value, ast.Tuple):
                        return tuple(e.value for e in value.elts)
                    return value.value
    raise AssertionError(f"{origin} defines no module-level constant {name}")


def _script_ast(path: Path) -> ast.Module:
    """Parse ``path`` once and hand the tree to the readers above.

    For a wrapper under ``skills/*/scripts/`` the tree of the package source it
    dispatches to is parsed instead: these readers ask what the *product*
    declares (its exit codes, its parser flags, its docstring), and a wrapper is
    a shim whose own docstring says nothing about the tool's contract. The
    wrapper's source is still read whole by the scrub and presence checks, which
    take a path rather than this helper.
    """
    source = _product_source(path)
    return ast.parse(source.read_text(encoding="utf-8"))


def _harness_source(path: Path) -> str:
    """The text of the product source behind a wrapper path.

    For the checks that read a shipped guard off the source it lives in (a
    compiled regex is a Call, so ``_script_constant`` cannot reach it): they must
    read the package module, since the wrapper is a shim that holds none of the
    tool's logic.
    """
    return _product_source(path).read_text(encoding="utf-8")


def _product_source(path: Path, name: str | None = None) -> Path:
    """The package source behind a wrapper path (identity for a package path).

    A wrapper is recognised by the package module it imports, so the mapping is a
    property of the file rather than a table of paths that can go stale when a
    tool is renamed.

    ``name`` is the module the caller asked for, and where it is given the mapping is
    bounded by it: a module that imports a sibling of its own (the ordering group
    loads its closed-row module beside the census's own code) is not a wrapper for
    that sibling, and trusting the file's first import alone would hand the caller the
    sibling's source under the name it asked for -- a copy of the wrong file, tested as
    though it were the right one. Where the two disagree, the path is the answer.
    """
    text = path.read_text(encoding="utf-8")
    match = re.search(r"from noni import ([a-z_][a-z_0-9]*)\b", text)
    if match is None:
        return path
    candidate = SRC / "noni" / f"{match.group(1)}.py"
    if not candidate.is_file():
        raise AssertionError(
            f"{path} imports noni.{match.group(1)} but {candidate} does not exist"
        )
    if name is not None and candidate != SRC / "noni" / f"{name}.py":
        return path
    return candidate
