"""One bash preamble for the two shell census wrappers.

Both ``census.sh`` and ``census-sessions.sh`` have to find an interpreter, prove
the package imports, and exec the in-place wrapper beside them. That sequence is
byte-identical in the two files, and a preamble two scripts each grew on their
own is exactly how the two entry points drifted apart before: the census gained a
verdict, one script found out. So the preamble lives here as one string, and
``tests/test_census_wrapper_preamble.py`` asserts the shipped files still carry
it -- the same way the help fixtures pin the usage text.

What the preamble does, and why each line is there:

- It refuses zero arguments with the census's usage code rather than defaulting
  to a directory the caller did not name: a census of the wrong tree is a green
  that means nothing.
- It takes its interpreter from ``NONI_PYTHON`` (``python3`` by default), exactly
  as set: the value is the *program* and must resolve on ``PATH``. A caller who
  needs flags for that program -- an isolated interpreter, say -- sets ``PATH``,
  ``PYTHONHOME`` or a wrapper of their own, which is the portable way to say it:
  a space in the value means a program by that name, and a program by that name
  does not exist. Naming the variable and its default in one place keeps the two
  wrappers and the tests from disagreeing about which variable a caller sets.
- It probes the import with the interpreter's stderr swallowed. A traceback is
  not a diagnostic a reader can act on; one line naming the fault is, and exit 3
  is the census's own code for a tool the reading machine does not have.
- It execs the ``.py`` of the same name beside itself, so the exit code that
  reaches the caller is the census's and not a shell's reading of it.

The wrapper's own refusal is the only refusal this file contains: it carries no
rules, no schema and no exit-code table. The single exit-code reference is
``skills/census/SKILL.md``.

The text below is written in the shell's own spelling -- dollars and braces
included -- so a reader of this file reads the script. The caller's words
(``@label@``, ``@noun@``, ``@script@``) are substituted with ``str.replace``,
never ``str.format``: a ``format`` pass over bash source would read every
``${VAR}`` as a field.
"""

from __future__ import annotations

#: The interpreter variable a caller may set, and the default when it is
#: unset. Named once here so the two wrappers and the tests cannot disagree
#: about which variable a caller sets.
PYTHON_VAR = "NONI_PYTHON"
PYTHON_DEFAULT = "python3"

_PRELUDE = """\
set -u

if [ "$#" -eq 0 ]; then
  echo "@label@: no @noun@ directory given (usage: @label@ [--help] [census options] <state-root>/noni/@noun@)" >&2
  exit 2
fi

"""

_INTERPRETER = """\
# The interpreter, exactly as its caller named it: a program, resolved on PATH.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="$SCRIPT_DIR/@script@"
py="${@PYTHON_VAR@:-@PYTHON_DEFAULT@}"

if ! command -v "$py" >/dev/null 2>&1; then
  echo "@label@: $py not found on $(hostname 2>/dev/null || echo unknown)" >&2
  exit 3
fi

"""

_PROBE = """\
# The import is probed with the interpreter's stderr captured: a traceback is
# not a diagnostic one can act on, and exit 3 is the code this run has already
# committed to for exactly this state.
if ! "$py" -c 'import noni.census_wrapper' 2>/dev/null; then
  echo "@label@: the noni package is not importable; install it or put its src/ on PYTHONPATH" >&2
  exit 3
fi

exec "$py" "$WRAPPER" "$@"
"""


def preamble(label: str, noun: str, script: str) -> str:
    """The bash preamble for one wrapper.

    ``label`` is the name the diagnostics print (the script's own name), ``noun``
    the directory the caller must name (``decisions`` or ``sessions``), and
    ``script`` the in-place ``.py`` beside it to exec.
    """
    text = _PRELUDE + _INTERPRETER + _PROBE
    for token, value in (("@label@", label), ("@noun@", noun),
                         ("@script@", script), ("@PYTHON_VAR@", PYTHON_VAR),
                         ("@PYTHON_DEFAULT@", PYTHON_DEFAULT)):
        text = text.replace(token, value)
    return text
