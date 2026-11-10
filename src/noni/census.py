"""The unified census: one read-only entry point over the steering ledger,
the ordering artifact and the item store.

The census is the arbiter of the noni protocol invariants. It reads the git
history plus the committed files under ``noni/`` (decision records under
``noni/decisions/``, the ordering artifact at ``noni/direction/order.json``,
the standing intent file and the item store under ``noni/items/``), flags
protocol violations, and returns an honest exit code. It never writes
anything: running it leaves ``git status --porcelain`` empty, and no digest
file or report directory is produced — results are recomputed on demand.

The check ids, their codes and their default severities are declared once, in
``CHECKS`` of ``census_report.py`` beside this file: the exit-code table,
``--list``, the ``--strict`` help string and the tests' expected ids are all
derived from it, and re-exported here for the callers that name the census.

The warn classes make a finding without --strict but never move the exit code
on their own: the clean-ledger case (no noni/ at all) is a reported warning,
not a silent clean.

Probe failures never report clean: a probe that cannot read a file or cannot run
git records a probe failure (a warning, or its own code under --strict), never a
silent pass. The same rule covers the checks whose question this run cannot
answer at all — they append a ``cannot-tell`` row naming why, rather than falling
silent and reading as a clean run. The same rule outranks the ``--only`` row
filter: a group reports the rows that say *this run could not read the file it was
asked to check* (the artifact, its ``--issue-state`` input, or its ledger)
whatever the filter names, because a run that observed that fault and reported
none would be reporting a clean it did not establish. Rows about one entry inside
a file are still dropped when their class is not named — that is what ``--only``
is for. See ``_row`` and ``WHOLE_ARTIFACT_KEY``.

Time comes from ``--now <ISO-8601>`` when given (reproducible output for
tests), otherwise the current UTC time. Every metric in --json mode derives
from git history, file existence, or file sizes — never from a value
written inside an agent-authored field.

Exit codes: 0 clean (warnings allowed), 2 usage error, 3 a required tool is
missing, then the class codes above. The lowest non-zero class code wins;
stderr names every class that fired.

The flag surface and the body of the run live in ``census_cli.py`` and
``census_run.py`` beside this file, which re-export ``_build_parser`` and the
run's body: the census stays the module its wrappers, ``python -m noni census``,
``noni census`` and its tests import, and the module a test patches. Each
group's row mechanics are handed to the module that composes that group at the
call from here, so the row shape, its visibility marker and the machine-local
path rule keep one owner.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

# The census's git view lives in census_git.py beside this file; its names are
# re-exported here because the census is their home for callers and for the census's
# own tests, which patch and assert on them through the module they already import.
from .census_git import (  # noqa: F401  (re-exported: the census is their home)
    GIT_ENV_NEUTRAL,
    Git,
    _git_config_args,
    _git_env,
    _git_top,
    _repo_sha1,
    subprocess,
)

# The ledger group's record pass lives in census_ledger_checks.py beside this file;
# the two git-backed integrity checks and the cannot-tell row they share live in
# census_ledger_edited.py. The census re-exports their names and their group
# constants so a caller that already imports the census still names them through it.
from .census_ledger_checks import (  # noqa: F401  (re-exported)
    DATE_RE,
    LEDGER_EMPTY_MESSAGES,
    LEDGER_EMPTY_STATES,
    NAME_RE,
    REQUIRED_LEDGER_FIELDS,
    _validate_record,
    check_ledger,
    check_ledger_empty,
    check_ledger_records,
)
from .census_ledger_edited import (
    append_cannot_tell,
    check_ledger_chain,
    check_ledger_deleted,
    check_ledger_edited,
)
from .census_render import (  # noqa: F401  (re-exported: the census is their home)
    ITEM_STALE_AFTER_DEFAULT,
    NO_STATE_ROOT_NOTE,
    NO_STATE_ROOT_PREFIX,
    ORDERING_CLOSED_CHECK,
    ORDERING_CLOSED_NOT_EVALUATED,
    ORDERING_STALE_AFTER_DEFAULT,
    STALE_AFTER_RE,
    _finding_sort_key,
    _promote,
    _render,
    _severity,
    _threshold,
    _warn_class_names,
    no_state_root_note,
)

# The check contract (the class table, its derived views, the severity rules, the
# threshold and filter helpers and the renderers) lives in census_report.py beside
# this file, and is re-exported here for the same reason: the census is the entry
# point its callers and tests import.
from .census_report import (  # noqa: F401  (re-exported: the census is home)
    CHECKS,
    CLASS_CODE,
    CLASS_FIX,
    CLASS_SEVERITY,
    EXIT_CLEAN,
    EXIT_TOOL_MISSING,
    EXIT_USAGE,
    INTENT_CHECKS,
    ITEM_CHECKS,
    LEDGER_CHECKS,
    ORDERING_CHECKS,
    SCHEMA_VERSION,
    WHOLE_ARTIFACT_KEY,
)

# The row factory and the path/time text helpers live in census_row.py beside this
# file, re-exported as the census's own names: the row shape and the ``--now`` parse
# keep one owner and one spelling, and a seam a test puts on ``census._row`` is the
# one every group's reporter reads at its call.
from .census_row import _parse_iso, _parse_now, _rel_to, _rel_to_root, _row  # noqa: F401  (re-exported: the census is their home)

# The census owns these public spellings: they are patch targets, and each is the
# moved function re-exported under the spelling its callers and tests name, not a
# copy. The ledger reporters' call signature now takes the row mechanics as
# keyword-only arguments, unlike the same-named functions on main.
_append_cannot_tell = append_cannot_tell
_check_ledger_edited = check_ledger_edited
_check_ledger_deleted = check_ledger_deleted
_check_ledger_chain = check_ledger_chain
_check_ledger_empty = check_ledger_empty
_check_ledger_records = check_ledger_records


def _file_kind(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """Classify a file for the census: ("absent"|"regular"|"symlink"|"nonregular", problem).

    ``kind`` is "file" (default) or "dir". Only a regular, non-symlinked
    entry of the requested kind is readable. Symlinked or non-regular
    artefacts are reported as probe failures (never read through a link), and
    a missing entry is absent (a real state, not an oversight).

    The problem half is the text a row quotes when the classification itself
    faulted, so it comes from ``census_text.fault_text``: a stat that raises
    hands the census an ``OSError`` whose ``str()`` ends in the path it failed
    on, and no row may carry that path. Every other return of this function is a
    fixed sentence this file wrote.
    """
    try:
        if path.is_symlink():
            return "symlink", "path is a symlink; the census does not read through links"
        if not _text.path_is_known_missing(path):
            return "absent", None
        if kind == "dir":
            if not path.is_dir():
                return "nonregular", "path is not a directory"
        else:
            if not path.is_file():
                return "nonregular", "path is not a regular file"
    except OSError as e:
        return "nonregular", _text.fault_text(e)
    return "regular", None


# The ledger group's probe is the census's own seam; the row mechanics it uses are
# handed in at the call, so the row shape and the state vocabulary keep their one
# owner here.
def _ledger_probe(ledger: Path) -> _ledger.LedgerProbe:
    """Classify ``ledger`` once through the ledger module's probe; see LedgerProbe.

    The seam the census's own tests patch (a listing that raises, a probe that
    answers a state the tree does not have), so it stays a name of this module
    rather than a direct call into `census_ledger`. The module itself is loaded
    by the loader under 'Ledger and hygiene splits' below.
    """
    return _ledger.probe_ledger(ledger, _file_kind)


def _intent_commit_subject(rel: str) -> str | None:
    """The subject of the last commit that touched ``rel``, from this run's view.

    The seam the intent group asks its citation question through, and the reason
    the class costs no second ``git log`` of its own: the answer is a lookup over
    the history the run already parsed. The view is built over the root
    :func:`_run_root` recorded for the run in flight — the tree ``--repo`` named —
    and never over the process's own directory, so an intent outside that tree is
    never answered for. None means the view holds no commit for that path, or no
    view could be built at all (no run in flight, no git tree, or a history read
    that could not answer), and the group's cannot-tell rule depends on that being
    an answer rather than a verdict.
    """
    root = _run_root()
    if root is None:
        return None
    top = _git_top(root)
    if top is None:
        return None
    git = Git(top)
    return git.commit_subject(rel) if git.available else None


# The root of the run in flight, or None between runs. Set by
# ``census_run._run`` through :func:`_set_run_root` and read by
# :func:`_intent_commit_subject`. A one-element list rather than a module-level
# rebinding so the record is visible through the module object a test already
# imported; and a run that never started answers None, which is the honest
# direction for a seam called outside a run: no root named, no history answered.
_RUN_ROOT: list[Path | None] = [None]


def _set_run_root(root: Path) -> None:
    """Record the tree the run in flight audits; see :func:`_intent_commit_subject`."""
    _RUN_ROOT[0] = root


def _run_root() -> Path | None:
    """The root recorded by :func:`_set_run_root`, or None when no run is in flight."""
    return _RUN_ROOT[0]


def _ledger_name(rel: str) -> str:
    """The identifier a row uses for a directory it could not read.

    Re-exported as the one function, not a copy, so a caller (and the census's
    own tests) still names it through the module it already imports.
    """
    return _ledger.ledger_name(rel)


# --- Ledger and hygiene splits --------------------------------------------------
# The ledger probe and the hygiene class live in census_ledger.py and
# census_hygiene.py beside this
# file. All are ordinary package imports: inside an installed wheel there is no
# sibling file to load by path, and the census's trust in its checker is module
# identity (see census_hygiene._trusted_public_safety), not a resolved filesystem
# path. The row mechanics each one uses are handed in at the call, so the row
# shape keeps its one owner here.
from . import census_hygiene as _helpers  # noqa: E402
from . import census_ledger as _ledger  # noqa: E402
from . import census_text as _text  # noqa: E402

# The probe's type stays reachable as a member of the census, re-exported as the
# one object rather than a copy, so a caller (and the census's own tests) still
# names it through the module it already imports.
LedgerProbe = _ledger.LedgerProbe


# The hygiene class's own parts stay reachable as members of the census: they are
# re-exports of one object, not copies, so the census keeps its single owner of
# the checker and its loader while a caller (and the census's own tests) still
# names them through the module it already imports.
PublicSafetyModule = _helpers.PublicSafetyModule
CENSUS_PS_MODULE_KEY = _helpers.CENSUS_PS_MODULE_KEY
HYGIENE_SCAN_ARTIFACT = _helpers.HYGIENE_SCAN_ARTIFACT
_load_public_safety = _helpers._load_public_safety
_trusted_public_safety = _helpers._trusted_public_safety
_hygiene_labels = _helpers._hygiene_labels
_split_violation = _helpers._split_violation
# The message scrub's own parts stay reachable as members of the census for the
# same reason: one object, not a copy, so the text rules keep their single owner
# in ``census_text`` while a caller (and the census's own tests) still names them
# through the module it already imports.
_bounded = _text._bounded
_stripped = _text._stripped
_clipped = _text._clipped

# The three ordering classes live in census_ordering.py beside this file, their
# reads in census_ordering_readers.py (which obeys the strict JSON rule of
# census_json.py). Their composition, the ``--issue-state`` read and the row
# mechanics handed to them live in ``census_run.py`` beside this file with the
# body of the run, which reads the mechanics back off this module at the call.

# The six item classes live in census_items.py beside this file, their reads in
# census_items_readers.py, and the store's one readdir in census_items_probe.py,
# re-exported here as the census's own seam so the
# group's tests patch a name of the module they already import and the run reaches
# one definition of the readdir.
from .census_items_probe import ItemsProbe, _items_listing  # noqa: E402,F401


def _check_ledger(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                  strict: bool, probe: _ledger.LedgerProbe) -> None:
    """The ledger group, composed by ``census_ledger_checks.check_ledger``.

    The entry point stays a name of this module (the run calls it, and its tests
    pin that call). The row mechanics the composition builds its rows from — the
    row factory, the two root-relative identifiers, the bounders, the classifier,
    the content digest and the cannot-tell row — are named literally at the call,
    never bound into a table or closed over at import: the arguments are looked up
    in this module's globals when the call runs, so a seam a test puts on one of
    them here is the seam the moved reporters read.
    """
    check_ledger(ledger, git, root, findings, strict, probe,
                 row=_row,
                 rel_to=_rel_to,
                 rel_to_root=_rel_to_root,
                 bounded=_bounded,
                 clipped=_clipped,
                 file_kind=_file_kind,
                 repo_sha1=_repo_sha1,
                 cannot_tell=_append_cannot_tell,
                 edit_check=_check_ledger_edited,
                 deletion_check=_check_ledger_deleted,
                 chain_check=_check_ledger_chain,
                 ledger_name=_ledger_name)


def _check_hygiene(top: Path | None, strict: bool, findings: list[dict], *,
                   row: Callable[..., dict], bounded: Callable[..., str]) -> None:
    """The hygiene group, run by the module beside this file.

    The census's own row factory and message bounder are handed in at the call,
    as the other three groups do it, so no second file composes a row.
    """
    _helpers.check_hygiene(top, strict, findings, row=row, bounded=bounded)


# The command line lives in the two modules beside this file: ``census_cli.py``
# builds the parser and ``census_run.py`` holds the body of the run, which reads
# every group off this module at the call (so a seam a test puts on a census name
# is the seam the run uses) and binds no copy of one at import. Both are imported
# last and neither imports this module at its own top, so the split added no
# cycle: whichever module the caller enters first, the other two are complete by
# the time any of them is called.
from .census_cli import _build_parser  # noqa: E402,F401  (re-exported)
from .census_run import _run as _census_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Run the census: the exit code the tool returns for ``argv``.

    The census's one entry point — the skill wrapper, ``python -m noni census``,
    ``noni census`` and the census's own tests all call it here. The body is the
    sibling's (``census_run._run``), so the census keeps its single owner of the
    contract that body asks about.
    """
    return _census_run(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
