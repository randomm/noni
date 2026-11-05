"""The mechanics that write noni's decision ledger.

``decide.py`` owns the writer's contract: the exit codes, the refusal wording and
the order of the checks. This module owns the three ways a run touches the
filesystem -- allocating the ledger directory, landing a record's bytes atomically,
and staging and committing exactly the paths a run wrote. They are separated
because the seam is where silent drift lives: a writer that open-codes its own
rollback can leave the index holding this run's paths while reporting a clean
tree, so all three land here, beside the :mod:`noni.gitwrite` helpers they share
with the supersede target read.

Nothing here prints or exits. Each helper hands back either the value the writer
asked for or a (headline, hint) pair, which the writer words through its own
printer with its own exit code, so one voice owns every refusal a run can make.
The writer's name arrives as ``label`` for the same reason: a hint that suggests
"re-run decide" has to be issued by the command that refused.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

from . import gitwrite


def allocate_ledger(label: str, repo: Path, ledger: Path) -> tuple[str, str] | None:
    """Why the ledger directory could not be created, or None once it exists.

    A fresh project has no ``noni/`` state, so the writer allocates the directory
    that holds its own record; a tree that will not take it is the write failure it
    reads as. A caller asks only after the tree has proved itself a git work tree
    with an identity, so a run refused for another reason never creates the path it
    was refused at: a ``--repo`` that is not a directory stays absent rather than
    gaining an empty ``noni/``.
    """
    if ledger.is_dir():
        return None
    try:
        ledger.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return (f"the ledger directory {ledger} could not be created "
                f"({exc.__class__.__name__}: {exc.strerror or exc})",
                f"check that {repo} is writable, then re-run {label}")
    return None


def write_record(write: Callable[[Path, str], None], render: Callable[[dict], str],
                 record_path: Path, record: dict,
                 target: tuple[Path, dict, bytes] | None,
                 superseded: str) -> tuple[str, str] | None:
    """Land the record (and the flipped target), or return the refusal to report.

    ``render`` is asked before anything is written: a ``ValueError`` from the
    renderer is a record carrying a number this writer cannot name, and refusing it
    is an exit-4 event rather than a crash at 1 after bytes have landed. Status is
    the one field of an existing record a run may change, so the target is a copy
    with that one value replaced, given the same renderer and the same atomic
    replace as the new record. The caller hands in its own ``write`` and ``render``
    so the mechanics stay the writer's bindings and a test can watch either one.
    """
    try:
        body = render(record)
    except ValueError:
        return _cannot_render()
    write(record_path, body)
    if target is None:
        return None
    flipped = dict(target[1])
    flipped["status"] = superseded
    try:
        body = render(flipped)
    except ValueError:
        return _cannot_render()
    write(target[0], body)
    return None


def _cannot_render() -> tuple[str, str]:
    """The (headline, hint) pair for bytes this writer cannot produce.

    A number json read in (``NaN``, an overflowed literal) has no form the renderer
    may write, and a record the census cannot read back is a ledger nobody will fix.
    """
    return ("the record carries a number this writer cannot name: it is not in the "
            "canonical form decide.py writes",
            "name a record decide.py wrote, or repair it and re-run decide")


def stage_and_commit(label: str, repo: Path, rels: list[str], message: str,
                     target_rel: str | None = None, record_rel: str = "",
                     committed_bytes: bytes | None = None) -> tuple[str, str] | None:
    """Stage and commit exactly ``rels``, or hand back a (headline, hint) refusal.

    ``git add -- <paths>`` then ``commit --only -- <paths>``, so the commit carries
    what this run wrote and never a file somebody else had staged. Either step
    failing rolls both paths back with :func:`noni.gitwrite.rollback`: the pair
    naming the failed step when the undo came back clean, and the undo's own
    wording when it did not, so nothing is ever reported as rolled back that was
    not. The caller owns the exit code and prints the pair through its own printer.
    """
    for verb, result in (("git add", gitwrite.run_git(repo, "add", "--", *rels)),
                         ("git commit", gitwrite.run_git(repo, "commit", "-q", "-m",
                                                          message, "--only", "--", *rels))):
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            unredone = gitwrite.rollback(repo, rels, target_rel, record_rel,
                                         committed_bytes)
            if unredone is not None:
                return gitwrite.undo_wording(f"{verb} failed", unredone, detail, rels)
            return (f"{verb} failed: {detail}",
                    f"{', '.join(rels)} are rolled back to their state before this "
                    f"run; re-run {label}")
    return None


def identity(label: str, run_git: Callable[..., subprocess.CompletedProcess[str]],
             repo: Path) -> tuple[str, tuple[str, str] | None]:
    """The tree's ``git config user.name``, and a (headline, hint) refusal.

    Exactly one of the two is ever set. The work-tree probe and the identity read
    are the two git calls that must answer before anything else is consulted, and
    both faults are refusals to write rather than records to attribute wrongly:
    ``by`` is the one field no flag may set, so the identity has to come from the
    tree git is in. A hung call is reported with the same wording the supersede
    target read uses, so a slow machine never answers for a clean tree.
    """
    work_tree = run_git(repo, "rev-parse", "--is-inside-work-tree")
    named = run_git(repo, "config", "user.name")
    hung = gitwrite.refuse_git_timeout(label, ("rev-parse", work_tree),
                                       ("config", named))
    if hung is not None:
        return "", (hung, f"re-run {label} once git answers again "
                          f"(git -C {repo} rev-parse --is-inside-work-tree)")
    if work_tree.returncode != 0:
        return "", (f"{repo} is not a git work tree",
                    "run decide from the attached project's repo root (git -C REPO "
                    "rev-parse --is-inside-work-tree must succeed)")
    by = named.stdout.strip()
    if named.returncode != 0 or not by:
        return "", (f"git config user.name is not set for {repo}, so the record cannot "
                    "be attributed",
                    "git config user.name is not set: give the tree an identity with "
                    f"git -C {repo} config user.name <name> (or --global)")
    return by, None


def ledger_name(repo: Path, ledger: Path, date_part: str,
                slug: str) -> tuple[str, Path, str]:
    """The record's ``(id, path, repo-relative path)`` for one run.

    ``id`` is ``<date>-<slug>`` and the filename is the id plus the extension, so a
    record's name stays a plain path segment the census can check with one regex and
    the chain can sort by date.
    """
    record_id = f"{date_part}-{slug}"
    record_path = ledger / f"{record_id}.json"
    return record_id, record_path, record_path.relative_to(repo).as_posix()


def supersede_target(load: Callable[[Path, Path, str],
                                    "tuple[Path, dict, bytes] | tuple[str, str] | int"],
                     label: str, repo: Path, ledger: Path, supersedes: str | None,
                     date_part: str) -> tuple[tuple[Path, dict, bytes] | None,
                                               str | None, tuple[str, str] | None]:
    """The ``(target, target_rel, refusal)`` a ``--supersedes`` run will rewrite.

    ``(None, None, None)`` when the run supersedes nothing. ``load`` is the caller's
    target reader (it holds the writer's renderer, which is what the canonical-form
    comparison needs), so this helper owns only the sequencing: a refusal the reader
    hands back is passed through for the caller to word, and the one rule layered on
    top is the date. Chain position, filename stem and census replay order all read
    the target's date, so a supersede dated another day cuts itself out of the chain
    it corrects -- and a target whose ``date`` is not a string was already refused by
    the reader, so the slice below is total.
    """
    if supersedes is None:
        return None, None, None
    found = load(repo, ledger, supersedes)
    if isinstance(found, int) or isinstance(found[0], str):
        return None, None, found  # type: ignore[return-value]
    target_path, target_record, target_committed = found
    target_rel = target_path.relative_to(repo).as_posix()
    if target_record.get("date", "")[:10] != date_part:
        return None, None, (
            f"--date {date_part} is not the date of the record being superseded "
            f"({target_record.get('date')!r})",
            "a supersede carries the date of the record it replaces: pass --date "
            f"{str(target_record.get('date', ''))[:10]}")
    return (target_path, target_record, target_committed), target_rel, None


def target_paths_of(target: "tuple[Path, dict, bytes] | None",
                    record_path: Path) -> tuple[list[str], list[str]]:
    """The ``(record_paths, target_paths)`` the success line names: caller-cwd form,
    record first and target second (issue #77, AC2). Supersedes are the only run
    with two; a run that supersedes nothing names only the record.
    """
    if target is None:
        return [str(record_path)], []
    return [str(record_path), str(target[0])], [str(target[0])]


def success_line(label: str, record_paths: list[str],
                 target_paths: list[str], superseded: str,
                 no_commit: bool) -> str:
    """The one line a successful run prints, naming caller-cwd paths (#77, AC2).

    ``--no-commit`` says committing them is the caller's job (the census reads the
    working tree, so an edited target is census.sh exit 12) and names what the second
    path now holds, so an operator who aborts knows to restore the target as well as
    delete the new record.
    """
    wrote = ', '.join(record_paths)
    if not no_commit:
        return f"{label}: wrote {wrote}"
    left = (f"; {target_paths[0]} now holds status {superseded}"
            if target_paths else "")
    return (f"{label}: wrote {wrote}{left}; left uncommitted: "
            "commit these paths before running the census")


def flag_refusals(fail: Callable[[int, str, str | None], int], exit_usage: int,
                  refuse_name: Callable[..., int | None], slug_re: re.Pattern[str],
                  slug: str, scope: str, asked_by: str, decided_by: str | None,
                  on_behalf_of: str | None,
                  line_free: Callable[[object], bool],
                  options_by_question: dict[str, list[str]],
                  single_option: bool) -> int | None:
    """The exit code of the first usage refusal the flags earn, or None.

    The rules, in the order they are refused: the slug is what the census accepts as
    a plain path segment (a basename outside that pattern is a ``10:bad-name`` row),
    so it goes first because it decides the filename; then the two free-text ids no
    report can name without characters; then the two attribution names, whose shape
    is the census's own predicate handed in as ``line_free`` so the writer refuses
    at the flag what the census would otherwise report at exit 10 after a commit;
    then the marker, which has to be earned by one of the record's questions.
    The pairing (``on_behalf_of`` without ``decided_by``) is the writer's rule and
    neither census enforces it: a delegate decides, and only a delegate's record may
    name who they acted for. The marker rule is the writer's half of a rule both
    censuses report: ``options_by_question`` maps each question id to the options
    given for it, so the check sees what the record will hold rather than the flag
    alone. Both are required and neither has a default: the marker rule reads the
    options map unconditionally, so a defaulting ``None`` would be a signature that
    advertised a call it could not honour -- it would raise, not refuse. ``fail``
    and ``exit_usage`` are the caller's printer and code, so every
    refusal is worded in one voice.
    """
    if not slug_re.fullmatch(slug):
        return fail(exit_usage, f"slug {slug!r} is not a slug",
                    "a slug is [a-z0-9-]+: lowercase letters, digits and dashes, no "
                    "dots, slashes, spaces or uppercase")
    for flag, value, hint in (("--scope", scope,
                               "name the direction area, e.g. --scope 'release ordering'"),
                              ("--asked-by", asked_by,
                               "name the agent role or session that asked")):
        if not value.strip():
            return fail(exit_usage, f"{flag} is empty", hint)
    for flag, value in (("--decided-by", decided_by), ("--on-behalf-of", on_behalf_of)):
        refused = refuse_name(flag, value, fail=fail, exit_usage=exit_usage,
                              line_free=line_free)
        if refused is not None:
            return refused
    if on_behalf_of is not None and decided_by is None:
        return fail(exit_usage,
                    "--on-behalf-of needs --decided-by: a record naming the party "
                    "the decision was made for must also name who made it",
                    "pass --decided-by <who> alongside --on-behalf-of "
                    f"{on_behalf_of!r}, or drop --on-behalf-of")
    if single_option and not any(len(options) == 1
                                 for _qid, options in options_by_question.items()):
        # The marker says a question was asked with one option on purpose; the
        # record it is written on has to show one. A flag with nothing to explain
        # is a mistake at the flag, not a record to commit: the censuses report
        # the same shape as malformed, so refusing here is the earlier, kinder
        # answer to the same question.
        return fail(exit_usage,
                    "--single-option was given but no question has one option",
                    "give one question a single --option, or drop --single-option "
                    "and keep the 2-4-option form")
    return None
