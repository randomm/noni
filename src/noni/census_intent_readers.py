"""The one reader the intent class has: the cited decision record's bytes.

Split from ``census_intent.py`` the way the ordering readers were split from the
ordering group: that module owns the class, its verdicts and its rows, and this one
owns the single open it makes outside the intent file. The refusal lives at that open
and nowhere else, so it lives here in one piece: ``O_NOFOLLOW`` so a link faults
instead of being followed, ``O_NONBLOCK`` so a pipe cannot stall the run, the
``fstat`` of the descriptor that was opened so nothing non-regular is read, and the
loop that reads the body to EOF so a short read cannot truncate a verdict.

Two answers come back from :func:`read_record`, because "the record is wrong" and
"this run could not read the record" are different findings and only the first is a
verdict on the intent. The fault types are named apart from ``_absence``'s list in
``census_intent`` so a path that is there but unreadable is never read as a record
that is not there.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

# The most any one cited record can be, in bytes. The census sets no cap of its own
# on a decision record (the writer's caps are on the intent file), so this is only
# the bound past which this reader stops and calls the read a fault rather than
# reporting a verdict built from the part it happened to get.
_RECORD_READ_LIMIT = 1 << 20


def read_record(record: Path) -> tuple[bytes | None, OSError | None]:
    """The bytes of the record, or the fault that stopped the read.

    The refusal is at this open and not in the caller's earlier classification:
    ``O_NOFOLLOW`` makes a link raise ``ELOOP`` instead of being followed, and the
    ``fstat`` refuses anything that is not a regular file on the very descriptor that
    was opened. A path swapped for a link between the caller's ``lstat`` and this call
    is therefore refused too, which is what keeps the class's promise rather than
    merely intending it.

    ``O_NONBLOCK`` is on the same open for the same reason: a path swapped for a fifo
    after the classification would otherwise block that open forever waiting for a
    writer, and the census's promise is that no path it did not classify can decide a
    verdict or stall the run. The flag matters only for the fifo case -- a regular
    file opens the same either way, so the descriptor is not cleared back to blocking.
    A non-blocking open of a fifo with no writer faults with ``ENXIO``, which
    ``_absence`` does not name, so the state lands on the class's ``cannot-tell`` and
    never on an ``uncited``.

    The body is read until EOF, not one syscall's worth of it: ``os.read`` is free to
    return fewer bytes than were asked for even on a regular file, and a body
    truncated that way would be refused as unparseable -- a verdict on bytes this run
    never held. Bytes past ``_RECORD_READ_LIMIT`` are the same fault: the census read
    part of the record and cannot say what the whole of it holds.
    """
    try:
        fd = os.open(record, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        return None, exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            # ENOTDIR is the absence errno, so the descriptor's own verdict is named
            # apart from it: this is the class's cannot-tell, never the ``uncited``
            # the absence branch would have drawn from a path that is there but holds
            # nothing readable.
            return None, _NonRegularRecord(record)
        return _read_body(fd)
    except (OSError, ValueError, RuntimeError) as exc:
        # The reader is a read of the tree like any other, so it faults with the types
        # every other reader of this class catches: a call the interpreter refused is
        # this run's blindness, never an exception that escapes the census and takes
        # the run down with it.
        return None, exc
    finally:
        os.close(fd)


def _read_body(fd: int) -> tuple[bytes, None] | tuple[None, OSError]:
    """The whole body of an open regular file, or the fault that stopped the read.

    ``None`` body and no fault is impossible; a short ``os.read`` is continued, and a
    file that still has bytes past the limit is a fault, because half a record answers
    nothing about whether the direction it records stands.
    """
    chunks = bytearray()
    while True:
        chunk = os.read(fd, _RECORD_READ_LIMIT - len(chunks))
        if not chunk:
            return bytes(chunks), None
        chunks += chunk
        if len(chunks) >= _RECORD_READ_LIMIT:
            # A body at the limit is a fault only when a further read proves more
            # stands behind it, so a record exactly as large as the bound is still
            # read in full rather than refused.
            if os.read(fd, 1):
                return None, _RecordTooLarge()
            return bytes(chunks), None


class _NonRegularRecord(OSError):
    """The opened descriptor is not a regular file.

    Carries an errno outside ``_absence``'s list on purpose: a fifo or a device at the
    cited path is this run's blindness, and an ENOENT-or-ENOTDIR errno here would be
    read as "no record here" and come out as an ``uncited`` verdict.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(errno.ENXIO, "opened path is not a regular file",
                         str(path))


class _RecordTooLarge(OSError):
    """The cited record is bigger than this reader will hold in memory.

    An errno outside ``_absence``'s list, like the non-regular descriptor's: a record
    too big to read is this run's blindness, and an absence errno here would be drawn
    as the ``uncited`` verdict on a record that is there.
    """

    def __init__(self) -> None:
        super().__init__(errno.E2BIG, "record is larger than the census reads",
                         _RECORD_READ_LIMIT)
