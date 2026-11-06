#!/usr/bin/env bash
# The sessions census: the session register's own entry point.
#
#   census-sessions.sh [--help] [census options] <state-root>/noni/sessions
#
# A thin wrapper, like the skill's other .py entry points. It carries no rules
# and no exit-code table of its own: it finds an interpreter, checks that the
# noni package imports, and execs noni.census_wrapper, which runs the unified
# census over the session group and returns the census's own exit code. The
# single exit-code reference is skills/census/SKILL.md, and the census is the
# arbiter — this script exists so the path the older pages print still runs.
#
# The one argument is the sessions directory of the state root. There is no
# current-directory default, and no option is interpreted here: every flag goes
# to the census, which owns their meaning and their refusals.
#
# Requires a Python 3 that can import the package. NONI_PYTHON names the
# interpreter (python3 by default); a missing interpreter or an unimportable
# package is named on one plain line and exits 3 — the census's own code for a
# tool the reading machine does not have — rather than leaving a traceback as
# the diagnostic.

set -u

if [ "$#" -eq 0 ]; then
  echo "census-sessions.sh: no sessions directory given (usage: census-sessions.sh [--help] [census options] <state-root>/noni/sessions)" >&2
  exit 2
fi

NONI_PYTHON="${NONI_PYTHON:-python3}"
if ! command -v "$NONI_PYTHON" >/dev/null 2>&1; then
  echo "census-sessions.sh: $NONI_PYTHON not found on $(hostname 2>/dev/null || echo unknown)" >&2
  exit 3
fi

# The import is probed with stderr captured so the interpreter's traceback never
# reaches the reader: a traceback is not a diagnostic one can act on, and exit 3
# is the code this run has already committed to for exactly this state.
if ! "$NONI_PYTHON" -c 'import noni.census_wrapper' 2>/dev/null; then
  echo "census-sessions.sh: the noni package is not importable; install it or put its src/ on PYTHONPATH" >&2
  exit 3
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$NONI_PYTHON" "$SCRIPT_DIR/census-sessions.py" "$@"
