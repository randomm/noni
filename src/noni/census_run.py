"""The census's run: the body of ``main``, from argv to the rendered verdict.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` keeps the check contract's re-exports, the probe seams, the
row factory and the group entry points, and this module owns the sequence the
tool executes — the argument validation, the one probe each group is gated on,
the ``--only``/``--skip`` row filter, the exit-code choice and the call that
renders the report.

This module is the leaf of the census's package graph: it imports the census and
is imported by no census module, so nothing cycles. It asks the census for every
group through a module resolved at the call (``census = _census()``, then
``census._check_ledger`` and its siblings) rather than binding a copy at import,
so a seam a test puts on a census name is the seam this run uses. The ledger
composition names its row mechanics literally at its own call (see
``_check_ledger`` there), so the names are looked up in the census's globals when
the call runs and a seam on the row factory, the classifier or the content digest
reaches the moved reporters too.

Nothing here composes a finding of its own: the rows are built by the census's
row factory and the modules it hands its mechanics to. The only output this file
produces is the usage and tool-missing messages of a run that cannot start, the
``--list`` ids, the ordering-closed notice, and the report ``_render`` prints.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import census_group_gate as _group_gate
from . import census_intent as _intent
from . import census_json as _census_json
from . import census_ordering as _ordering
from . import census_ordering_readers as _ordering_readers
from . import census_text as _text
from . import intentschema
from .census_cli import _build_parser
from .census_render import (
    ORDERING_CLOSED_NOT_EVALUATED,
    ORDERING_STALE_AFTER_DEFAULT,
    STALE_AFTER_RE,
    _render,
    _threshold,
    no_state_root_note,
)
from .census_report import (
    CLASS_CODE,
    EXIT_CLEAN,
    EXIT_TOOL_MISSING,
    EXIT_USAGE,
    INTENT_CHECKS,
    LEDGER_CHECKS,
    ORDERING_CHECKS,
    WHOLE_ARTIFACT_KEY,
    _known_checks,
)


def _census():
    """The census module, resolved at the call and never at import.

    ``census.py`` re-exports this run as its own entry point, so the two modules
    name each other and one of them is always the half-built object Python leaves
    in ``sys.modules`` while the pair loads. A module-level ``from . import
    census`` here would bind that partial copy permanently: a name bound below
    the cycle would then be missing, and a seam a test puts on the census after
    the import would be invisible to this body. Resolving the module on every
    call reads the finished object and its current bindings, which is what the
    seam rule in this file's docstring promises.
    """
    return importlib.import_module("noni.census")


def _load_issue_state(issue_state_path: Path | None):
    """The ``--issue-state`` map, read by the readers module beside the census.

    The census's own classifier and bounder are read off the census at the call,
    exactly as the ordering group's own row mechanics are, so a lookalike earlier
    on the path cannot answer for the artifact and no second file writes a row or
    clips a message.
    """
    census = _census()
    return _ordering_readers.load_issue_state(
        issue_state_path, _ordering.ISSUE_STATE_STATES, census._file_kind,
        census._bounded, _census_json.load_json_strict)


def _check_ordering(
    order: Path, ledger: Path, root: Path, now: datetime, ordering_stale_after: timedelta,
    issue_state, strict: bool, findings: list[dict],
    names: tuple[str, ...] | None,
) -> None:
    """The ordering group, run by the module beside the census.

    The row factory, the two helpers a row is built from and the readers module
    are read off the census at the call rather than closed over at import, so the
    row shape, its visibility marker and the machine-local-path rule stay written
    in exactly one place (``census.py``) and a seam on any of them is the one the
    moved group uses.

    ``names`` is the run's one ledger listing, the probe's, handed down for the
    group's record lookups: the ordering group reads the ledger the census
    already read and never walks the directory again (see ``LedgerProbe.names``).
    """
    census = _census()
    _ordering.check_ordering(order, ledger, root, now, ordering_stale_after,
                             issue_state, strict, findings,
                             row=census._row,
                             rel_to_root=census._rel_to_root,
                             file_kind=census._file_kind,
                             bounded=census._bounded,
                             parse_iso=census._parse_iso,
                             clipped=census._clipped, names=names,
                             readers=_ordering_readers,
                             load_json_strict=_census_json.load_json_strict,
                             names_zone=_ordering_readers.names_zone,
                             ledger_name=census._ledger_name)


def _check_intent(
    intent: Path, ledger: Path, root: Path, strict: bool, findings: list[dict]
) -> None:
    """The intent group, run by the module beside the census.

    The row factory, the root-relative identifier, the path classifier, the
    fault wording and the strict JSON reader are read off the census at the call
    rather than closed over at import, so the row shape, the machine-local-path
    rule and the bound on a foreign message keep their single owner in
    ``census.py`` and a seam a test puts on any of them is the one the moved group
    uses. The group reads one file and one record of its own; ``commit_subject``
    is the run's one history view asked for the subject of the last commit that
    touched the file, which is what keeps the whole run to a single ``git log``.
    ``ledger_state`` is the same probe's state word for the ledger directory, so the
    intent group refuses a cited record standing under a linked ``decisions/`` on the
    answer the run already took instead of re-deriving the path state for itself.
    """
    census = _census()
    _intent.check_intent(
        intent, ledger, root, findings, strict,
        row=census._row, rel_to_root=census._rel_to_root,
        file_kind=census._file_kind, fault_text=_text.fault_text,
        load_json_strict=_census_json.load_json_strict,
        commit_subject=census._intent_commit_subject,
        ledger_state=lambda path: census._ledger_probe(path).state)


def _run(argv: list[str] | None = None) -> int:
    """The body of the census run, called by ``census.main``.

    The census owns the entry point and the flag list it reads (see
    ``census.main``); this is the sequence that acts on it. Every group and every
    row mechanic is asked of the census module once per body (``census =
    _census()``, then ``census._`` …), so a seam a test puts on a census name is
    the seam this body uses.

    ``_set_run_root`` records the tree being audited before any group runs: the
    intent class asks the history view for the subject of the last commit that
    touched its file, and that question is answered through a census seam a test
    can replace — ``census._intent_commit_subject(rel)``, which consults the root
    recorded here. A caller that replaces the seam needs nothing from this body;
    a caller that does not gets the view built for ``--repo`` and nothing else.
    """
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    census = _census()

    checks = _known_checks(args.only, args.skip)
    if isinstance(checks, tuple):
        print(checks[1], file=sys.stderr)
        return EXIT_USAGE

    if args.list_checks:
        for name in checks:
            print(name)
        return EXIT_CLEAN

    now, err = census._parse_now(args.now)
    if err:
        print(err, file=sys.stderr)
        return EXIT_USAGE
    raw_days = args.stale_after
    if not STALE_AFTER_RE.fullmatch(raw_days):
        print(
            f"error: --stale-after {args.stale_after!r} must be positive whole days (e.g. 7 or 7d)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    days = int(raw_days.rstrip("dD"))
    if days <= 0:
        print(
            f"error: --stale-after {args.stale_after!r} must be positive whole days (e.g. 7 or 7d)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    stale_after = timedelta(days=days)
    # The threshold this run applies. --stale-after was given: the class uses the
    # number the caller named, which is what keeps a census run reproducible from its
    # command line alone. It was not: the class gets the default that belongs to it, and
    # the run records which one it used in the row's own wording (the stale row names the
    # threshold it compared against).
    # The flag's *presence* decides, not its value: an argparse default cannot
    # tell a caller who typed the number from one who did not, and treating the
    # literal `7d` as absent would quietly run the ordering check at 30 days on
    # a command line that promises 7.
    supplied = [a for a in (sys.argv[1:] if argv is None else argv)
                if a == "--stale-after" or a.startswith("--stale-after=")]
    ordering_stale_after = (stale_after if supplied
                            else _threshold(ORDERING_STALE_AFTER_DEFAULT))

    # git is a required tool: the census reads history for three of its four
    # groups. The lookup goes through this module's own ``shutil``, so the seam a
    # test puts on ``noni.census_run.shutil.which`` is the one the run asks.
    if shutil.which("git") is None:
        print("census: git not found on the reading machine", file=sys.stderr)
        return EXIT_TOOL_MISSING

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: repo path does not exist: {args.repo}", file=sys.stderr)
        return EXIT_USAGE
    ledger = Path(args.ledger) if args.ledger else root / "noni" / "decisions"
    ordering = (Path(args.ordering) if args.ordering
                else root / "noni" / "direction" / "order.json")
    intent = (Path(args.intent) if args.intent
              else root / intentschema.INTENT_REL)
    issue_state_path = Path(args.issue_state) if args.issue_state else None
    ledger = Path(os.path.expanduser(str(ledger)))
    ordering = Path(os.path.expanduser(str(ordering)))
    intent = Path(os.path.expanduser(str(intent)))
    if issue_state_path is not None:
        issue_state_path = Path(os.path.expanduser(str(issue_state_path)))

    top = census._git_top(root)
    git = census.Git(top) if top is not None else None
    # The one root this run audits, recorded on the census for the duration of
    # the call so the intent group's history question is answered for the tree
    # --repo named and no other (see census._set_run_root).
    census._set_run_root(root)

    findings: list[dict] = []
    # What this run observed about a class it did not evaluate. Human mode prints
    # each entry as a ``note:`` line, --json mode carries them on the summary row
    # (see ``_render``). Decided from the flags alone -- never the clock, the
    # filesystem or the cwd -- so the byte stream of a --json run stays
    # reproducible across two runs with one --now.
    notes: list[str] = []
    # One --only/--skip rule for all five groups: a group runs when any class
    # of its reporting set was asked for, and keeps only the rows of the
    # classes actually named. The ledger group is reported as a unit (the
    # empty-ledger probe owns states the record pass must not duplicate), so
    # the filter is applied to its rows rather than skipped; no group runs work
    # whose rows it will discard.
    requested = set(checks)

    def keep(group_findings: list[dict]) -> list[dict]:
        """The rows of one group the run reports: those of a class the caller
        named, plus every row marked ``WHOLE_ARTIFACT_KEY`` — a row about the
        file a group was asked to read, not one entry inside it.

        The first half is the --only contract. The second is the probe-honesty
        rule: a group that could not read its input must say so even under a
        filter that named none of its classes, or a run that observed a fault
        would report the same clean verdict as a run that found none.
        """
        return [f for f in group_findings
                if f["check"] in requested or f.get(WHOLE_ARTIFACT_KEY)]

    # The ledger is classified once per run, here, before the group is gated on
    # the answer: `main` reads `listing_fault` off this one probe to decide
    # whether the group runs at all, and the same probe goes into
    # `_check_ledger` for the rows.
    ledger_probe = census._ledger_probe(ledger)

    # A tree whose ``noni/`` does not exist at all is the one state the census must
    # say out loud before its rows: on its own, a no-``noni/`` tree reads as a
    # ledger-empty warn plus an inactive deny-list and exits 0, which a caller who
    # pointed --repo at a code repository by mistake reads as a clean project. The
    # probe already answers that state (``absent`` is answered only when ``noni/``
    # itself is missing), so the note keys on it and on nothing else -- not the clock,
    # not the cwd, and not a row. It rides the notes channel, so no check class and no
    # NDJSON row kind is added and every exit code is unchanged. Suppressed
    # whenever any of the three path overrides is in effect: with a ``--ledger``
    # (or ordering, intent) pointing elsewhere, the state does not live under
    # --repo and "no noni/ under --repo" would be a true sentence about an
    # irrelevant tree.
    if ledger_probe.state == "absent" and not (args.ledger
                                               or args.ordering or args.intent):
        notes.append(no_state_root_note(args.repo))

    if (LEDGER_CHECKS | {"ledger-empty"}) & requested or ledger_probe.listing_fault:
        # The group runs whenever one of its classes was asked for, and also
        # whenever the probe could not list the ledger: that row is the
        # probe-honesty one `keep` never drops, so a run whose filter named no
        # ledger class must still reach the read that faulted rather than
        # report the clean verdict of a group that never ran.
        # The composition of the group is the census's own
        # `_check_ledger`; its reporters and the row mechanics they compose
        # with are read off that module at the call, so a seam a test puts
        # on the census's own row factory, classifier or probe is the one
        # the moved code uses.
        census._check_ledger(ledger, git, root, findings, args.strict,
                             ledger_probe)
        findings[:] = keep(findings)

    if ORDERING_CHECKS & requested:
        _check_ordering(ordering, ledger, root, now, ordering_stale_after,
                        _load_issue_state(issue_state_path),
                        args.strict, findings, ledger_probe.names)
        findings[:] = keep(findings)
        # The closed check's question comes only from --issue-state, which an
        # adapter or the operator produces. Without it the class is not run, and
        # the run says so once rather than letting "no ordering-closed rows"
        # read as "every ordered issue is open". The same sentence is carried in
        # both modes: a ``note:`` line on stdout here, the summary row's
        # ``not_evaluated`` field in --json mode (see ``_render``), so a CI run
        # that gates on the rows loses the information no more than one that
        # reads the human report.
        if issue_state_path is None and "ordering-closed" in requested:
            notes.append(ORDERING_CLOSED_NOT_EVALUATED)
            # The note alone is not a verdict, and a recipe-following CI that reads
            # only the exit code saw green while its order went dead (issue #148). So
            # the same fact is also a row of the class that owns the question, built by
            # the group's own ``add`` helper so it shares the group's row factory,
            # ``strict`` promotion and root-relative artifact naming: a warn without
            # --strict, which leaves the exit exactly where the note left it, and the
            # class's own 46 under --strict.
            _ordering.closed_state_unasked_row(
                ordering, root, args.strict, findings, row=census._row,
                rel_to_root=census._rel_to_root, readers=_ordering_readers,
                primitives={"file_kind": census._file_kind,
                            "bounded": census._bounded,
                            "clipped": census._clipped,
                            "parse_iso": census._parse_iso,
                            "load_json": _census_json.load_json_strict})

    # The intent class is its own group: one file, one cited record, and the
    # citation question answered from the history view this run already took. The
    # ledger's listing is not handed down -- the group reads the one record the
    # citation names and reads the answer for itself. Like every other group its
    # path defaults under --repo and ``census_cli`` gives it the same kind of path
    # override the ledger and ordering groups have.
    #
    # The group is entered whenever a class of it was asked for, and also whenever
    # the census's own classifier says a read is owed: every cannot-tell row this
    # class can raise is raised from a read of that file (the bytes, their
    # encoding, or the history of the path), so a run that skipped the read while a
    # file was there would report the same clean verdict as a run that read it and
    # found nothing -- the inversion ``keep``'s whole-artifact term exists to
    # prevent, which only ever applies to a row the group actually appended. An
    # absent file is the one state this class says nothing about at all (see
    # ``check_intent``), so the cheap classification keeps a filtered run of a
    # project that wrote no intent from paying for a read whose answer is known to
    # be no row. The gate asks the classifier rather than ``Path.exists`` because
    # a path the filesystem will not describe is a read the run owes, not a crash:
    # ``check_intent`` owns that verdict, and the gate must not reach it first.
    if INTENT_CHECKS & requested or _group_gate._intent_present(intent):
        _check_intent(intent, ledger, root, args.strict, findings)
        findings[:] = keep(findings)

    # The item store and its six classes were removed, and the census ignores a
    # ``noni/items/`` directory a repository still holds: it is not listed, not read,
    # not classified and not reported, so a tree with a stale store left behind censuses
    # exactly as the same tree without it. The hygiene group is untouched by it: the
    # directory is not one of the paths hygiene inspects.

    # hygiene is its own check group: it scans the tracked files of the census's
    # own git tree (never the --ledger override). The group is entered
    # through the census's own wrapper, as the other three are, so the row factory
    # and the message bounder it hands the scanner are read off that module at the
    # call and a seam on either is the one the scanner uses.
    if "hygiene" in requested:
        census._check_hygiene(top, args.strict, findings, row=census._row,
                              bounded=census._bounded)

    # --- Aggregate -----------------------------------------------------------
    # Warnings never set the exit code on their own: clean means exit 0 even
    # with cannot-tell or probe warnings. A warning-class check can only lift
    # the exit when --strict promotes it to a failure.
    fired = {f["check"] for f in findings}
    fail_classes = {c for c in fired if next(f for f in findings if f["check"] == c)["severity"] == "fail"}
    exit_code = 0
    for c in sorted(fail_classes, key=lambda c: CLASS_CODE[c]):
        exit_code = CLASS_CODE[c]
        break

    counts = {c: 0 for c in CLASS_CODE}
    for f in findings:
        counts[f["check"]] += 1
    ok = exit_code == EXIT_CLEAN

    _render(findings, counts, ok, exit_code, args.json_out, tuple(notes))
    return exit_code
