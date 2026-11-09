"""The rationale rule: the one statement a ``why`` value answers to.

Three artifacts of the product hold a rationale and all three read this module: a
decision record's ``why``, an order entry's ``why``, and an item's reason. One owner
is what keeps a value one writer committed from being refused by the arbiter that
reads it -- the symptom of a drift is a record the writer happily wrote and the
census then reports at exit 10, which no verb can repair because no verb will open a
file its own writer refuses to re-render.

Two rules and one wording. The shape is :func:`noni.ledger_schema.is_single_line` --
the same predicate the two attribution names and an item's title answer to -- so a
rationale cannot smuggle a second line into a report or a log line. The bound is
:data:`noni.itemschema.WHY_MAX`, counted over code points by ``len`` of the string
and not over bytes, so a value of combining marks or emoji is measured the way its
author measures it.

Nothing here prints, exits or appends a finding: these are predicates and problem
strings, and each caller words its own refusal. Both neighbours are reached by
:func:`_neighbour` rather than imported at load time: ``itemschema`` imports
``ledger_schema`` for its own single-line rule, so an import of it at load time here
would close a cycle between the two schemas.
"""

from __future__ import annotations

# The two neighbours this rule reads, resolved the way this module itself is reached.
# Both load paths have to work: the package route takes the ordinary import, and the
# route that loads one file of this family by path (the test harness, and any consumer
# of a skill's ``scripts/`` copy) lands in a module with no package, where a relative
# import at load time would be an ``ImportError``. A bare-module load also leaves
# ``__file__`` pointing at wherever the loader chose, so a neighbour is looked for
# beside this file first and then in the source tree's package directory.
_IMPORT_ERROR = ImportError
_ITEM_SEARCH = ("", "noni")


def _neighbour(name: str):
    """Import the package module ``name``, by either route this file is loaded by."""
    try:
        package = __package__ or ""
        return __import__(f"{package}.{name}" if package else name,
                          fromlist=[name])
    except _IMPORT_ERROR:
        import importlib.util
        import sys
        from pathlib import Path

        here = Path(__file__).resolve().parent
        roots = [here] + [here.parent / part for part in _ITEM_SEARCH
                          if (here.parent / part / f"{name}.py").is_file()]
        for root in roots:
            source = root / f"{name}.py"
            if not source.is_file():
                continue
            spec = importlib.util.spec_from_file_location(f"_why_{name}", source)
            if spec is None or spec.loader is None:  # pragma: no cover - fixed path
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        raise



def why_max() -> int:
    """The rationale bound, read from the one module that owns the number.

    The number lives beside the item store's reason field: one rationale bound for
    the whole product, spelled once. A second literal anywhere is how a writer and
    the census come to disagree about a value one of them wrote, and is how a doc
    page comes to state a bound no code enforces.
    """
    return _neighbour("itemschema").WHY_MAX


def is_bounded_single_line(value: object, maximum: int) -> bool:
    """Whether ``value`` is one non-blank line of at most ``maximum`` code points.

    The two rules a rationale answers to as one predicate, for a caller that asks
    shape and bound in a single question -- which is what a writer's flag check
    wants. :func:`noni.ledger_schema.is_single_line` keeps its one-argument
    signature and the bound is asked separately here: the two attribution name
    fields share that predicate and carry no length bound at all, so a length
    parameter on it would be a rule they never asked for. The bound is compared with
    ``len`` of the string, so it counts code points and not bytes: an operator
    measuring a limit measures the text they see.

    The bound is an argument and not a constant read here, for the reason
    :func:`why_problems` gives: the number belongs to the artifact that declares it.
    """
    schema = _neighbour("ledger_schema")
    return schema.is_single_line(value) and len(value) <= maximum


def why_problems(record: dict) -> list[str]:
    """What ``record``'s ``why`` gets wrong, as problem strings naming the field.

    The writer's flag, the ledger census's record pass, the ordering census's entry
    pass and the supersede-target read all ask this one question of a rationale, so
    a value one of them refuses is refused by all four and worded the same way. Both
    halves come from the schemas rather than from this module's own idea of a line.

    Total on the record: no ``why`` key is no rationale and answers no problem, so a
    caller never has to ask whether it may call this. A non-string is refused by the
    shape arm and ``len`` is never asked of a number, a boolean or a null, which is
    what keeps a reader reporting a finding instead of faulting on the value.
    """
    schema = _neighbour("ledger_schema")

    if WHY_FIELD not in record:
        return []
    value = record[WHY_FIELD]
    if not schema.is_single_line(value):
        return [f"{WHY_FIELD} must be a non-empty single-line string"]
    maximum = why_max()
    if len(value) > maximum:
        return [f"{WHY_FIELD} is {len(value)} characters, past the {maximum} limit"]
    return []


# The key a rationale is written under: a decision record's field, an order entry's
# field, and the name every refusal and every census row prints for it. Named once,
# beside the rule that reads it, so the module that states the ``why`` rule is also
# the module that names the field.
WHY_FIELD = "why"
