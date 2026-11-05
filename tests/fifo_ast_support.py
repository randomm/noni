"""The hygiene scan's own open, read off the syntax tree.

Two properties of the guarded open are not states a fixture can produce, and no
filesystem test can tell them apart from a scan that got lucky:

- **The order.** A separate ``lstat``/``stat`` of the path and a later ``open``
  leave an interval in which a regular file is swapped for a pipe after the check
  and is still opened for reading. The promise holds only while the mode is read
  off the descriptor the scan itself opened, which is a fact about two statements
  in one function -- so it is read off the tree, where a refactor that keeps the
  behaviour keeps passing.
- **The flags.** ``O_NONBLOCK`` must be on the flags argument of the one ``os.open``
  that guards the read: a separate ``fcntl`` call after the open is too late, since
  the open itself is what blocks on a pipe with no writer. And ``O_NOFOLLOW`` must
  be *absent*: it raises ELOOP on a tracked symlink and would silently skip
  legitimate tracked content.

The filesystem states themselves -- a tracked pipe, a link to one, an untracked
pipe, a violation planted beside a pipe -- are asserted for behaviour in
``tests/test_public_safety_fifo.py``, which is the mutation-checked half. The AST
pins are not a substitute for it: they say the code has the shape, only the
behavioural tests say the shape works. Mirrors ``tests/intent_class_ast.py``,
which pins the intent reader's open the same way.

A helper module, never named ``test_*``.
"""

from __future__ import annotations

import ast
from pathlib import Path


def public_safety_text() -> str:
    """The source of the module that owns the scan's opens.

    Read from the imported package module rather than from a path the caller builds, so a
    pin cannot be satisfied by a copy of the checker no scan runs. The guarded open lives
    in ``noni.public_safety_io`` since the #91 split, so that module's text is what the
    open's pins read; the scan itself stays in ``noni.public_safety``.
    """
    import noni.public_safety
    import noni.public_safety_io

    return (Path(noni.public_safety.__file__).read_text(encoding="utf-8")
            + "\n" + Path(noni.public_safety_io.__file__).read_text(encoding="utf-8"))


def public_safety_module(source: str) -> ast.Module:
    """That module parsed, beside the text its pins quote."""
    return ast.parse(source)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """The module-level function ``name``, in either module of the scan.

    A missing function is an invariant that stopped holding, not a ``None`` to be
    dereferenced by the caller, so the message is raised rather than returned.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"public_safety defines no function {name}, so the "
                         "invariant this pin exists for is not the code any more")


def call_line(tree: ast.Module, func: str, callee: str) -> int:
    """The line where ``func`` calls ``callee``, or a failure naming both.

    The message is the point: a bare ``StopIteration`` from ``next`` or a
    ``ValueError`` from a substring search reports a renamed helper as an
    unexplained error rather than as the invariant that stopped holding.
    """
    body = _function(tree, func)
    for node in ast.walk(body):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None)) == callee):
            return node.lineno
    raise AssertionError(f"{func}() no longer calls {callee}(), so the order this "
                         "pin guards is not the code any more")


def function_source(name: str, source: str) -> str:
    """The text of the function ``name`` in the concatenated source of the scan."""
    return ast.get_source_segment(source, _function(public_safety_module(source), name)) or ""
