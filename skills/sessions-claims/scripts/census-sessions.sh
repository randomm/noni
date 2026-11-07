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
# The body below is the shared preamble of noni/wrapper_bash.py, identical in
# both census wrappers so the two entry points cannot drift apart.

set -u

if [ "$#" -eq 0 ]; then
  echo "census-sessions.sh: no sessions directory given (usage: census-sessions.sh [--help] [census options] <state-root>/noni/sessions)" >&2
  exit 2
fi

# The interpreter, exactly as its caller named it: a program, resolved on PATH.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="$SCRIPT_DIR/census-sessions.py"
py="${NONI_PYTHON:-python3}"

if ! command -v "$py" >/dev/null 2>&1; then
  echo "census-sessions.sh: $py not found on $(hostname 2>/dev/null || echo unknown)" >&2
  exit 3
fi

# The import is probed with the interpreter's stderr captured: a traceback is
# not a diagnostic one can act on, and exit 3 is the code this run has already
# committed to for exactly this state.
if ! "$py" -c 'import noni.census_wrapper' 2>/dev/null; then
  echo "census-sessions.sh: the noni package is not importable; install it or put its src/ on PYTHONPATH" >&2
  exit 3
fi

exec "$py" "$WRAPPER" "$@"
