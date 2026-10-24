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
# number wins (30 < 31 < 32) and the higher-numbered checks may not have been
# evaluated — the stderr message says so:
#   0   clean — every session file valid, no double-claims, all claims have
#       a register file
#   3   a required tool is missing (python3 not found)
#   30  double-claim: two active claims on the same task from different
#       identities (the arbiter check)
#   31  a claim row was committed without a register file under the sessions
#       directory (work is not blocked — report only)
#   32  a session file is malformed (a required field is missing or a claim
#       row has no task reference)
#
# Each non-zero exit prints NDJSON rows on stdout naming the offending task
# or file, e.g. {"type": "double-claim", "task": "#42", "sessions": [...]}.
#
# Requires python3 on the machine that does the reading.

set -u

SESSIONS_DIR=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) sed -n '2,34p' "$0"; exit 0 ;;
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

command -v python3 >/dev/null 2>&1 || {
  echo "census-sessions.sh: python3 not found on $(hostname 2>/dev/null || echo unknown)" >&2
  exit 3
}

exec python3 "$SCRIPT_DIR/census-sessions.py" "$SESSIONS_DIR"
