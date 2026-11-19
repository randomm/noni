"""One record-first hint, printed verbatim by every route that refuses a citation.

Added for issue #198: the three sites that refuse a missing or absent ``--decision``
(order ``add`` with no flag, order ``add``/``move --decision`` for a record the ledger
does not hold, and ``intent set``'s citation) all print the one constant
``noni.orderstate.RECORD_FIRST_HINT``. This module is the check no per-site substring
assertion can make: three launched runs, three labels, one string, compared byte for
byte against what each run actually printed.
"""

from __future__ import annotations

import ast

from _harness import (
    SRC,
    _commit_file,
    _git,
    _init_repo,
)
from intent_fixtures import (
    GOOD_INTENT,
    INTENT_REL,
    RECORD_ID,
    repo_with_record,
)
from intent_writer_support import draft, intent_run
from order_doc_readers import _docstring, _order_ast
from order_fixtures import (
    BASELINE_ID,
    GHOST_ID,
    NOW,
    _entry,
    _order,
    _order_path,
    _repo,
    _seed,
)
from orderstate_hint_support import (
    ADD_ROUTES,
    INTENT_LABEL,
    ORDER_LABEL,
    RECORD_FIRST,
    fix_lines,
    launch_add_without_decision,
)

# Asked of the product rather than copied: this module pins whole fix lines, so it
# reads the writer's own docstring and constant instead of a remembered wording.
from noni import orderstate as _orderstate_module

SET = "set"


def _order_source() -> str:
    """The writer's own source, ``src/noni/order.py``, as text.

    Read from ``SRC`` and not the ``ORDER`` wrapper: the wrapper is a shim whose text
    says nothing about the tool's contract, the same reason ``_script_ast`` parses the
    package source when handed a wrapper path. The single-owner check reads the
    refusal site here, so a second spelling of the sentence fails the run.
    """
    return (SRC / "noni" / "order.py").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """``text`` with every run of whitespace down to one space."""
    return " ".join(text.split())


def _code_repo(tmp_path, name: str):
    """A committed git tree holding source and no ``noni/``: a wrong ``--repo``."""
    repo = _init_repo(tmp_path / name)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    _commit_file(repo, "README.md", "# a code repository\n")
    _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
    return repo


def test_the_three_citation_refusals_print_the_one_constant_verbatim(tmp_path):
    """Every site's fix line is the remedy it always said plus the constant.

    Each route reaches the hint through a different function (``order.py`` main,
    ``read_record``'s absent arm, ``decision_problems``' id-shape arm), so a
    reword at one of them moves one line and not the other two -- which is what
    the whole-line comparison catches and a substring check on each run never
    would. The expected lines are spelled here, so a site that swapped its remedy
    for another site's is caught too.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))

    runs = {
        "add without --decision": (
            _order(repo, "add", "7", "--now", NOW), 2,
            "name the decision record that put this issue there, or order it "
            "with order.py confirm if it is already listed " + RECORD_FIRST),
        "add --decision <missing>": (
            _order(repo, "add", "7", "--decision", GHOST_ID, "--now", NOW), 4,
            "name the record that set the position, or add it with the "
            "steering-ledger writer first " + RECORD_FIRST),
        "move --decision <missing>": (
            _order(repo, "move", "1", "--decision", GHOST_ID, "--now", NOW), 4,
            "name the record that set the position, or add it with the "
            "steering-ledger writer first " + RECORD_FIRST),
    }
    for name, (proc, code, expected) in runs.items():
        assert proc.returncode == code, f"{name}: {proc.returncode}: {proc.stderr}"
        lines = fix_lines(proc.stderr, ORDER_LABEL)
        assert len(lines) == 1, f"{name} printed {len(lines)} fix lines: {proc.stderr}"
        assert lines[0] == expected, f"{name}: {lines[0]!r}"


def test_the_hint_constant_is_one_sentence_naming_only_noni():
    """The constant is one line, an imperative, and names nothing outside noni.

    The wording is the whole of the guidance, so its shape is part of the
    contract: a sentence with a newline in it would print an unlabelled
    continuation line under one ``fix:`` prefix, and public-repo hygiene allows
    no tool, tracker or driver other than noni's own commands.
    """
    assert _orderstate_module.RECORD_FIRST_HINT is RECORD_FIRST
    assert "\n" not in RECORD_FIRST, RECORD_FIRST
    assert RECORD_FIRST.strip() == RECORD_FIRST, "the hint carries stray whitespace"
    assert RECORD_FIRST.startswith("Record the decision first with noni decide"), (
        RECORD_FIRST)


def test_each_route_of_the_add_refusal_prints_the_same_hint(tmp_path):
    """Wrapper, ``noni order`` and ``python -m noni`` print one identical refusal.

    The three routes import the package by different means, so a route that read
    a stale copy of the module would still print a decide-first sentence -- just
    not this one. Full-line equality is the only check that would notice.
    """
    repo = _repo(tmp_path)
    lines = set()
    for route, prefix in ADD_ROUTES:
        proc = launch_add_without_decision(route, prefix, repo)
        assert proc.returncode == 2, f"{route}: {proc.returncode}: {proc.stderr}"
        got = fix_lines(proc.stderr, ORDER_LABEL)
        assert len(got) == 1, f"{route}: {proc.stderr}"
        lines.add(got[0])
    assert len(lines) == 1, f"the routes disagree on the refusal: {lines}"
    assert next(iter(lines)).endswith(RECORD_FIRST)


def test_the_order_docstring_carries_the_constant_verbatim():
    """The document a caller reads says the thing the run says.

    The docstring is read from ``src/noni/order.py``'s own AST (the route
    ``tests/test_order_writer_docs.py`` uses for every other sentence of it), and
    the sentence is the product's constant rather than this file's copy of it, so a
    doc that drifted to a near-miss of what the refusal prints stays red. Line
    breaks are collapsed first: the docstring wraps at its own width.
    """
    doc = _flat(_docstring(_order_ast()))
    assert RECORD_FIRST in doc, f"order.py's docstring does not carry the hint: {doc}"
    assert "noni decide" in doc, "the docstring must name the verb the hint names"
    assert "RECORD_FIRST_HINT" in doc, (
        "the docstring must name the constant that owns the sentence")
    assert "orderstate.RECORD_FIRST_HINT" in _order_source(), (
        "the refusal site must name the constant, not spell the sentence again")


def test_intent_set_prints_the_same_hint_and_stays_on_its_own_label(tmp_path):
    """``intent set`` shares the refusal, so it shares the sentence (PM ruling #1).

    ``intent.py`` reaches the hint through ``orderstate.decision_problems`` under a
    different label, which is exactly how it could have acquired an order-shaped
    copy of it or lost the line altogether: both writers print one constant, and
    intent keeps its headline and its four codes.
    """
    repo = repo_with_record(tmp_path, records=())
    (repo / "noni" / "decisions").mkdir(parents=True, exist_ok=True)
    result = intent_run(repo, SET, "--from", draft(tmp_path, GOOD_INTENT),
                        "--decision", RECORD_ID)
    assert result.returncode == 4, f"{result.returncode}: {result.stderr}"
    assert "holds no noni/" not in result.stderr, result.stderr
    assert RECORD_ID in result.stderr, result.stderr
    lines = fix_lines(result.stderr, INTENT_LABEL)
    assert len(lines) == 1, result.stderr
    assert lines[0].endswith(RECORD_FIRST), result.stderr
    assert ORDER_LABEL not in result.stderr, (
        f"intent must print under its own label: {result.stderr}")
    assert not (repo / INTENT_REL).exists(), "a refused run wrote the intent file"


def test_a_wrong_repo_tree_gets_no_record_first_hint(tmp_path):
    """A tree with no ``noni/`` is a wrong ``--repo``, not a missing decision.

    The state-root sentence is the answer there, and sending that caller to
    ``noni decide`` would advertise a step that cannot fix the path they named.
    """
    repo = _code_repo(tmp_path, "no-hint-tree")
    proc = _order(repo, "add", "7", "--decision", GHOST_ID, "--now", NOW)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "holds no noni/" in proc.stderr, proc.stderr
    assert "is in the ledger" in proc.stderr, proc.stderr
    assert RECORD_FIRST not in proc.stderr, proc.stderr
    assert not _order_path(repo).exists()
    assert not (repo / "noni").exists(), "the refused run created the state tree"


def test_no_source_file_spells_the_hint_a_second_time():
    """Every refusal of a citation reaches the sentence through the one constant.

    The launched-run comparison is the behavioural half of this contract; this is
    the source half, and it is the one that catches a reword nobody ran: the four
    places the hint can be printed live in two modules, and a site that spelled the
    sentence itself would keep every per-site assertion green while the constant
    drifted away from what the reader saw. ``orderstate`` is allowed the words that
    compose it (its own definition, and the join in :func:`_citation_hint`); no
    other file may hold them at all, and order.py's one use must name the constant.
    """
    for name in ("order.py", "order_add.py", "order_plan.py", "intent.py"):
        path = SRC / "noni" / name
        text = path.read_text(encoding="utf-8")
        # Strip the module docstring: it documents the wording, which the docstring
        # pin above checks verbatim, so a quoted copy there is not a second printing.
        doc = ast.get_docstring(ast.parse(text)) or ""
        body = text.replace(doc, "", 1) if doc else text
        assert RECORD_FIRST not in body, (
            f"{name} spells the hint instead of importing it: {RECORD_FIRST!r}")
    writer = _order_source()
    assert "orderstate.RECORD_FIRST_HINT" in writer, (
        "order.py's own refusal site must name the constant")
