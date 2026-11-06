"""``decide.py``'s path guards, each refusing in the writer's own voice.

:mod:`noni._path_kind` owns the ``lstat`` question -- is every directory from the
state root down to the ledger one this writer may read or write through -- and
:func:`noni._path_kind.direction_refusal` answers it for all three direction
writers. :mod:`noni._writer` owns the mechanics that create a ledger or land a
record's bytes. What lives here is the seam between the two and the printer: the
call that asks one question, and the print that gives its answer ``decide``'s exit
code and ``decide``'s prefix.

Three seams, because this writer has three paths it may not use blindly:

- :func:`refuse_linked_state` asks the DIRECTORY question of every component of the
  writer's guarded list -- ``noni`` first, then ``noni/decisions`` -- before the git
  probes, the first read or the ``mkdir``. A link at ``noni`` is invisible to a
  question asked only of the leaf, because ``lstat`` resolves intermediate
  components, and that is the fault that put a record outside the state repository.
- :func:`refuse_ledger_allocation` is the creation half: :func:`noni._writer.allocate_ledger`
  asks the same directory question before its ``mkdir`` because ``Path.is_dir``
  follows a link and answered "already there" for a linked ledger, making the mkdir
  a no-op and the record's destination a tree outside the repository.
- :func:`refuse_taken_name` is the collision check ``Path.is_file`` cannot make:
  ``is_file()`` follows a link, so a record name already spoken as a link reads as
  free and the atomic replace that follows writes through it.

Every seam prints through the caller's own printer and takes the caller's own exit
constant, so the prefix a reader sees is the command they ran and the number is the
one docs/PRODUCT.md 7, ``skills/steering-ledger/SKILL.md`` and the writer's
docstring all state. Each is two statements at its call site, which is what keeps
them out of :mod:`noni.decide` -- a file at the size limit, where a guard that
reached for its own ``lstat`` would be a second reading of one path, the failure
:mod:`noni._path_kind` exists to prevent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import _path_kind, _writer

# The writer's failure printer: the code it wants back, the headline, the fix hint.
# Positional so a writer hands in its own ``_fail`` and keeps its prefix.
Printer = Callable[[int, str, str], int]

# The two lines the collision refusal prints, spelled once. The record id is unique
# across the ledger because the id IS the filename, so the repair is always another
# slug, and a supersede has its own rule for the date it carries (see the writer's
# --supersedes refusals) -- which the hint restates so one refusal names both the
# rule and the way to satisfy it.
_TAKEN_HEADLINE = "{path} already exists; record ids are unique across the ledger"
_TAKEN_HINT = ("choose a slug nobody has taken; a supersede keeps the --date of the "
               "record it replaces and differs by its slug")


def refuse_linked_state(printer: Printer, code: int, repo: Path,
                        rels: tuple[str, ...]) -> int | None:
    """The exit code for a ``noni/`` this writer may not read or write, or None.

    The walk, its wording and its declined-``lstat`` rule are all
    :func:`noni._path_kind.direction_refusal`: every component of ``rels`` is asked
    of ``lstat``, from the state root down, and an absent one is the ordinary answer
    a first run creates. Nothing here reads, writes or creates, and nothing raises:
    a declined answer is a refusal, never an absence.

    ``code`` is the caller's own constant so the page and the run agree on one
    number, and the printer is the caller's so the prefix stays the command the
    operator invoked.
    """
    refused = _path_kind.direction_refusal(repo, rels)
    return None if refused is None else printer(code, *refused)


def _allocation_refusal(repo: Path, ledger: Path) -> tuple[str, str] | None:
    """The ledger directory asked as a directory, for a caller that wants the pair.

    The one call :func:`refuse_ledger_allocation` makes, exposed for a writer whose
    allocation lives behind its own seam: the question is the guard's and never a
    second ``is_dir()`` beside the mkdir.
    """
    return _path_kind.direction_refusal(repo, (_relative(repo, ledger),))


def _relative(root: Path, path: Path) -> str:
    """``path`` spelled from ``root``, or as an off-tree path the guard cannot walk.

    The writers pass a ledger derived from the same ``--repo`` they hand in, so the
    normal case is a one-word ``relative_to``; a path that does not live under the
    root is spelled verbatim, which the guard's own bounds reject rather than
    inspecting -- a caller cannot aim the directory question above its state root.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def refuse_ledger_allocation(printer: Printer, label: str, code: int, repo: Path,
                             ledger: Path) -> int | None:
    """The exit code for a ledger directory this run may not create, or None.

    The two halves of one allocation, in the order they have to happen: the
    directory question first (the guard, not ``Path.is_dir``, which follows a link
    and answers "already there" for a ``noni/decisions`` that links to a tree
    outside the state repository), then :func:`noni._writer.allocate_ledger`, which
    creates the absent directory the first record needs. Absent is created, a real
    directory is accepted as it stands, and a link or an odd kind comes back as the
    guard's refusal rather than a mkdir through it. A caller asks only after the tree
    has proved itself a work tree with an identity, so a run refused for another
    reason never creates the path it was refused at.
    """
    refused = _allocation_refusal(repo, ledger)
    if refused is not None:
        return printer(code, *refused)
    made = _writer.allocate_ledger(label, repo, ledger)
    return None if made is None else printer(code, *made)


def refuse_taken_name(printer: Printer, code: int, record_path: Path) -> int:
    """The exit code for a record name that is already spoken.

    The writer asks this after its guards have cleared the directory, so anything
    standing at the record's path -- a file, a directory or a link -- is a collision
    and not a name to reuse: the answer is always another slug.
    """
    return printer(code, _TAKEN_HEADLINE.format(path=record_path), _TAKEN_HINT)
