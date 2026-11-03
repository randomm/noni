"""A session file's field lines, parsed for whoever reads a register file.

:func:`parse_fields` is the register file's own grammar -- the '- key: value' lines
that hold identity, status and the rest -- lifted out of ``register.py`` so that
module holds the writing rules and this holds the reading of one body. A line that
does not match the field shape is not this reader's business: the census is what
flags a malformed register file, and registration needs only identity and status to
be present, so a line without a colon is passed over rather than argued about.

The last write of a repeated key wins, which is what makes a hand-edited file whose
'- status:' line appears twice answer one status rather than two, and a value is
taken up to the next colon so a timestamp keeps its own.
"""

from __future__ import annotations


def parse_fields(body: str) -> dict[str, str]:
    """Parse the '- key: value' field lines of a register file.

    A line that does not match the field shape is left for the census to flag;
    registration needs only identity and status to be present.
    """
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        key, sep, value = line[2:].partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip()
    return fields
