#!/usr/bin/env bash
# The census entry point. Two checks live under this name, each with its own
# exit-code table and its own golden fixtures under tests/fixtures/:
#
#   census.sh <state-root>/noni/decisions   the decisions census (E1)
#       columns: id date by status live supersedes
#       codes:   0 clean | 2 no ledger dir given | 3 jq missing or the
#                schema program missing (3:schema-program-missing)
#                | 10 record/ledger unusable | 12 edited after commit
#                | 20 supersede chain broken
#       a record is valid when it carries the eight top-level required
#       fields (plus the optional source, decided_by, on_behalf_of and
#       single_option fields) and the chain resolves
#
#   census.sh --sessions <state-root>/noni/sessions   the sessions census (E2)
#       one NDJSON row per finding; read-only, output to stdout only
#       codes:   0 clean | 3 python3 missing | 30 double-claim
#                | 31 claim without a register file | 32 malformed session file
#
# The two checks are never mixed in one run: the dispatch below selects the
# E1 or the E2 path from the flag set, and the exit code is whichever check
# ran. In the E2 path the sessions census is the deterministic arbiter for
# the claim protocol: claims are signals, git delays the second claimant
# (it does not lock), and the census double-claim check (30) is the check
# that catches it at read time.

# --- Dispatch ------------------------------------------------------------------
# The --sessions dispatch reaches into the sibling sessions-claims skill. The
# relative path below is the co-installed default; set NONI_SESSIONS_CENSUS to
# point at a separately installed copy or an adapter to override. (Documented
# dependency: with no override, sessions-claims must be installed at the
# expected relative path.)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -gt 0 ]; then
  case "$1" in
    --sessions) shift
      exec "${NONI_SESSIONS_CENSUS:-$SCRIPT_DIR/../../sessions-claims/scripts/census-sessions.sh}" "$@"
      ;;
  esac
fi

# --- Decisions census (E1) ----------------------------------------------------
# Census of the steering ledger: one line per dated decision record under
# noni/decisions/. Read-only — never writes, never mutates a record.
#
#   census.sh <state-root>/noni/decisions
#
# The one argument is the ledger directory of the state root — the directory
# --repo names for the writers, with noni/decisions under it. There is no
# current-directory default: a run with no argument is a usage error (2),
# because a default of "." would audit whatever directory the caller happened
# to stand in, and a census of the wrong tree is worse than no census. The
# script reads the records and, when the ledger directory lives inside a git
# worktree, the git history to attribute authors and detect post-commit edits.
#
# Columns: id  date  by  status  live  supersedes
# A CHAIN block follows on stderr when the supersede chain is broken.
#
# Exit codes. The codes are distinct so one failing census names the class of
# invariant that broke; when several classes are violated at once, the lowest
# number wins (10 < 12 < 20) and the higher-numbered checks may not have
# been evaluated — the stderr message says so.
#   0   clean — every record valid (the eight top-level required fields
#       plus the optional source, decided_by, on_behalf_of and single_option
#       fields), chain intact
#   2   usage: no ledger directory was given (the state root is named by the
#       caller, never by the cwd)
#   3   jq not found on the reading machine, or the schema program is
#       missing (3:schema-program-missing): census-schema.jq, the sibling file
#       this census reads its record rules from, is not beside this script.
#       A census that cannot read the schema cannot report on a record, so it
#       exits honestly rather than calling an unreadable ledger clean.
#   10  a record is missing or malformed, or the ledger is unusable —
#       five distinct sub-classes, all named on the stderr line:
#       (10:missing-dir) the directory does not exist (operator error —
#       wrong path); (10:bad-name, 10:unparseable, 10:schema,
#       10:missing-record, 10:integral-float) a filename, body, or schema
#       field violates the declared shape (fix the record);
#       (10:empty-ledger) the directory exists but could not be enumerated
#       (a read that happened nowhere is not an empty ledger);
#       (10:git-unavailable) git itself failed on a real repo (fix the tree)
#   42  a ledger directory that holds no *.json record at all — reported as
#       (42:ledger-empty) on stderr and exited 0, the unified census's
#       ledger-empty warn, so a freshly attached project censuses clean here
#       as it does there (issue #97)
#   12  a record was edited after commit (working tree differs from git)
#   20  the supersede chain is broken (dangling, duplicate, orphan, cycle,
#       or a chain resolving to zero or more than one live record)
#
# Requires jq on the machine that does the reading.

# --- Decisions census header end (the --help output ends here) --------------
# The --help branch below prints this file from the second line to this
# marker, so the help text always matches the header and no hard-coded
# line range drifts when the header above changes length.

set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  # The help text is the package constant, not this file's header: `noni census
  # --help` and this shim must print the same bytes. See noni.shim_help and
  # tests/fixtures/census-sh/usage.txt, which is the fixture both routes are
  # compared against. NONI_PYTHON names the interpreter (python3 by default);
  # when the package is not importable the run says so on one plain line and
  # exits 3 rather than letting the interpreter's traceback stand as the
  # diagnostic.
  NONI_PYTHON="${NONI_PYTHON:-python3}"
  if ! command -v "$NONI_PYTHON" >/dev/null 2>&1; then
    echo "census.sh: $NONI_PYTHON not found on $(hostname 2>/dev/null || echo unknown)" >&2
    exit 3
  fi
  # A package that cannot be imported is named on one plain line and exits 3.
  # The import is probed with stderr captured, so the interpreter's traceback
  # never reaches the reader: a traceback is not a diagnostic one can act on,
  # and the shim's exit-code table says 3 for exactly this state.
  if ! help_text="$("$NONI_PYTHON" -c 'import sys; from noni import shim_help; sys.stdout.write(shim_help.CENSUS_SH_HELP + "\n")' 2>/dev/null)"; then
    echo "census.sh: noni package not importable" >&2
    exit 3
  fi
  printf '%s\n' "$help_text"
  exit 0
fi

usage_error() {   # one line naming the fault and the correct shape, then exit 2
  echo "census.sh: $1 (usage: census.sh [--help] <state-root>/noni/decisions)" >&2
  exit 2
}
LEDGER_DIR=""
POSITIONS=0
for arg in "$@"; do
  # One run, one ledger, named once: an unknown option or a second positional is
  # a usage error (2) refused before any probe. Either accepted would audit a
  # tree the caller never named: worse than no census.
  case "$arg" in
    --help|-h) ;;
    -*) usage_error "unknown argument: $arg" ;;
    *) POSITIONS=$((POSITIONS + 1))
      LEDGER_DIR="${arg%/}" ;;
  esac
done
if [ "$POSITIONS" -gt 1 ]; then
  usage_error "one ledger directory at most (got $POSITIONS)"
fi
# An empty LEDGER_DIR means no ledger was named at all: a usage error (2), never
# a census of the cwd (a default of "." audits whatever directory the caller
# happened to stand in).
if [ -z "$LEDGER_DIR" ]; then
  usage_error "no ledger directory given"
fi

command -v jq >/dev/null 2>&1 || { echo "census.sh: jq not found on $(hostname 2>/dev/null || echo unknown)" >&2; exit 3; }

# Refuse every non-directory here rather than at the (10:empty-ledger) branch
# below: a dangling symlink and a plain file both fail -d, and a fallback that
# cannot stat the path must not answer "no records" for it. A directory that
# exists but cannot be listed stays on the find branch, which reports that state
# as its own. The refusal names the path, not which state it was.
if [ ! -d "$LEDGER_DIR" ]; then
  echo "census.sh: ledger dir not found: $LEDGER_DIR (10:missing-dir)" >&2
  exit 10
fi

# Resolve the git top-level so attribution and the post-commit-edit check can
# address paths relative to it. Empty when the ledger is not in a git tree (a
# tarball, a non-git directory): those checks skip rather than fail, and a record
# with no reachable history is reported on its own terms. A failure to cd here
# means the directory became unusable mid-run (absent or unreadable was refused
# above), so it fails closed rather than resolving git against the caller's cwd.
GIT_TOP=""
if GIT_T="$(cd "$LEDGER_DIR" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)" \
   && [ -n "$GIT_T" ] && [ -d "$GIT_T" ]; then
  GIT_TOP="$GIT_T"
  # REL_LEDGER is the ledger dir path relative to the git top, for use in
  # git cat-file / git log pathspecs.
  case "$LEDGER_DIR" in
    "$GIT_TOP"/*) REL_LEDGER="${LEDGER_DIR#$GIT_TOP/}" ;;
    *) REL_LEDGER="" ;;
  esac
  [ -z "$REL_LEDGER" ] && [ "$LEDGER_DIR" = "$GIT_TOP" ] && REL_LEDGER="."
else
  REL_LEDGER=""
fi

# --- Record enumeration ------------------------------------------------------
# The directory is the aggregate; enumerate regular *.json files by name. A
# record name that is not a single path segment matching
# ^[A-Za-z0-9._-]+\.json$ is a schema violation (10:bad-name) before it is
# ever used as a filesystem path or a git pathspec.
STATUS=0
RECORDS=""
while IFS= read -r -d '' rec; do
  REC="${rec##*/}"
  if ! printf '%s' "$REC" | grep -qE '^[A-Za-z0-9._-]+\.json$'; then
    echo "census.sh: $REC: filename is not a plain <name>.json path segment (10:bad-name)" >&2
    STATUS=10
    continue
  fi
  if [ -z "$RECORDS" ]; then
    RECORDS="$REC"
  else
    RECORDS="$RECORDS"$'\n'"$REC"
  fi
done < <(find "$LEDGER_DIR" -maxdepth 1 -type f -name '*.json' -print0 2>/dev/null | LC_ALL=C sort -z)
find_err=""
if [ -z "$RECORDS" ] && [ "$STATUS" -eq 0 ]; then
  # Distinguish "find failed" (e.g. permission denied) from a truly empty dir.
  find_err="$(find "$LEDGER_DIR" -maxdepth 1 -name '*.json' 2>&1 | head -1)"
  if [ -n "$find_err" ] && ! find "$LEDGER_DIR" -maxdepth 1 -name '*.json' >/dev/null 2>&1; then
    # A ledger this script could not enumerate is not an empty ledger: nothing
    # was read, so no verdict about its records was earned. That stays 10.
    echo "census.sh: find failed to enumerate $LEDGER_DIR: $find_err (10:empty-ledger)" >&2
    STATUS=10
  else
    # A recordless decisions/ directory is the unified census's ledger-empty warn
    # (code 42, exit 0), not a failure: a freshly attached project has no records
    # yet and must not read as permanently red, and this shim has no --strict to
    # promote the warn with. One verdict on one tree, whichever census is run
    # (issue #97); the unified census keeps the wording and the promotion.
    echo "census.sh: no *.json records under $LEDGER_DIR (42:ledger-empty)" >&2
  fi
fi

# --- Schema -----------------------------------------------------------------
# One jq program per record validates the declared shape (eight top-level
# required fields plus the four optional ones: source, decided_by,
# on_behalf_of and single_option) and emits "ok"; a non-"ok"
# result is the (fixed, jq-generated) violation message. jq stderr is discarded: an unparseable record is
# distinguished from a schema failure by the follow-up `jq empty` probe, and raw
# record bytes are never echoed back into the diagnostic line.
# The program itself is a sibling file read by jq, so the rules live in one
# place a reader can open and a linter can parse; the path is taken from this
# script's own directory so a relocated census stays self-contained. A missing
# sibling is exit 3 (3:schema-program-missing), the same code as a missing jq:
# without the program there is no schema to apply, and a census that read the
# ledger and reported nothing would be reporting a clean it never established.
SCHEMA_JQ_FILE="$SCRIPT_DIR/census-schema.jq"
if [ ! -f "$SCHEMA_JQ_FILE" ]; then
  echo "census.sh: $SCHEMA_JQ_FILE not found (3:schema-program-missing)" >&2
  exit 3
fi
# Field extraction after a schema pass: id \t date \t status \t sup \t by \t any_answer
SCHEMA_DATA_JQ='
  [ .id, .date, .status,
    (if .supersedes == null then "null" else (.supersedes|tostring) end),
    .by,
    ([.questions[]?.answer // ""] | map(select(. != "")) | length | tostring)
  ] | join("\t")
'

# --- Per-record walk ----------------------------------------------------------
# One pass over the validated records: schema check, field extraction,
# attribution, and the exit-12 check. PAIRS (id \t sup) accumulates
# for the chain walk, so the chain section never re-parses a file.
ROWS="$(mktemp)" || { echo "census.sh: cannot allocate a temp file (mktemp failed)" >&2; exit 3; }
PAIRS="$(mktemp)" || { echo "census.sh: cannot allocate a temp file (mktemp failed)" >&2; rm -f "$ROWS"; exit 3; }
trap 'rm -f "$ROWS" "$PAIRS"' EXIT
: > "$ROWS"
: > "$PAIRS"

while IFS= read -r rec; do
  [ -z "$rec" ] && continue
  f="$LEDGER_DIR/$rec"
  [ -f "$f" ] || { echo "census.sh: $rec not found in $LEDGER_DIR (10:missing-record)" >&2; STATUS=10; printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"; continue; }

  sc="$(jq -r -f "$SCHEMA_JQ_FILE" "$f" 2>/dev/null)"
  if [ "$sc" != "ok" ]; then
    # Distinguish an unparseable record (jq parse error, which -r -e prints
    # to stdout) from a genuine schema violation: on parse failure, `jq empty`
    # also fails, so we report the fixed "not valid JSON" message rather than
    # echoing the raw record bytes. A non-UTF-8 body is named the same way:
    # the fixed wording names the class without echoing the record bytes.
    if ! jq empty "$f" >/dev/null 2>&1; then
      # Non-UTF-8 bodies fall in the same class: the fixed wording names
      # the problem (not valid JSON / not valid UTF-8) without echoing the
      # record bytes, which jq would otherwise quote into its error text.
      if LC_ALL=C grep -q $'[\x80-\xff]' "$f" 2>/dev/null; then
        echo "census.sh: $rec: record is not valid JSON or valid UTF-8 (10:unparseable)" >&2
      else
        echo "census.sh: $rec: record is not valid JSON (10:unparseable)" >&2
      fi
    else
      # Distinguish the integral-float source rejection (a number whose text
    # form is not a bare integer — an integral float such as 42.0 — which
    # census.py's isinstance(int) rejects too) from the other schema
    # violations: the fixed 10:integral-float diagnostic names the shape
    # without echoing the offending value.
    if jq -e '(.source | type) == "object" and ((.source.issue_number | (type == "number") and (tostring | test("^-?[0-9]+$") | not)) or (.source.comment_id | (type == "number") and (tostring | test("^-?[0-9]+$") | not)))' "$f" >/dev/null 2>&1; then
      echo "census.sh: $rec: source.issue_number/comment_id must be a bare JSON integer (an integral float such as 42.0 is not an integer) (10:integral-float)" >&2
    else
      echo "census.sh: $rec: schema violation: $sc (10:schema)" >&2
    fi
    fi
    STATUS=10
    printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"
    continue
  fi

  if ! fields="$(jq -r "$SCHEMA_DATA_JQ" "$f" 2>/dev/null)"; then
    echo "census.sh: $rec: failed to extract fields (10:schema)" >&2
    STATUS=10
    printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"
    continue
  fi
  IFS=$'\t' read -r id date status sup by_body any_answer <<< "$fields"

  printf '%s\t%s\n' "$id" "$sup" >> "$PAIRS"

  # Attribution + history: one git call per record returns both the commit
  # author (%an, the legitimacy check) and the commit hash (%H, for the
  # edited-after-commit check). The pathspec is the validated, plain-basename
  # $rec prefixed with "./" so a leading dash can never be read as a git option.
  # An empty %an (no author to report) leaves the record's own $by standing.
  by_report="$by_body"
  lastc=""
  if [ -n "$GIT_TOP" ] && [ -n "$REL_LEDGER" ]; then
    if ! attr="$(git -C "$GIT_TOP" log -1 --format='%an%x1f%H' -- "${REL_LEDGER:?}/./$rec" 2>/dev/null)"; then
      echo "census.sh: git failed to read history for $rec on a real repo (10:git-unavailable)" >&2
      STATUS=10
      printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"
      continue
    fi
    by_git="${attr%%$'\x1f'*}"
    lastc="${attr##*$'\x1f'}"
    [ -n "$by_git" ] && by_report="$by_git"
  fi

  # Edited-after-commit check (exit 12): working-tree bytes vs the last commit
  # that touched the path. Skipped when the ledger is not in a git tree.
  if [ -n "$GIT_TOP" ] && [ -n "$REL_LEDGER" ] && [ -n "$lastc" ]; then
      h_disk="$(sha1sum "$f" 2>/dev/null | cut -d' ' -f1)"
      h_git="$(git -C "$GIT_TOP" cat-file blob "$lastc:$REL_LEDGER/$rec" 2>/dev/null | sha1sum 2>/dev/null | cut -d' ' -f1)"
      if [ -n "$h_disk" ] && [ -n "$h_git" ] && [ "$h_disk" != "$h_git" ]; then
        echo "census.sh: $rec: edited after commit (working tree differs from git)" >&2
        STATUS=12
      fi
  fi

  # The live column reflects the record's own status field; the per-chain
  # resolution (zero-live / multi-live) is checked below in the chain walk.
  live="no"
  [ "$status" = "decided" ] && live="yes"
  [ "$status" = "open" ] && live="yes"

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$date" "$by_report" "$status" "$live" "$sup" >> "$ROWS"
done <<REOF
$RECORDS
REOF

# --- Supersede chain resolution (exit 20) -------------------------------------
# Runs only when no schema violation (10) was found: the walk needs schema-valid
# records and reads PAIRS, accumulated from the validated pass-1 records above (a
# malformed record never contributes a pair). When 12 already fired the walk is
# skipped and the report says so: precedence is 10 < 12 < 20.
if [ "$STATUS" -ne 10 ]; then
  if [ "$STATUS" -ne 0 ]; then
    echo "census.sh: exit $STATUS already reported; the supersede chain check was not evaluated (priority 10 < 12 < 20)" >&2
  else
    # The status map (id -> status) comes from the validated report rows ($ROWS
    # field 4); $ROWS holds only data lines (the header goes to stdout).
    status_file="$(mktemp)" || { rm -f "$ROWS" "$PAIRS"; echo "census.sh: cannot allocate a temp file (mktemp failed)" >&2; exit 3; }
    awk -F'\t' 'NF >= 6 && $1 != "ERR" { print $1 "\t" $4 }' "$ROWS" > "$status_file"

    # id/sup are indexed by row number: the walk follows row -> supersedes id ->
    # row via id_to_row, so a walk by id string never works. Chain aggregation
    # applies only to roots that are real records (in files): a dangling target
    # gets no chain/livecount entry, so the dangling diagnostic stands alone.
    awk_rc=0
    broken="$(awk -F'\t' '
      FILENAME == ARGV[1] { status_of[$1] = $2; next }
      { id[FNR] = $1; sup[FNR] = $2; files[$1]++; id_to_row[$1] = FNR }
      # find_root(i): follow supersedes from record i to its chain root.
      # Returns "?" on a cycle, the dangling target id otherwise.
      function find_root(i,   t, cyc, r, seen_ctr) {
        t = id[i]; cyc = 0; seen_ctr = 0
        delete seen_map
        while (t in files) {
          r = id_to_row[t]
          if (t in seen_map) { cyc = 1; break }
          seen_map[t] = 1
          if (sup[r] == "null" || sup[r] == "") { delete seen_map; return t }
          t = sup[r]
          if (++seen_ctr > 1000) { cyc = 1; break }
        }
        delete seen_map
        if (cyc) return "?"
        return t   # dangling: t not in files
      }
      # check_live_count(): count live records per chain root and flag
      # zero-live / multi-live chains.
      function check_live_count(   r) {
        for (r in chain)
          if (r in files) {
            c = livecount[r] + 0
            if (c == 0) msg = msg sprintf("\nzero-live: chain %s resolves to no live record (every record in it is superseded)", r)
            if (c > 1) msg = msg sprintf("\nmulti-live: chain %s resolves to more than one live record (expected exactly one)", r)
          }
      }
      END {
        for (i in id) root[i] = find_root(i)
        for (i in id) {
          r = root[i]
          # Chain aggregation only for real roots (dangling roots are not chains)
          if (r in files) {
            chain[r] = 1
            if (status_of[id[i]] != "superseded") livecount[r]++
          }
          if (sup[i] != "null" && sup[i] != "" && !(sup[i] in files))
            msg = msg sprintf("\ndangling: %s supersedes %s (no such record)", id[i], sup[i])
          if (sup[i] != "null" && sup[i] != "") succ_cnt[sup[i]]++
          if (sup[i] == "null" && status_of[id[i]] == "superseded") marked[i] = 1
        }
        for (t in succ_cnt)
          if (succ_cnt[t] > 1) msg = msg sprintf("\nduplicate: %s is superseded by more than one record", t)
        for (i in marked)
          if (succ_cnt[id[i]] + 0 == 0)
            msg = msg sprintf("\norphan: %s is marked superseded but no record supersedes it", id[i])
        for (i in id) if (root[i] == "?")
          msg = msg sprintf("\ncycle: record %s is in a supersedes cycle", id[i])
        check_live_count()
        if (msg != "") { print msg; print "BROKEN" }
        else print "OK"
      }
    ' "$status_file" "$PAIRS" 2>&1)"
    awk_rc=$?
    rm -f "$status_file"
    if [ "$awk_rc" -ne 0 ]; then
      echo "census.sh: chain walk failed (awk exited with status $awk_rc): $broken (20)" >&2
      STATUS=20
    elif [ "$broken" != "OK" ]; then
      STATUS=20
      { echo "CHAIN:"; printf '%s\n' "$broken" | sed '/^$/d' | sed '$d'; } >&2
    fi
  fi
fi

# --- Report -------------------------------------------------------------------
printf 'id\tdate\tby\tstatus\tlive\tsupersedes\n'
[ -f "$ROWS" ] && cat "$ROWS"
exit "$STATUS"
