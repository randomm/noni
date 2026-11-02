"""``_decide_flags`` and ``decide.py`` are one usage contract, not two copies.

The flag rules moved out of decide.py into a module that must not import it (the
writer imports the helper), which is exactly the arrangement that lets the two
drift: a private exit constant, a second date regex, or a printer of the helper's
own would keep every behavioural test green while changing what ``decide``
publishes. These checks pin the shared surface to the writer's own.
"""

from __future__ import annotations

import re

from _harness import REPO

from noni import _decide_flags, decide


def test_the_helper_carries_no_copy_of_decides_usage_code_or_date_shape():
    """The exit code and the message printer come in as arguments, not as copies.

    A second ``EXIT_USAGE`` literal or a second date regex is a contract that can
    drift while every behavioural test stays green, so neither is allowed to
    exist: the helper takes what decide.py hands it and owns no restatement.
    """
    names = {name for name in vars(_decide_flags) if not name.startswith("__")}
    assert "_EXIT_USAGE" not in names, \
        "the helper restates decide's usage exit code instead of taking it"
    assert not hasattr(_decide_flags, "_fail"), \
        "the helper owns a printer of its own instead of the caller's"
    assert _decide_flags.DATE_FLAG_RE.pattern == r"^\d{4}-\d{2}-\d{2}$", \
        _decide_flags.DATE_FLAG_RE.pattern
    source = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    assert not hasattr(decide, "DATE_FLAG_RE"), \
        "decide.py keeps a second date regex no code reads: the --date shape has " \
        "one definition, in the helper that checks it"
    assert "--date" in source  # still documented as this writer's flag


def test_the_helper_refuses_through_the_callers_printer_and_code():
    """Every refusal is printed by decide._fail with decide.EXIT_USAGE.

    The three checks are driven with a recording printer, so what is asserted is
    that the helper passes decide's own code and message shape through, rather
    than a number or a format it invented.
    """
    calls: list[tuple[int, str, str | None]] = []

    def fail(code: int, message: str, hint: str | None = None) -> int:
        calls.append((code, message, hint))
        return code

    assert _decide_flags.parse_date("26-1-1", fail=fail,
                                    exit_usage=decide.EXIT_USAGE)[1] == decide.EXIT_USAGE
    assert _decide_flags.parse_date("2026-02-30", fail=fail,
                                    exit_usage=decide.EXIT_USAGE)[1] == decide.EXIT_USAGE
    assert _decide_flags.parse_questions([], fail=fail,
                                         exit_usage=decide.EXIT_USAGE)[1] == decide.EXIT_USAGE
    assert _decide_flags.parse_questions(["q1"], fail=fail,
                                         exit_usage=decide.EXIT_USAGE)[1] == decide.EXIT_USAGE
    assert _decide_flags.parse_questions(["q1=a", "q1=b"], fail=fail,
                                         exit_usage=decide.EXIT_USAGE)[1] == decide.EXIT_USAGE
    assert _decide_flags.check_supersede("2026-10-01-x", None,
                                         [("q1", "text")], [], fail=fail,
                                         exit_usage=decide.EXIT_USAGE) == decide.EXIT_USAGE
    assert _decide_flags.check_supersede("2026-10-01-x", "2026-10-01",
                                         [("q1", "text")], [], fail=fail,
                                         exit_usage=decide.EXIT_USAGE) == decide.EXIT_USAGE

    assert calls, "no refusal was printed at all"
    assert {code for code, _m, _h in calls} == {decide.EXIT_USAGE}, calls
    assert all(message for _c, message, _h in calls), calls
    # A valid input set prints nothing and returns no code: the caller's
    # ``if refused is not None`` is the only signal.
    calls.clear()
    assert _decide_flags.parse_date("2026-10-26", fail=fail,
                                    exit_usage=decide.EXIT_USAGE) == ("2026-10-26", None)
    assert _decide_flags.parse_questions(["q1=ask"], fail=fail,
                                         exit_usage=decide.EXIT_USAGE) == ([("q1", "ask")], None)
    assert _decide_flags.check_supersede("2026-10-01-x", "2026-10-01",
                                         [("q1", "text")], [("q1", "a")], fail=fail,
                                         exit_usage=decide.EXIT_USAGE) is None
    assert calls == []


def test_the_helper_takes_every_rule_from_its_arguments_and_keeps_none():
    """The usage contract is split across the two files, so one gate owns the seam.

    Three of decide's flag rules live in ``_decide_flags`` and the rest live next
    to the renderer they feed (the slug, the scope, the 2-4-options-per-question
    check, and the rule that only a ``--supersedes`` run carries). That split is
    exactly the arrangement that lets the two halves disagree in silence: a caller
    that stopped handing in its printer, a rule moved without the other side
    noticing, or a fourth rule quietly added to the helper would each leave every
    behavioural test green. These are the assertions that make the split visible:
    every helper call in ``decide.py`` passes the printer and the code, the helper
    imports nothing of decide's, and the rules each side owns are named.
    """
    import ast

    helper = ast.parse((REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8"))
    # The helper must not reach back into its caller: decide imports the helper,
    # and a reverse edge is a cycle the next reader has to untangle by hand.
    imported = {alias.name for node in ast.walk(helper) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module for node in ast.walk(helper)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(part == "decide" for name in imported for part in name.split(".")), \
        f"the helper imports its caller: {imported}"
    reached = [node for node in ast.walk(helper) if isinstance(node, ast.Attribute)
               and node.attr != "parse" and isinstance(node.value, ast.Name)
               and node.value.id == "decide"]
    assert not reached, "the helper reads an attribute off a decide namespace"

    # Every call the caller makes hands in the printer and the exit code: a rule
    # that started refusing through a printer of the helper's own, or with a
    # number of its own, is the drift the rest of this module guards.
    source = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    calls = re.findall(r"_decide_flags\.(\w+)\(([^)]*)\)", source, re.S)
    assert len(calls) >= 3, calls
    for name, arguments in calls:
        assert name in {"parse_date", "parse_questions", "check_supersede"}, name
        assert "fail=_fail" in arguments, f"{name} is called without the caller's printer"
        assert "exit_usage=EXIT_USAGE" in arguments, \
            f"{name} is called without the caller's usage code"


def test_the_supersede_rule_takes_its_two_flags_as_arguments():
    """The contract is visible in the signature: two flag values, not a Namespace.

    Reading ``args.supersedes`` / ``args.date`` off an argparse.Namespace ties the
    helper to a caller that happens to build one, and a rename in decide's
    ``add_argument`` list is invisible until runtime.
    """
    import inspect

    parameters = inspect.signature(_decide_flags.check_supersede).parameters
    assert list(parameters) == ["supersedes", "date", "questions", "answers",
                                "fail", "exit_usage"], list(parameters)
    annotations = {name: str(p.annotation) for name, p in parameters.items()}
    assert "Namespace" not in " ".join(annotations.values()), annotations
    # The caller still refuses before the ledger is touched.
    source = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    assert "check_supersede(args.supersedes, args.date" in source, \
        "decide.py no longer passes the two flags it owns"
