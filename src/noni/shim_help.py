"""The --help text of the two bash census shims, as package-owned constants.

The shims used to print their own header comment, so the same bytes could not
come from both the shim and the package. The text lives here once and both
routes emit these constants: ``tests/fixtures/census-sh/usage.txt`` and
``sessions-usage.txt`` are the single source of truth the tests compare both
routes against.

A shim prints the constant verbatim, so what a reader sees is the bytes written
here.
"""

from __future__ import annotations

CENSUS_SH_HELP = """The census entry point. Two checks live under this name, each with its own
exit-code table and its own golden fixtures under tests/fixtures/:

  census.sh <state-root>/noni/decisions        the decisions census (E1)
      columns: id date by status live supersedes
      codes:   0 clean | 2 no ledger dir given | 3 jq missing
               | 10 record/ledger unusable | 12 edited after commit
               | 20 supersede chain broken
      a record is valid when it carries the eight top-level required
      fields (plus the optional source field) and the chain resolves

  census.sh --sessions <state-root>/noni/sessions   the sessions census (E2)
      one NDJSON row per finding; read-only, output to stdout only
      codes:   0 clean | 2 no sessions dir given | 3 python3 missing
               | 30 double-claim | 31 claim without a register file
               | 32 malformed session file

The one argument each check takes is the state directory of the state root —
the directory --repo names for the writers — and neither check has a
current-directory default: run with no argument, either path is a usage error
(2) rather than a census of whatever noni/ happened to sit next to the caller.

The two checks are never mixed in one run: the dispatch below selects the
E1 or the E2 path from the flag set, and the exit code is whichever check
ran. In the E2 path the sessions census is the deterministic arbiter for
the claim protocol: claims are signals, git delays the second claimant
(it does not lock), and the census double-claim check (30) is the check
that catches it at read time."""

CENSUS_SESSIONS_SH_HELP = """Census of the session register: one NDJSON row per finding for the session
files under noni/sessions/. Read-only — never writes, never mutates a
session file. Output goes to stdout only (no writes under noni/census/).

  census-sessions.sh <state-root>/noni/sessions

The one argument is the sessions directory of the state root — the directory
--repo names for the writers, with noni/sessions under it. Pass the sessions
directory of the clone you want to audit. There is no current-directory
default: a run with no argument is a usage error (2), because a relative
default would census whatever noni/sessions happened to sit next to the
caller and report a clean the caller never pointed at.

The census is the deterministic arbiter for the claim protocol. Two active
claims on the same task from different identities are a double-claim: git
delays the second claimant, it does not lock them out, so the census is the
check that catches it at read time. A claim committed without a register
file is flagged (distinct code) but the session's work is not blocked — the
census is report-only.

Exit codes. The codes are distinct so one failing census names the class of
invariant that broke; when several classes are violated at once, the lowest
number wins (30 < 31 < 32). Every check runs in a single pass regardless of
the exit code — the priority only selects which code is returned — so all
findings are always in the NDJSON output:
  0   clean — every session file valid (five required fields each), no
      double-claims, all claims have a register file
  2   usage: no sessions directory was given, or the one given is not a
      directory (the state root is named by the caller, never by the cwd)
  3   the interpreter it would run is missing (see NONI_PYTHON below)
  30  double-claim: two active claims on the same task from different
      identities (the arbiter check)
  31  a claim row was committed without a register file under the sessions
      directory (work is not blocked — report only)
  32  a session file is malformed (a required field is missing or a claim
      row has no task reference)

Each non-zero exit prints NDJSON rows on stdout naming the offending task
or file, e.g. {"type": "double-claim", "task": "#42", "sessions": [...]},
plus a stderr line naming the code and noting that all findings are in the
NDJSON rows.

Requires a Python 3 interpreter on the machine that does the reading. The
interpreter is $NONI_PYTHON when that variable is set, and python3
otherwise; the exit-3 check below tests the one actually about to run.

This header is also the --help output: the script prints this constant, so the
help text has exactly one owner and no hard-coded line range can drift when it
grows. The Python core is the ``noni`` package (``noni.census_sessions``); the
sessions census is also reachable as `census.sh --sessions` from the
steering-ledger skill (skills/steering-ledger/scripts/census.sh dispatches
here); this script is the direct entry point."""
