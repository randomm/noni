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


def _call_arguments(source: str, qualified: str, call_site: str = "") -> str:
    """The argument text of the call to ``qualified``, skipping definitions and prose.

    ``qualified`` is spelled as the source spells it (``parse_date(`` inside the
    helper, where the rule is called unqualified). A rule's own signature is a
    ``def`` line and is skipped: a signature names its parameters, it does not pass
    a printer. A docstring that cites the rule with ``:func:`` markup is skipped the
    same way -- the sentence "``:func:`refuse_linked_state` asks``" is a mention, not
    a call, and the parenthesis that follows it in prose is not a call either.
    ``call_site`` narrows the search to one caller (the writer's own printer, say),
    so a module that both defines a rule and calls a like-named one hands back the
    call and not its own signature.

    The balanced-paren scan starts at the paren that follows the name, so a keyword
    argument that is itself a call does not end the read early -- the property a plain
    ``[^)]*`` regex could not give for the assembly call, which forwards several call
    expressions as values.
    """
    at = 0
    while (found := source.find(qualified, at)) != -1:
        at = found + 1
        head = source[max(0, found - 20):found].rstrip()
        if head.endswith("def") or head.endswith("`"):
            continue
        open_at = found + len(qualified) - 1
        if source[open_at] != "(":
            continue
        arguments = _balanced_arguments(source, open_at)
        if not call_site or call_site in arguments:
            return arguments
    return ""


def _balanced_arguments(source: str, open_at: int) -> str:
    """The text between ``source[open_at]`` and the paren that closes it."""
    depth, index = 0, open_at
    while index < len(source):
        char = source[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return source[open_at + 1:index]


def _helper_calls(source: str) -> list[tuple[str, str]]:
    """Every ``_decide_flags.<rule>(...)`` call in ``source``, with its argument text.

    Balanced-paren scanner rather than a ``[^)]*`` regex: the assembly call forwards
    keyword arguments whose values are themselves calls, and a regex stops at the
    first closing paren and reports a call whose arguments were never seen. The
    scanner reads from each call's opening paren to the paren that closes it, so the
    argument text it hands back is what the caller actually passed.
    """
    needle = "_decide_flags."
    found: list[tuple[str, str]] = []
    at = 0
    while (start := source.find(needle, at)) != -1:
        at = start + len(needle)
        open_at = source.find("(", at)
        if open_at == -1:
            break
        head = source[at:open_at].strip()
        if "(" in head or "\n" in head or "." in head or not head.isidentifier():
            # A mention, not a call: a docstring that cites the rule by name (with
            # or without the cross-reference markup) or a bare attribute handed to
            # another helper. Neither passes a printer, so neither is one, and the
            # search resumes just after the needle so a real call further along is
            # still found.
            continue
        depth, index = 0, open_at
        while index < len(source):
            char = source[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        found.append((head, source[open_at + 1:index]))
        at = index
    return found


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
    helper_source = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    # Both sides of the seam are read, each by its own rule. The CALLER's calls carry
    # the literals: a rule that stopped being handed the writer's printer would
    # otherwise vanish from this file entirely, count included. The calls the
    # ASSEMBLY makes on the caller's behalf carry the forwarded bindings, which are
    # the same two arguments one frame deeper -- asserting the literal there would
    # assert the caller's spelling rather than the property, so those three are
    # checked for both names simply being passed on. A rule the assembly refused to
    # forward would read as an empty argument string and fail here.
    calls = (_helper_calls(source)
             + [("parse_date", _call_arguments(helper_source, "parse_date(")),
                ("parse_questions", _call_arguments(helper_source, "parse_questions(")),
                ("check_supersede", _call_arguments(helper_source, "check_supersede(")),
                ("refuse_linked_state",
                 _call_arguments(source, "refuse_linked_state(", call_site="_fail")),
                ("refuse_state_root",
                 _call_arguments(source, "refuse_state_root(", call_site="_fail")),
                ("refuse_ledger_allocation",
                 _call_arguments(source, "refuse_ledger_allocation(",
                                 call_site="_fail")),
                ("refuse_taken_name",
                 _call_arguments(source, "refuse_taken_name(", call_site="_fail")),
                ("_allocation_refusal",
                 _call_arguments(helper_source, "_allocation_refusal("))])
    # The four single-rule calls, plus the assembly that makes them, plus the four
    # path seams decide hands its printer to. The assembly and the seams live in the
    # helper too, so the count is what says the caller did not quietly re-implement
    # one of them beside it -- and every one of them crosses with the caller's own
    # printer and code.
    assert len(calls) >= 8, calls
    for name, arguments in calls:
        assert name in {"parse_date", "parse_questions", "check_supersede",
                        "refuse_name", "build_record_flags",
                        "refuse_linked_state", "refuse_state_root",
                        "refuse_ledger_allocation",
                        "refuse_taken_name", "_allocation_refusal"}, name
        # A rule that takes no printer is exempt from the printer/code pair: the
        # directory question of the allocation seam answers with a pair of lines and
        # prints nothing, so it is held to its own call site instead. The four path
        # seams take both positionally, so they are held to the same contract by name
        # rather than by keyword.
        if name == "_allocation_refusal":
            continue
        if name in {"refuse_linked_state", "refuse_state_root",
                    "refuse_ledger_allocation", "refuse_taken_name"}:
            assert "_fail" in arguments, f"{name} is called without the caller's printer"
            assert re.search(r"\bEXIT_\w+\b", arguments), \
                f"{name} is called without the caller's own exit constant"
            continue
        assert "fail=" in arguments, f"{name} is called without the caller's printer"
        assert "exit_usage=" in arguments, \
            f"{name} is called without the caller's usage code"
    # The helper's own internal call is the other half of that check: the allocation
    # seam asks its directory question first, so if that call ever lost the printer
    # the refusal would be computed and never printed.
    allocation = _call_arguments(helper_source, "_allocation_refusal(")
    assert "repo" in allocation and "ledger" in allocation, allocation
    # ...and for the calls the caller makes itself, the values handed over are
    # literally the writer's own printer and its own usage constant. The three path
    # seams are exempt: they take the printer and the exit constant positionally, so
    # the literal check below (which is spelled for the keyword-only flag rules) is
    # replaced by an assertion that both are named in the argument text.
    for name, arguments in _helper_calls(source):
        if name in {"refuse_linked_state", "refuse_state_root",
                    "refuse_ledger_allocation", "refuse_taken_name"}:
            assert "_fail" in arguments, f"{name} is called without the caller's printer"
            assert re.search(r"\bEXIT_\w+\b", arguments), \
                f"{name} is called without the caller's own exit constant"
            continue
        assert "fail=_fail" in arguments, f"{name} is called without the caller's printer"
        assert "exit_usage=EXIT_USAGE" in arguments, \
            f"{name} is called without the caller's usage code"
    # The name rule is reached through the helper that owns the flag refusals, so
    # the seam is one call wider than the three older rules: decide.py hands
    # ``refuse_name`` to ``_writer.flag_refusals`` together with its own printer,
    # its usage code and the census's line predicate. A seam that dropped the
    # predicate -- or kept a second copy of "what is one line" -- is how a name the
    # census reports at exit 10 gets committed, so all three are asserted to cross.
    seams = re.findall(r"_writer\.flag_refusals\(([^)]*)\)", source, re.S)
    assert len(seams) == 1, seams
    seam = seams[0]
    assert "_decide_flags.refuse_name" in seam, \
        "the flag seam no longer hands the name rule to the helper"
    assert "fail=_fail" in seam or "_fail, EXIT_USAGE" in seam.replace("\n", " "), \
        "the flag seam is called without the caller's printer and usage code"
    assert "EXIT_USAGE" in seam, "the flag seam is called without the caller's code"
    assert "is_single_line" in seam, \
        "the flag seam is called without the census's own line predicate"
    helper_source = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    assert "LINE_BREAKS" not in helper_source and "\\u2028" not in helper_source, \
        "the helper keeps its own copy of the line-break set instead of the argument"


def test_the_name_rule_refuses_through_the_callers_printer_and_code():
    """``refuse_name`` obeys the same contract as the three older rules.

    The name check refuses at the flag rather than letting the census report the
    record later, so it must print through the caller's printer with the caller's
    usage code, and it must obey the predicate it is handed rather than one of its
    own: a value the caller's ``line_free`` calls a line is accepted whatever the
    helper thinks of it.
    """
    calls: list[tuple[int, str, str | None]] = []

    def fail(code: int, message: str, hint: str | None = None) -> int:
        calls.append((code, message, hint))
        return code

    def line_free(value: object) -> bool:
        return isinstance(value, str) and bool(value) and "\n" not in value

    refused = _decide_flags.refuse_name("--decided-by", "", fail=fail,
                                        exit_usage=decide.EXIT_USAGE,
                                        line_free=line_free)
    assert refused == decide.EXIT_USAGE
    refused = _decide_flags.refuse_name("--on-behalf-of", "ops\nlead", fail=fail,
                                        exit_usage=decide.EXIT_USAGE,
                                        line_free=line_free)
    assert refused == decide.EXIT_USAGE
    assert calls and all(code == decide.EXIT_USAGE for code, _m, _h in calls), calls
    assert all("--" in message for _c, message, _h in calls), \
        "the refusal must name the flag it refused"
    calls.clear()
    assert _decide_flags.refuse_name("--decided-by", "Dana Reyes", fail=fail,
                                     exit_usage=decide.EXIT_USAGE,
                                     line_free=line_free) is None
    # A predicate the caller hands in is the whole rule: a value this line_free
    # calls a line is accepted even carrying a break the census's own set names.
    assert _decide_flags.refuse_name("--decided-by", "a\fb", fail=fail,
                                     exit_usage=decide.EXIT_USAGE,
                                     line_free=line_free) is None
    assert calls == []


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
    # The caller still refuses before the ledger is touched. The two values are
    # passed as flags by whoever calls the rule -- decide.py today through
    # :func:`build_record_flags`, which forwards its own ``args`` values -- so the
    # assertion is about the pair crossing the seam as values and not about which
    # frame makes the call.
    helper_source = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    caller = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    passed = ("check_supersede(args.supersedes, args.date" in helper_source
              or "check_supersede(args.supersedes, args.date" in caller)
    assert passed, "the two flags the supersede rule owns are no longer passed as values"
