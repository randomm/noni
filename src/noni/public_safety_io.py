"""The guarded open every file read in the package goes through.

Split from ``public_safety`` along the seam the FIFO fix of #91 created: the
open-and-classify step answers five distinct questions about one path, and a read is
built on top of those answers. It is imported as ``noni.public_safety_io`` by
``public_safety``, and tests reach it through ``public_safety`` so the module that owns
the scan keeps owning its seams.

Why an open needs a guard at all: a tracked path is someone else's tree, and ``git
ls-files`` lists index entries without caring what the working tree holds at them. A
named pipe with no writer has nothing to say, so an open without O_NONBLOCK never
returns -- the hygiene scan of #91 blocked inside ``path.read_text`` forever, outside
every timeout and every handler the module has (a blocked read raises nothing, so
``except OSError`` cannot rescue it). The guard therefore sits at the open, and on the
descriptor the open returned:

    os.open(O_RDONLY | O_NONBLOCK)  ->  stat.S_ISREG(os.fstat(fd))  ->  read

``O_NOFOLLOW`` is deliberately absent: a tracked symlink is legitimate content and the
flag would raise ELOOP on it, skipping the file silently. The link is followed and
scanned when its target is a regular file and refused by the same-fd check when it is
not; an ``lstat`` before the open would leave the window in which a regular file is
swapped for a pipe after the check. This is the idiom
``census_intent_readers.read_record`` uses.

The two helpers at the end of this file -- "what is this path, before anyone reads it"
and "the two answers a caller cannot get from the open alone" -- belong to the same
question the guard answers, and are here rather than duplicated in the allowlist loader
because that loader is the third caller of the guard and a per-caller copy of the
absence rule is the drift the guard exists to prevent.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

# The bytes one tracked file may be read into memory. The bound is not a performance
# knob: it is what a read of someone else's tree is willing to hold. A file past it is
# skipped -- content this scan declined to hold, not a file the filesystem refused (the
# fault that is a finding).
MAX_SCAN_FILE_BYTES = 8 << 20

# O_NONBLOCK is on the open itself because that open, not a later read, is what blocks on
# a pipe with no writer. See the module docstring for the whole guard.
SCAN_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)

# The one answer a caller may not close: the path opened but was not a regular file, and
# this module already gave that descriptor back. Negative so no real descriptor can be
# mistaken for it, and distinct from ``None`` ("could not be opened") because
# ``public_safety.load_denylist`` classifies those two the same and neither as "absent".
NOT_REGULAR = -1

# The two errno values that mean "nothing of mine is at that path": the pair of
# ``noni._path_kind.ABSENT_ERRNOS``, repeated as literals so this module needs no package
# sibling. An open faulting with either is a path that vanished after the listing.
ABSENT_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})

# ENXIO is what opening a bound AF_UNIX socket raises on Linux: the kernel refuses the
# open rather than hand back a descriptor for a path with no content and no EOF. It is the
# kind's refusal, so it joins the skips; a real file cannot raise it.
ENXIO = getattr(errno, "ENXIO", None)


def fault_pair(fault: OSError) -> tuple[str, str]:
    """The two fields of a fault a row may carry: its class and its errno words.

    Never the message, which holds the path the syscall failed on: ``str(OSError)`` mixes
    the three, and a row that carried it would leak the machine the scan ran on.
    """
    return (fault.__class__.__name__, fault.strerror or "")


def close(fd: int) -> None:
    """Close a descriptor the caller is finished with, swallowing a bad one.

    The scan never crashes on a path it cannot read, so a descriptor revoked underneath it
    must not raise EBADF.
    """
    try:
        os.close(fd)
    except OSError:
        pass


def open_regular(path: Path) -> tuple[int | None, tuple[str, str] | None]:
    """``(fd, fault)`` for one path: an fd only when it is a regular file.

    Exactly one of the two is ever set, so a caller never reads a fault left over from the
    previous path: ``(fd, None)`` is a readable regular descriptor the caller closes;
    ``(None, None)`` is nothing to report (absent per ``ABSENT_ERRNOS``, opened at a kind
    with no content per ``ENXIO``, or a non-file -- ``NOT_REGULAR``, already closed);
    ``(None, (class, errno words))`` is the open or the ``fstat`` faulting with anything
    else -- the filesystem declining to hand over a regular file.

    Nothing is read on any path: a pipe, socket or device is refused, not read as the empty
    string its immediate EOF would have produced. The ``fstat`` runs on the descriptor that
    was opened, so a path swapped after a pre-open check is refused too. Closing here keeps
    the leak out of callers: the census scans in-process, so a tree of pipes cannot exhaust
    the descriptor table.
    """
    try:
        fd = os.open(path, SCAN_OPEN_FLAGS)
    except OSError as fault:
        # Absent, unreadable, or a link loop -- three answers the caller must tell apart,
        # so a fault that is not absence carries its class and errno words back. ENXIO
        # belongs with the kinds: a socket is a path with no content to read, not a file
        # the filesystem refused.
        if fault.errno in ABSENT_ERRNOS or fault.errno == ENXIO:
            return (None, None)
        return (None, fault_pair(fault))
    try:
        mode = os.fstat(fd).st_mode
    except OSError as fault:
        close(fd)
        # A descriptor the scan cannot classify is a regular file it could not read: the
        # open succeeded, so the filesystem declined to answer about a listed file.
        return (None, fault_pair(fault))
    if not stat.S_ISREG(mode):
        # The kind is reported rather than swallowed because the two lenient callers answer
        # differently for it: a tracked file that is not a file is skipped as if absent,
        # while a deny-list that is not a file must classify the run as corrupt ("absent"
        # would tell the operator to go write one).
        close(fd)
        return (NOT_REGULAR, None)
    return (fd, None)


def read_bytes_capped(fd: int, limit: int = MAX_SCAN_FILE_BYTES) -> bytes | None:
    """Every byte of an open regular descriptor, or None when it exceeds ``limit``.

    The loop is not decoration: ``os.read`` may return fewer bytes than were asked for even
    on a regular file, and a body truncated that way would scan clean on the part nobody
    held. Past the bound the read stops and answers None.
    """
    chunks = bytearray()
    while True:
        chunk = os.read(fd, min(1 << 16, limit + 1 - len(chunks)))
        if not chunk:
            return bytes(chunks)
        chunks += chunk
        if len(chunks) > limit:
            return None


def read_open_regular(fd: int, limit: int = MAX_SCAN_FILE_BYTES) -> (
        tuple[list[str], None] | tuple[None, tuple[str, str]] | None):
    """The lines of a classified regular descriptor, a fault, or None for a skip.

    None is a body this scan declined to hold, never one the filesystem refused. The
    descriptor is closed on every path, including the faulting one.
    """
    try:
        raw = read_bytes_capped(fd, limit)
    except OSError as read_fault:
        # The descriptor faulted after classification succeeded: the same finding as a
        # refused open, with the pair taken from the fault itself.
        return (None, fault_pair(read_fault))
    finally:
        close(fd)
    if raw is None:
        return None
    try:
        return (raw.decode("utf-8").splitlines(), None)
    except UnicodeDecodeError:
        return None


def read_text_lenient(path: Path) -> (
        tuple[list[str], None] | tuple[None, tuple[str, str]] | None):
    """Read a tracked file as text: its lines, a fault, or None for a skip.

    The three answers are the three things a scan may learn about a path it was told to
    audit, and the middle one is the one #91 lost. ``(None, (class, errno words))`` is a
    regular file the scan was refused (EACCES, EIO, an ``fstat`` that faulted): a finding,
    because a scan that cannot read a tracked file cannot certify it. ``None`` is a skip:
    binary or non-UTF-8; not a regular file (see ``open_regular``); gone from the listing
    (``ABSENT_ERRNOS``); opened at a kind with no content (``ENXIO``); or past
    ``MAX_SCAN_FILE_BYTES``.
    """
    fd, fault = open_regular(path)
    if fault is not None:
        return (None, fault)
    if fd is None or fd == NOT_REGULAR:
        return None
    return read_open_regular(fd)


def is_absent(path: Path) -> bool:
    """True only for a path the filesystem describes as absent.

    ``lstat`` rather than ``exists``: ``exists`` follows links and answers False for a
    dangling one, which would make a link to nowhere read as "there is nothing here".
    ENOENT and ENOTDIR are absence; anything else (EACCES on an unreadable directory,
    ELOOP on a link loop, or a path that is a directory rather than a file) is a
    statement about where something lives, not a statement that it is not there.

    The scan itself does not ask this -- a tracked path that vanished after the listing is
    a skip whatever the reason -- but a caller that answers "no configuration" instead of
    "unreadable configuration" needs the distinction, because the two have opposite
    consequences for the run.
    """
    try:
        path.lstat()
    except OSError as fault:
        return fault.errno in ABSENT_ERRNOS
    except Exception:
        # A path the OS layer cannot describe is not a path reported as absent.
        return False
    return False


def is_regular_file(path: Path) -> bool:
    """True when ``path`` is a regular file, without reading or waiting on it.

    The classification the guard makes on an open descriptor, made on a path instead, for
    a caller that must decide *whether to open at all*. The window the guard exists to
    close (a swap between check and open) is not a concern here: the result steers a
    second, guarded open, which re-answers the question on the descriptor it holds.
    """
    fd, _fault = open_regular(path)
    if fd is None or fd == NOT_REGULAR:
        return False
    close(fd)
    return True
