"""The one home of the program-name label every tool prints.

Every shipped tool owns a constant label equal to the program name it has always
printed (``decide.py``, ``census.py``, ``order.py``,
``intent.py``, ``item.py``, ``brief.py``). The label is
defined here and never derived from ``__file__``: the same bytes must come out
whether the tool ran in place through its wrapper under
``skills/<skill>/scripts/`` or through ``noni <tool>`` from the installed
package, and a name read from the running file differs between the two.

A tool that prints its label with a trailing colon prints ``TOOL + ":"``; the
constants here carry no colon so the one word stays comparable.
"""

from __future__ import annotations

CENSUS = "census.py"
DECIDE = "decide.py"
ORDER = "order.py"
INTENT = "intent.py"
ITEM = "item.py"
BRIEF = "brief.py"
