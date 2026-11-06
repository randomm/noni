"""The census's ledger group: the record checks over ``noni/decisions/``.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the record pass — the composition of the
group, the schema check, the empty-ledger reporter, and the I/O and parse pass.
The two git-backed integrity checks, which answer the only two questions about
the ledger that history rather than the filesystem settles, sit in
``census_ledger_edited.py`` beside this file.

The row mechanics each reporter needs — ``row``, ``rel_to``, ``rel_to_root``,
``file_kind``, ``bounded``, ``clipped``, ``repo_sha1`` and the cannot-tell row —
are handed in at the call, exactly as the ordering and session splits do it, so
the row shape, its visibility marker and the machine-local-path rule keep their
single owner in ``census.py`` and this module composes no row of its own
devising. The one probe of the ledger directory is taken by the census
(``_ledger_probe``) and arrives here as the ``probe`` argument: this module never
lists the directory for itself.

The group's own constants — the schema field set, the record date shape and the
empty-state vocabulary — are declared here beside the code that reads them, and
``census.py`` re-exports them so a caller that already imports the census still
names them through it.

Nothing here prints or exits: every answer is appended to the caller's
``findings`` list.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import census_ledger as _ledger
from . import census_text as _text
from . import ledger_schema as _schema

if TYPE_CHECKING:  # pragma: no cover - typing only, nothing imported at runtime
    from .census_git import Git

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.json$")
# The field sets, the option bounds and the two predicates are the shared
# vocabulary in ``ledger_schema`` (see that module for why all four readers of
# the schema name one owner); these bindings keep the names this module's
# callers and ``census.py`` already use.
REQUIRED_LEDGER_FIELDS = _schema.REQUIRED_LEDGER_FIELDS
OPTIONAL_LEDGER_FIELDS = _schema.OPTIONAL_LEDGER_FIELDS
NAME_LINE_FIELDS = _schema.NAME_LINE_FIELDS
LINE_BREAKS = _schema.LINE_BREAKS
DATE_RE = _schema.DATE_RE
is_single_line = _schema.is_single_line

# The five states the ledger probe answers: the four the ledger-empty class
# reports, each in exactly one row's message, plus the silent "ok". "empty"
# names a tree with no decision record to arbitrate: noni/ present without a
# decisions/ directory, or a decisions/ directory that holds no *.json record.
# The words and their wording are pinned by LEDGER_EMPTY_MESSAGES below and the
# tests iterate that table, so renaming a state without updating its wording
# (and tests/test_census_ledger_empty.py) is a contract change.
LEDGER_EMPTY_STATES = ("absent", "empty", "not a directory", "symlink", "ok")

# state word -> the detail the row carries, or None for the state that reports
# nothing. The keys ARE the state vocabulary: _ledger_probe returns one of
# them and _check_ledger_empty looks its message up here, so the contract has
# exactly one owner.
LEDGER_EMPTY_MESSAGES: dict[str, str | None] = {
    "absent": "no decision record is censusable: the ledger directory is absent "
    "(no noni/decisions under this repo — no steering ledger to arbitrate)",
    "empty": "the ledger holds no *.json record: either noni/ has no decisions/ "
    "directory, or that directory exists and holds none",
    "not a directory": "noni/ is not a directory, so no ledger can live under it",
    "symlink": "noni/ or the ledger path is a symlink; the census does not read through links",
    "ok": None,
}


def _validate_record(obj: object) -> list[str]:
    """Schema-check a parsed decision record; return the list of problems
    (empty = valid). Mirrors the required-field shape of the steering-ledger
    record, including the closed-set rule (the required eight plus the four
    optional fields), which is tested as a SET: every key of the record must be
    a declared one, so a junk key is reported whatever the record's key count
    is (a count would let a junk key ride beside a real optional field).
    The field groups whose wording is long enough to deserve
    its own function are the helpers in ``ledger_schema``; what is left here is
    the one-line set and type checks, so every problem still names its field and
    nothing else and the reporter turns one malformed value into one row."""
    if not isinstance(obj, dict):
        return ["record is not a JSON object"]
    problems: list[str] = []
    missing = [f for f in REQUIRED_LEDGER_FIELDS if f not in obj]
    if missing:
        problems.append("missing field(s): " + ", ".join(missing))
    extra = [k for k in obj
             if k not in REQUIRED_LEDGER_FIELDS and k not in OPTIONAL_LEDGER_FIELDS]
    if extra:
        problems.append("unknown field(s): " + ", ".join(sorted(extra)))
    problems.extend(_schema.validate_source(obj))
    problems.extend(_schema.validate_date(obj))
    problems.extend(_schema.validate_questions(obj))
    status = obj.get("status")
    if "status" in obj and status not in ("decided", "open", "superseded"):
        problems.append("status not one of decided|open|superseded")
    for field in ("id", "by", "asked_by", "scope"):
        if field in obj and not _schema.is_non_empty_string(obj[field]):
            problems.append(f"{field} must be a non-empty string")
    # The two names keep the rule above and add the single-line one, and the
    # wording is the same shape ("<field> must be ...") so one malformed value
    # still reports as one ledger-record row that names its field. The predicate
    # refuses a blank as well as a break, which is the writer's flag rule read
    # back at the record: a hand-edited `"decided_by": "   "` is a ledger-record
    # failure here, not a clean row.
    for field in NAME_LINE_FIELDS:
        if field in obj and not is_single_line(obj[field]):
            problems.append(f"{field} must be a non-empty single-line string")
    if _schema.SINGLE_OPTION_MARKER in obj and obj[_schema.SINGLE_OPTION_MARKER] is not True:
        problems.append(f"{_schema.SINGLE_OPTION_MARKER} must be true when present")
    sup = obj.get("supersedes")
    if "supersedes" in obj and sup is not None and (not isinstance(sup, str) or not sup):
        problems.append("supersedes must be null or a non-empty string")
    return problems


# The ledger probe (the state word for `noni/decisions/` and the one row a
# listing that faulted earns) lives in census_ledger.py beside this file, in the
# same shape as the hygiene and ordering splits: an ordinary package import, with

def check_ledger(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                 strict: bool, probe: _ledger.LedgerProbe, *,
                 row: Callable[..., dict],
                 rel_to: Callable[[Path, Path], str | None],
                 rel_to_root: Callable[[Path, Path], str],
                 bounded: Callable[..., str],
                 clipped: Callable[[str], str],
                 file_kind: Callable[..., tuple[str, str | None]],
                 repo_sha1: Callable[[Path], str | None],
                 cannot_tell: Callable[[str, str, bool, list[dict]], None],
                 edit_check: Callable[..., None],
                 deletion_check: Callable[..., bool],
                 chain_check: Callable[..., None],
                 ledger_name: Callable[[str], str]) -> None:
    """Check the steering ledger; append findings (each a partial finding row).

    ``probe`` is the run's one classification of ``ledger``, built by ``main``
    before it decided whether this group runs at all: a second probe would be a
    second read of the directory and a second chance to disagree with the first,
    so the group reports from the answer that got it here.

    The composition only: the ledger-empty probe, then record I/O + schema
    validation, the edited check (git-backed), the deleted check (git-backed)
    and the supersede-chain check, in that order. The record pass reads the
    probe's own names, so the group's read of the directory is the probe's
    single readdir (see ``LedgerProbe.names``). ledger-empty only ADDS rows:
    the states where the record pass has nothing to say. The git-backed
    integrity checks run whatever the empty probe found — see the
    deleted-sole-record regression tests in tests/test_census_exit_codes.py.

    The two rows the composition adds itself, both probe honesty:

    * a listing that faulted gets one cannot-tell row of its own and stops the
      group there (`census_ledger.append_listing_fault`, called with this group's
      own ``ledger-edited`` class, noun and question): the probe read nothing, so
      no state word it answered is one this run established and no record pass
      can be trusted either;
    * when the deletion check could not put its question to git and the ledger
      reads as "empty", the run says so (probe honesty, issue #33). "Empty" is
      the only state that can mean "committed records were deleted", and this
      check is the only signal for that, so a silent one here would let a
      gutted ledger read as a plain no-ledger warning — the row is warn by
      default, fail under --strict."""
    if probe.listing_fault is not None:
        # The probe could not list the ledger, so no state word it answered is
        # one this run established: the empty class stays silent, the record
        # pass has nothing trustworthy to read, and the one row the group adds
        # says what the read could not do (`census_ledger.append_listing_fault`).
        #
        # The return suppresses more than the group's own read. Every check
        # below it is skipped, including the git-backed ones, so a listing fault
        # silences git's deletion answer as well: a committed `decisions/`
        # directory whose records were deleted — a tree still on disk, which is
        # the only shape a listing can fault on — reports no `deleted` row, and
        # history may well have held records. That is accepted behaviour, not an
        # oversight: a cannot-tell is the honest answer for a run that read
        # nothing, and a deletion row built on a listing the run never got would
        # be reporting a state it did not observe. Both halves are pinned in
        # tests/test_census_ledger_deleted_directory.py (one run with the listing
        # faulted, one without, on the same tree), so a change to this early
        # return has to move that pair deliberately rather than by accident.
        _ledger.append_listing_fault(
            ledger, root, findings, strict, probe.listing_fault,
            check="ledger-edited", noun="the ledger directory",
            unknown="so whether a committed record was deleted or edited cannot be "
                    "answered",
            row=row, rel_to_root=rel_to_root, bounded=bounded, clipped=clipped)
        return
    check_ledger_empty(probe, ledger, root, findings, strict, row=row, rel_to_root=rel_to_root,
                       bounded=bounded, ledger_name=ledger_name)
    valid, unparseable = check_ledger_records(ledger, root, findings, probe, row=row,
                                              file_kind=file_kind, rel_to_root=rel_to_root,
                                              ledger_name=ledger_name)
    edit_check(valid, unparseable, git, root, findings, strict, row=row, rel_to=rel_to, repo_sha1=repo_sha1)
    could_not_answer = deletion_check(ledger, git, root, findings, strict, row=row, rel_to_root=rel_to_root, cannot_tell=cannot_tell, ledger_name=ledger_name)
    if could_not_answer and probe.state == "empty":
        cannot_tell(
            "ledger-edited",
            "the git-backed deletion check could not run on this empty ledger "
            "(no readable git history), so whether committed records were deleted "
            "from it cannot be answered", strict, findings)
    chain_check(valid, ledger, root, findings, row=row, rel_to_root=rel_to_root,
                ledger_name=ledger_name)

def check_ledger_empty(probe: _ledger.LedgerProbe, ledger: Path, root: Path,
                       findings: list[dict],
                       strict: bool, *,
                       row: Callable[..., dict],
                       rel_to_root: Callable[[Path, Path], str],
                       bounded: Callable[..., str],
                       ledger_name: Callable[[str], str]) -> None:
    """The ledger-empty class: exactly one warn row when there is no ledger.

    A pure reporter: it appends its row and returns. The git-backed integrity
    checks are not gated on the outcome — a ledger that reads as empty today
    may have been emptied by a deletion, and that deletion is reported by
    `_check_ledger_deleted` regardless. The four states of
    LEDGER_EMPTY_MESSAGES (other than the silent "ok") each produce exactly one
    row carrying their own state word, so "no ledger at all" reads as a
    reported warning rather than a silent clean (the state word IS the
    finding: a census that stays quiet here cannot tell "nothing to census"
    apart from "the ledger went missing").

    The class only ADDS rows: it never weakens a failure the group already
    reports. The states it owns are exactly the ones where no record can be
    read: no ``noni/``, ``noni/`` not a directory, a symlink, or no record to
    census (``noni/`` with no ``decisions/``, or a ``decisions/`` directory
    holding no ``*.json`` record). Malformed records remain the ledger-record
    failure: only the absence of records is a warn.

    This class is warn-severity: a run that has only this finding exits 0,
    and --strict promotes it to exit 42. Symlinks are reported, never read
    through (the probe-honesty rule).

    The ledger is named by ``ledger_name(rel_to_root(root, ledger))`` in both
    identifier fields, the same identifier the group's other rows use (see
    :func:`check_ledger_records` for what the rule is and why an out-of-tree
    ``--ledger`` needs it). An in-tree ledger keeps its root-relative path, which
    is the directory the row's fix asks the operator to create.
    """
    detail = LEDGER_EMPTY_MESSAGES[probe.state]
    if detail is None:
        return
    if probe.problem:
        # Foreign text from this tree, so it gets the bound-and-scrub the
        # listing-fault row applies to its fault text: a row built from someone
        # else's error must not smuggle a host path or run past the length every
        # other row keeps. The sentence around it is this census's own wording.
        detail = f"{detail} (probe error: {bounded(probe.problem)})"
    artifact = ledger_name(rel_to_root(root, ledger))
    findings.append(
        row("ledger-empty", strict, artifact, artifact,
             f"ledger-empty ({probe.state}): {detail}", root)
    )



def check_ledger_records(ledger: Path, root: Path, findings: list[dict],
                         probe: _ledger.LedgerProbe, *,
                         row: Callable[..., dict],
                         file_kind: Callable[..., tuple[str, str | None]],
                         rel_to_root: Callable[[Path, Path], str],
                         ledger_name: Callable[[str], str]) -> (
                         tuple[list[tuple[str, Path, dict]], list[tuple[str, Path]]]):
    """I/O + schema validation. Returns (valid, unparseable) where each entry
    of unparseable is (name, path) of a file that exists on disk but failed
    parsing — it still gets the git edited check.

    ``probe`` is the run's one classification of ``ledger``, and this pass reads
    both of its answers and asks neither again: ``probe.state`` for whether a
    record pass is warranted at all, and ``probe.names`` for the records
    themselves. The names are the probe's because the probe's readdir is the
    only one this run performs — a second listing was a second read of a tree
    that can change under the run, and one that faulted after the probe's had
    succeeded raised out of ``main`` as a traceback rather than a row.

    ``state`` other than "ok" means this pass reads no records at all, so any
    state other than "ok" is ledger-empty's finding and adds no row here. "ok"
    means the directory holds at least one ``*.json`` name, so every row this
    pass adds is a malformed-record failure.

    Each row's artifact composes the ledger's identifier with the record's name —
    ``ledger_name(rel_to_root(root, ledger))`` plus ``<name>.json``, rather than
    ``str(ledger / name)`` rooted afterwards. The two agree for every ledger under
    ``--repo``, and differ for one the caller spelled: an out-of-tree ``--ledger``
    is a host directory, and a path built from it and then handed to the rooting
    helper is a path the helper cannot root and so prints verbatim. Naming the
    directory first is what keeps the row inside the census's
    never-print-a-machine-local-path promise whatever the override points at.
    """
    name = ledger_name(rel_to_root(root, ledger))

    def add(check: str, subject: str, record_name: str, message: str) -> None:
        """One row of this pass: ``record_name`` is the file the row is about and
        goes in ``artifact`` under the ledger's identifier, so a caller cannot
        hand it a path and have that path reach the row unrooted."""
        findings.append(row(check, False, subject, f"{name}/{record_name}", message, root))

    if probe.state != "ok" or probe.names is None:
        # ledger-empty owns every no-ledger state (absent, not a directory,
        # symlink, and any probe fault folded into one of them) as a warn that
        # names the state; this pass keeps only the malformed-record failures,
        # so a ledger that is not there adds no ledger-record row here. The
        # ``names is None`` arm is belt and braces: no state of "ok" is ever
        # built without the names that produced it.
        return [], []

    names = sorted(probe.names)
    valid: list[tuple[str, Path, dict]] = []
    unparseable: list[tuple[str, Path]] = []
    for record_name in names:
        path = ledger / record_name
        if not NAME_RE.match(record_name):
            add("ledger-record", record_name, record_name,
                "filename is not a plain <name>.json path segment")
            continue
        fkind, fproblem = file_kind(path)
        if fkind != "regular":
            add("ledger-record", record_name, record_name, f"record is unreadable: {fproblem}")
            continue
        try:
            raw = path.read_bytes()
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            # The exception message embeds the offending bytes, which are
            # untrusted record content (a record that contains raw NULs or
            # other control bytes would smuggle them into stderr); the fixed
            # wording below names the class without echoing the bytes.
            add("ledger-record", record_name, record_name, "record is not valid UTF-8")
            unparseable.append((record_name, path))
            continue
        except OSError as e:
            # The filename is the path of the record itself, which this row
            # already carries in ``artifact``: the fault contributes its class
            # and its errno words, nothing else.
            add("ledger-record", record_name, record_name,
                f"record is unreadable: {_text.fault_text(e)}")
            unparseable.append((record_name, path))
            continue
        try:
            obj = json.loads(body)
        except (json.JSONDecodeError, ValueError, RecursionError):
            # The wording is fixed and quotes nothing from the file, which is
            # untrusted content. The three named exceptions are the three ways
            # this decoder can refuse a record: ``json.JSONDecodeError`` for
            # malformed text; ``ValueError`` for the integer literal beyond the
            # interpreter's 4300-digit conversion limit, which raises it and is
            # no kind of decode error; and ``RecursionError``, which is no kind
            # of ValueError either, from a nesting past the interpreter's own
            # stack. On 3.11 that ceiling sits just under the recursion limit
            # (measured just under the default 1000, later builds reach far
            # more), so the arm is reachable, not decorative. Without it one
            # pathological record ended the whole run with a traceback, and a
            # report that never prints answers nothing.
            add("ledger-record", record_name, record_name, "record is not valid JSON")
            unparseable.append((record_name, path))
            continue
        problems = _validate_record(obj)
        if problems:
            subject = obj.get("id", record_name) if isinstance(obj, dict) else record_name
            add("ledger-record", subject, record_name, "; ".join(problems))
            continue
        valid.append((obj["id"], path, obj))

    return valid, unparseable


