"""The cited-record reader's own structural pins, read off the reader's module.

``census_intent_readers.py`` owns the one open the intent class makes outside the
intent file, and four of its properties are not states a fixture can produce: the
open must refuse a link rather than follow it, must not wait on a pipe, must read the
body to EOF rather than one syscall's worth of it, and must bound what it holds. A
filesystem test cannot distinguish a reader that classified and opened anyway from one
that refused, and no fixture can plant the swap in the process under test -- so these
are read off the syntax tree, where a refactor that keeps the behaviour keeps passing
and one that drops it fails with the reason.

The filesystem states themselves -- a link, a dangling link, a directory, a fifo, a
hardlink, a swap planted after the classification, a short read -- are asserted in
``tests/test_census_intent_cited_record.py``. The gate that refuses a linked ledger
directory above the record is in ``tests/test_census_intent_cited_ledger.py``.
"""

from __future__ import annotations

import pytest
from intent_class_ast import call_line as _call_line
from intent_class_ast import function_source as _function_source
from intent_class_ast import intent_reader_module, intent_reader_text


@pytest.fixture
def reader_text():
    """The source of the module owning the cited-record reader; see the helper's doc."""
    return intent_reader_text()


@pytest.fixture
def reader_ast(reader_text):
    """That module parsed, for the pins about the open, the stat and the read loop."""
    return intent_reader_module(reader_text)


def test_the_cited_record_open_refuses_a_link_without_following_it(reader_ast,
                                                                   reader_text):
    """The refusal lives at the open, not only in the caller's classification.

    A separate ``lstat`` and ``open`` leave an interval in which a path swapped for a
    link after the classification is still followed, so the promise holds only while
    the open itself refuses: ``O_NOFOLLOW``, so a link faults instead of being read,
    and an ``fstat`` of the descriptor that was opened, so nothing non-regular is
    read. Pinned at the syntax tree for the reason above: no fixture can plant the
    swap.
    """
    opened = _call_line(reader_ast, "read_record", "open")
    inspected = _call_line(reader_ast, "read_record", "fstat")
    source = _function_source(reader_ast, "read_record", reader_text)
    assert opened < inspected, (
        "the cited-record reader no longer opens and then inspects the descriptor it "
        "opened, so a link planted after the classification is read through and its "
        "bytes decide the intent verdict"
    )
    assert "O_NOFOLLOW" in source and "S_ISREG" in source, (
        "the cited-record reader lost the flag or the descriptor check that keep a "
        "link and a non-regular path from being read"
    )


def test_the_record_reader_opens_the_cited_path_nonblocking(reader_ast,
                                                            reader_text):
    """The non-blocking flag is on the same open that carries ``O_NOFOLLOW``.

    A separate ``fcntl`` call after the open is too late -- the open itself is what
    blocks on a fifo with no writer -- so the flag has to be in the flags argument of
    the one ``os.open`` the reader makes. Pinned at the tree for the same reason the
    link refusal is: no fixture can plant the swap in the process under test.
    """
    opened = _call_line(reader_ast, "read_record", "open")
    inspected = _call_line(reader_ast, "read_record", "fstat")
    source = _function_source(reader_ast, "read_record", reader_text)
    assert opened < inspected, (
        "the cited-record reader no longer inspects the descriptor it opened, so a "
        "path swapped for a fifo or a link after the classification is read"
    )
    assert "O_NONBLOCK" in source, (
        "the cited-record reader no longer opens with O_NONBLOCK, so a path swapped "
        "for a fifo after the classification blocks the census forever"
    )
    assert "O_NOFOLLOW" in source, (
        "the cited-record reader lost the flag that keeps a planted link from being "
        "followed"
    )


def test_the_record_reader_reads_until_eof_and_refuses_a_body_past_the_limit(
        reader_ast, reader_text):
    """The body comes from a loop, and a record past the bound is a fault.

    One ``os.read`` returns a short read on a busy file system, so the pin is that
    the reader keeps reading; and a body that overruns the bound must not be quoted
    as a verdict, so the limit answers a fault and not a truncation.
    """
    source = _function_source(reader_ast, "_read_body", reader_text)
    assert "while" in source and "os.read" in source, (
        "the cited-record reader no longer loops on os.read, so a short read "
        "truncates the body and a truncated body is a verdict on bytes nobody held"
    )
    assert "_RECORD_READ_LIMIT" in source, (
        "the reader no longer bounds the body it collects, so a record past the "
        "bound is reported as a verdict rather than as a read this run could not do"
    )
