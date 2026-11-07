"""The one write ``item.py`` performs: render, move into place, commit the one path.

Mechanics, not the writer's contract. ``item.py`` owns the verbs, the exit codes and
what each run prints; this module owns the three steps every verb ends with -- render
the planned item to its canonical bytes, refuse a store path that is not a directory,
write atomically through the package's one temp-file-then-``os.replace`` writer, and
stage and commit exactly the one path this run wrote.

Nothing here prints, exits or chooses a code: the two codes a refusal can carry
(``exit_io`` for an environment fault, ``exit_refusal`` for what the item itself
refuses) arrive as arguments, and the caller's own ``report`` printer words the
refusal in the writer's voice. The success lines stay with the caller too, so the
verb's own sentence is printed once, by the verb.
"""

from __future__ import annotations

from pathlib import Path

from . import itemschema
from . import order_gitwrite as gitwrite


def write_item(repo: Path, body: dict, rendered: bytes, commit) -> tuple[str, str,
                                                                 str | None]:
    """Put ``rendered`` at the item's path and commit it, or say why it did not.

    Returns ``(verdict, headline, hint)``: ``"ok"`` when the file was written (or
    found unchanged) and committed, ``"unchanged"`` when the file already held these
    bytes and nothing was staged, and ``"refuse"`` with the two lines of the refusal
    the caller prints through its own printer and returns under its own code. Only
    environment faults reach the refusal here — the git answers belong to ``commit``,
    which is the caller's step and owns the committed line and the code of each git
    answer — so this module's whole job is the file: the one shape about the store's
    path the pre-read guard does not own, the idempotence question, and the atomic
    move.
    """
    rel = itemschema.item_rel(body["id"])
    target = repo / rel
    if target.parent.exists() and not target.parent.is_dir():
        # The one shape about the store's path the pre-read guard does not own: an
        # ordinary FILE at noni/items, under a real noni/, which the walk admits
        # because nothing above it is a link. A link there was refused with the rest
        # of the tree at exit 2; a plain file is an environment fault, and mkdir would
        # have failed anyway with a worse message.
        return ("refuse", f"{itemschema.ITEM_DIR} is not a directory",
                f"remove {itemschema.ITEM_DIR} or move it aside, then re-run the "
                "item writer")
    if unchanged(target, rendered):
        return "unchanged", "", None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        gitwrite.write_atomic(target, rendered)
    except OSError as exc:
        return ("refuse",
                gitwrite.written(exc, f"{rel} could not be written"),
                f"check that {itemschema.ITEM_DIR} is writable, then re-run the "
                "item writer")
    return commit(target, rel)


def unchanged(target: Path, rendered: bytes) -> bool:
    """Whether the file already holds these bytes, so the run has nothing to do."""
    if not target.is_file():
        return False
    try:
        same = target.read_bytes() == rendered
    except OSError:
        return False
    return same
