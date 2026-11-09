#!/usr/bin/env python3
"""The git plumbing the brief fixture is built from: objects, trees, commits and the index.

``generate.py`` decides what the fixture *contains*; this module decides how a git repository *says*
it. The split is the two things a builder has to get right separately -- the content, and the binary
formats that carry it -- and it keeps either readable without the other in the way.

The repository is constructed rather than shelled out to ``git``, for the reason ``generate.py``
states: every ``git`` step reads the host. Here the only inputs are the document map, the file mode,
an identity line and the commit subjects, so the bytes -- and with them the object ids -- are a pure
function of the fixture's content.

The two layouts that could only be settled by measurement are kept next to the code that writes them
rather than asserted in prose: the tree entry whose mode is ASCII octal, and the index entry whose
fixed head is 62 bytes and not the 64 that a reading of the format gives. Both were pinned by reading
the bytes a real ``git add`` left behind, and both are checked at build time by an assertion rather
than by a fixture that unpacks and then fails to read.

Imported by ``generate.py`` alone. Run directly, it prints the object ids of the tree it would build.
"""

from __future__ import annotations

import hashlib
import zlib
from collections.abc import Callable
from pathlib import Path

# The one branch the fixture carries, and the name ``HEAD`` resolves to. ``master`` because that is
# still what a plain ``git init`` creates, and a fixture whose default branch had a modern name would
# differ from the repositories the cases actually meet.
BRANCH = "refs/heads/master"

# The fixed head of a v2 index entry, in bytes: ten 32-bit words of stat (ctime seconds and
# nanoseconds, mtime seconds and nanoseconds, dev, ino, mode, uid, gid, file size = 40 bytes), then
# the blob's 20-byte id, then one 16-bit path length -- 62 bytes, after which the path begins.
#
# Measured on the bytes a real ``git add`` left in ``.git/index`` rather than counted from the
# format's prose, because where the stage sits relative to the length is the detail a description gets
# wrong and git reports only as "unknown index entry format". The stage is not written: it lives in
# the top bits of the length word, and a fixture with no merge in progress has stage 0, which is the
# zero that word already holds.
INDEX_STAT_WORDS = 10
INDEX_HEAD_BYTES = 62
MODE_WORD = 6                        # after ctime s+ns, mtime s+ns, dev and ino comes the mode


def _object(kind: str, payload: bytes) -> tuple[str, bytes]:
    """The id and the loose-object bytes of one git object.

    ``<kind> <byte length>\\0<payload>``, zlib-compressed at the default level: what ``git`` writes
    for a loose object and what git reads back whatever wrote it. The id is a hash of the
    uncompressed payload, so the fixture's history is a pure function of its content and carries no
    pack, no bitmap and no index left over from the machine that built it.
    """
    raw = f"{kind} {len(payload)}\0".encode("ascii") + payload
    return hashlib.sha1(raw).hexdigest(), zlib.compress(raw)


def tree(entries: list[tuple[str, int, str]]) -> tuple[str, bytes]:
    """One tree object from ``(name, octal-mode, id)`` triples, sorted by name.

    A tree entry is ``<octal-mode> <name>\\0<20-byte-sha>``, the mode written in ASCII octal -- the
    digits, not the number: a tree that said ``33188`` for a regular file is malformed to git, and
    fsck reports it as a bad tree rather than as a near miss. git also requires the entries sorted by
    name (the same rule that makes a tree's id canonical), so they are sorted here rather than
    assembled in call order: a builder that appended a file last would otherwise produce a tree git
    refuses to open, and the failure would surface as a fixture that unpacks but will not read.
    """
    payload = b"".join(f"{oct(mode)[2:]} {name}\0".encode("ascii") + bytes.fromhex(object_id)
                       for name, mode, object_id in sorted(entries))
    return _object("tree", payload)


def _nested(documents: dict[str, bytes]) -> dict:
    """The work tree as nested maps: the shape both the tree objects and the index walk want."""
    root: dict = {}
    for rel, data in documents.items():
        *directories, name = rel.split("/")
        cursor = root
        for part in directories:
            cursor = cursor.setdefault(part, {})
        cursor[name] = data
    return root


def _tree_of(directory: dict, file_mode: int) -> tuple[str, bytes]:
    """The tree object of one directory: its files, then its subdirectories.

    Recursive, so the repository is one call on the root map, and it returns the whole object rather
    than only its id: a tree's bytes are as much part of the repository as its id is, and a builder
    that kept the ids alone would hand back commits pointing at trees no git can read. A directory's
    id is a function of its children's ids, which is what makes the root tree -- and with it every
    commit -- fixed by the fixture's content alone.
    """
    entries: list[tuple[str, int, str]] = []
    for name, value in directory.items():
        if isinstance(value, bytes):
            entries.append((name, file_mode, _object("blob", value)[0]))
        else:
            entries.append((name, 0o40000, _tree_of(value, file_mode)[0]))
    return tree(entries)


def _commit(tree_id: str, parent: str | None, subject: str,
            identity: Callable[[], str]) -> tuple[str, bytes]:
    """One commit object: one identity, one instant, the commit that came before it.

    ``identity`` is called rather than passed as a string because the caller owns the format of the
    line -- ``Name <email> <epoch> +0000`` -- and this module's job is the commit's grammar around it.
    Every commit of the fixture carries the same author and committer date, the instant the suite
    briefs the tree at: the census's ``intent`` class asks only whether a commit touching the intent
    file exists and what its subject says, so a fixed stamp keeps that verdict the same whatever day
    the fixture is unpacked.
    """
    who = identity()
    lines = [f"tree {tree_id}", f"author {who}", f"committer {who}"]
    if parent is not None:
        lines.append(f"parent {parent}")
    return _object("commit", ("\n".join(lines) + f"\n\n{subject}\n").encode("utf-8"))


def commits(documents: dict[str, bytes], file_mode: int, identity: Callable[[], str],
            subjects: list[str]) -> list[tuple[str, bytes]]:
    """The commit objects, oldest first, all carrying the root tree.

    A commit's parent is the one before it, so the chain is linear and its head is the last entry --
    the ``intent: <record-id>`` commit the census's ``intent`` class reads. The root tree is the same
    in all of them, because the fixture is committed in several subjects over one state rather than
    built up over several states: what the census asks is the head's subject, and a head carrying the
    whole tree is the state the page is briefed from.

    The root tree is taken from :func:`_tree_of` here and from the same call :func:`git_objects` makes
    over the same map -- an id computed by two walks that disagreed would produce a commit pointing at
    a tree no git can read, the broken link fsck reports and every case in the suite inherits.
    """
    top_id = _tree_of(_nested(documents), file_mode)[0]
    rows: list[tuple[str, bytes]] = []
    parent: str | None = None
    for subject in subjects:
        commit_id, commit_bytes = _commit(top_id, parent, subject, identity)
        rows.append((commit_id, commit_bytes))
        parent = commit_id
    return rows


def git_objects(documents: dict[str, bytes], file_mode: int, identity: Callable[[], str],
                subjects: list[str]) -> tuple[list[tuple[str, bytes]], dict[str, str]]:
    """The fixture's git objects and its blob ids, as ``(objects, blob_ids)``.

    ``objects`` as ``(40-hex id, loose bytes)`` -- blobs and trees from the work tree, then the
    commits in order; ``blob_ids`` as ``{repository-relative path: blob id}``, which is what the index
    is built from. Loose objects only and no pack, deliberately: a pack is a container whose bytes
    depend on the packer's choices, and everything git needs in this repository is a handful of trees,
    a dozen-odd blobs and three commits.

    The walk collects a directory's object *before* descending into it, so the root is put in
    explicitly by the id :func:`_tree_of` returns -- the one way this builder could otherwise leave a
    commit whose tree is missing from the archive.
    """
    collected: dict[str, bytes] = {}

    def walk(directory: dict) -> None:
        for value in directory.values():
            if isinstance(value, bytes):
                object_id, payload = _object("blob", value)
            else:
                object_id, payload = _tree_of(value, file_mode)
                walk(value)
            collected[object_id] = payload

    nested = _nested(documents)
    walk(nested)
    root_id, root_bytes = _tree_of(nested, file_mode)
    collected[root_id] = root_bytes
    blob_ids = {rel: _object("blob", data)[0] for rel, data in sorted(documents.items())}
    return [*collected.items(), *commits(documents, file_mode, identity, subjects)], blob_ids


def _index_entry(name: str, object_id: str, file_mode: int) -> bytes:
    """One index entry: the stat cache, the blob id, the path length, then the name.

    The head is :data:`INDEX_HEAD_BYTES` long and that length is asserted rather than assumed: a head
    one word off slides the path into the middle of the entry and git then calls the whole index
    unreadable, which is a fixture defect wearing a product failure's clothes.

    Every stat word is zero except the mode. git reads a zero ctime/mtime as "not examined", so a
    status run re-hashes the file and agrees with HEAD on content rather than trusting a stamp carried
    over from the machine that built the fixture. The entry ends with the path, a NUL, and NUL padding
    so the entry's length is a multiple of eight.
    """
    words = [0] * INDEX_STAT_WORDS
    words[MODE_WORD] = file_mode
    head = b"".join(word.to_bytes(4, "big") for word in words)
    head += bytes.fromhex(object_id) + len(name).to_bytes(2, "big")
    assert len(head) == INDEX_HEAD_BYTES, f"index head is {len(head)} bytes, not {INDEX_HEAD_BYTES}"
    body = head + name.encode("utf-8") + b"\0"
    return body + b"\0" * (-len(body) % 8)


def index(blob_ids: dict[str, str], file_mode: int) -> bytes:
    """The git index: the staged tree, in git's v2 binary format.

    The index is what ``git status`` reads, and the brief's read-only cases run it -- so an index that
    disagreed with HEAD would make a clean tree look dirty and the case would be about the fixture
    instead of about the tool. Entries are sorted by path (git's own ordering), counted in the header,
    and the file ends with the 20-byte sha1 of everything before it -- which is the checksum git
    verifies, and the one thing whose absence makes git call the index corrupt. No extension block: a
    plain ``git add`` writes none, and the fixture's index is meant to be indistinguishable from that
    one.
    """
    entries = sorted(blob_ids.items())
    body = b"".join(_index_entry(name, object_id, file_mode) for name, object_id in entries)
    prefix = b"DIRC" + (2).to_bytes(4, "big") + len(entries).to_bytes(4, "big") + body
    return prefix + hashlib.sha1(prefix).digest()


if __name__ == "__main__":  # pragma: no cover -- the hand-run inspector, not a product path
    sys_path_owner = Path(__file__).resolve()
    print(f"{sys_path_owner.name}: objects for the fixture beside generate.py")
