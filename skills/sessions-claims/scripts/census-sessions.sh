#!/usr/bin/env bash
# Census of the session register: one NDJSON row per finding for the session
# files under noni/sessions/. Read-only — never writes, never mutates a
# session file. Output goes to stdout only (no writes under noni/census/).
#
#   census-sessions.sh [SESSIONS_DIR]
#
# SESSIONS_DIR defaults to noni/sessions relative to the current working
# directory. Pass the sessions directory of the clone you want to audit
# (e.g. <clone>/noni/sessions).
#
# The census is the deterministic arbiter for the claim protocol. Two active
# claims on the same task from different identities are a double-claim: git
# delays the second claimant, it does not lock them out, so the census is the
# check that catches it at read time. A claim committed without a register
# file is flagged (distinct code) but the session's work is not blocked — the
# census is report-only.
#
# Exit codes. The codes are distinct so one failing census names the class of
# invariant that broke; when several classes are violated at once, the lowest
# number wins (30 < 31 < 32). Every check runs in a single pass regardless of
# the exit code — the priority only selects which code is returned — so all
# findings are always in the NDJSON output:
#   0   clean — every session file valid (five required fields each), no
#       double-claims, all claims have a register file
#   3   a required tool is missing (python3 not found)
#   30  double-claim: two active claims on the same task from different
#       identities (the arbiter check)
#   31  a claim row was committed without a register file under the sessions
#       directory (work is not blocked — report only)
#   32  a session file is malformed (a required field is missing or a claim
#       row has no task reference)
#
# Each non-zero exit prints NDJSON rows on stdout naming the offending task
# or file, e.g. {"type": "double-claim", "task": "#42", "sessions": [...]},
# plus a stderr line naming the code and noting that all findings are in the
# NDJSON rows.
#
# Requires a Python 3 interpreter on the machine that does the reading. The
# interpreter is $NONI_PYTHON when that variable is set, and python3
# otherwise; the exit-3 check below tests the one actually about to run.
#
# This header is also the --help output: the script prints itself from the
# second line to the first non-comment line of the body below, so the help
# text always matches the header and there is no hard-coded line range that
# drifts when this header changes length.

set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print }' "$0"
  exit 0
fi

SESSIONS_DIR=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) ;;
    -*) ;;
    *) SESSIONS_DIR="${arg%/}" ;;
  esac
done
[ -z "$SESSIONS_DIR" ] && SESSIONS_DIR="noni/sessions"

# The Python core lives in the same directory as this script. The sessions
# census is also reachable as `census.sh --sessions` from the steering-ledger
# skill (skills/steering-ledger/scripts/census.sh dispatches here); this file
# is the direct entry point.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

NONI_PYTHON="${NONI_PYTHON:-python3}"
# An empty NONI_PYTHON is treated as absent: the variable must name an
# interpreter, and an empty word would make `command -v` and `exec` fail in a
# way that does not look like a missing dependency.
[ -n "$NONI_PYTHON" ] || NONI_PYTHON=python3
command -v "$NONI_PYTHON" >/dev/null 2>&1 || {
  echo "census-sessions.sh: $NONI_PYTHON not found on $(hostname 2>/dev/null || echo unknown)" >&2
  exit 3
}

exec "$NONI_PYTHON" "$SCRIPT_DIR/census-sessions.py" "$SESSIONS_DIR"
