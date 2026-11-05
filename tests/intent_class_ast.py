"""The ``census_intent`` module parsed, for the pins that are about structure.

A source-text substring pin constrains spelling: renaming a local, hoisting a
helper, or moving a function below another one breaks it, and an ordering check
can pass merely because a reader happens to be defined after the class. Reading
``lineno`` off the syntax tree constrains the behaviour and nothing else, which is
what a pin that must survive a refactor is for.

The helpers are plain functions and the two fixtures are the same functions
wrapped by pytest's decorator at the bottom of this file, so a module that imports
the helpers is not obliged to import the fixture too. A helper module, never named
``test_*``, so pytest never collects it: the fixtures here are consumed by the
intent test files that pin the reader's structure. Mirrors
``tests/harness_sources.py``, which parses the shipped product source the same way.
"""

from __future__ import annotations

import ast
from pathlib import Path


def function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """The module-level function ``name``, with a message when it is gone."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"census_intent.py defines no function {name}")


def call_line(tree: ast.Module, func: str, callee: str) -> int:
    """The line where ``func`` calls ``callee``, or a failure naming both.

    The message is the point: a bare ``ValueError`` from a substring search, or a
    bare ``StopIteration`` from ``next``, reports a reworded token as an unexplained
    error rather than as the invariant that stopped holding.
    """
    body = function(tree, func)
    for node in ast.walk(body):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                == callee):
            return node.lineno
    raise AssertionError(f"{func}() no longer calls {callee}(), so the invariant "
                         "this pin exists for is not the code any more")


def return_line(tree: ast.Module, func: str, *, after: int) -> int:
    """The first ``return`` inside ``func`` at or after line ``after``."""
    body = function(tree, func)
    lines = sorted(node.lineno for node in ast.walk(body)
                   if isinstance(node, ast.Return) and node.lineno >= after)
    if not lines:
        raise AssertionError(f"{func}() returns nothing after line {after}, so the "
                             "refusal this pin guards has been removed")
    return lines[0]


def function_source(tree: ast.Module, name: str, source: str) -> str:
    """The text of the module-level function ``name`` in ``source``."""
    return ast.get_source_segment(source, function(tree, name)) or ""


def compare_against(tree: ast.Module, func: str, operand: str) -> set[tuple[str, object]]:
    """Every ``(operator, literal)`` ``func`` compares ``operand`` against.

    For a gate that must name the answer it accepts: an allow-list of the values a
    caller happens to handle is invisible to a test that only runs today's states,
    so the shape is read off the tree instead.
    """
    return {
        (type(node.ops[0]).__name__, node.comparators[0].value)
        for node in ast.walk(function(tree, func))
        if isinstance(node, ast.Compare) and len(node.ops) == 1
        and isinstance(node.left, ast.Name) and node.left.id == operand
        and isinstance(node.comparators[0], ast.Constant)
    }


# --- The pytest fixtures, defined last so an import of a helper above is not an
# import of pytest. Each is a ``pytest.fixture``-decorated function whose *name* is
# what the test module asks pytest for, so the importing test file must name the
# fixture in its own module namespace (the project's convention: every fixture is
# defined in the test module or a conftest, not smuggled in through an import).


def _intent_class_text() -> str:
    """The source text of the module that owns the intent class.

    Two of the intent suite's faults are not portable filesystem states, and the
    census runs as a subprocess, so a monkeypatch cannot reach the reader either.
    What is left is to pin the handling itself.
    """
    import noni.census_intent

    return Path(noni.census_intent.__file__).read_text(encoding="utf-8")


def _intent_module(intent_class: str) -> ast.Module:
    """The same module parsed once, beside the text its pins quote."""
    return ast.parse(intent_class)


# Imported by the test modules and decorated there, so pytest sees a fixture it
# can resolve by name in the module that requests it.
intent_class_text = _intent_class_text
intent_module = _intent_module
