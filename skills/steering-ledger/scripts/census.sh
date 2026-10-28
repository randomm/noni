#!/usr/bin/env bash
# The census entry point. Two checks live under this name, each with its own
# exit-code table and its own golden fixtures under tests/fixtures/:
#
#   census.sh [LEDGER_DIR]                  the decisions census (E1)
#       columns: id date by status live supersedes
#       codes:   0 clean | 3 jq missing | 10 record/ledger unusable
#                | 12 edited after commit | 20 supersede chain broken
#       a record is valid when it carries the eight top-level required
#       fields (plus the optional source field) and the chain resolves
#
#   census.sh --sessions [SESSIONS_DIR]     the sessions census (E2)
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
#   census.sh [LEDGER_DIR]
#
# LEDGER_DIR defaults to the current directory; pass the ledger directory of
# the clone you want to audit (e.g. noni/decisions/). The script reads the
# records and, when LEDGER_DIR lives inside a git worktree, the git history to
# attribute authors and detect post-commit edits.
#
# Columns: id  date  by  status  live  supersedes
# A CHAIN block follows on stderr when the supersede chain is broken.
#
# Exit codes. The codes are distinct so one failing census names the class of
# invariant that broke; when several classes are violated at once, the lowest
# number wins (10 < 12 < 20) and the higher-numbered checks may not have
# been evaluated — the stderr message says so.
#   0   clean — every record valid (the eight top-level required fields
#       plus the optional source field), chain intact
#   3   jq not found on the reading machine
#   10  a record is missing or malformed, or the ledger is unusable —
#       five distinct sub-classes, all named on the stderr line:
#       (10:missing-dir) the directory does not exist (operator error —
#       wrong path); (10:empty-ledger) the directory exists but contains
#       no *.json records (the ledger may simply be empty); (10:bad-name,
#       10:unparseable, 10:schema, 10:missing-record, 10:integral-float)
#       a filename, body, or schema field violates the declared shape (fix
#       the record);
#       (10:git-unavailable) git itself failed on a real repo (fix the tree)
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

LEDGER_DIR=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) ;;
    -*) ;;
    *) LEDGER_DIR="${arg%/}" ;;
  esac
done
[ -z "$LEDGER_DIR" ] && LEDGER_DIR="."

command -v jq >/dev/null 2>&1 || { echo "census.sh: jq not found on $(hostname 2>/dev/null || echo unknown)" >&2; exit 3; }
[ -d "$LEDGER_DIR" ] || { echo "census.sh: ledger dir not found: $LEDGER_DIR (10:missing-dir)" >&2; exit 10; }

# Resolve the git top-level so attribution and the post-commit-edit check can
# address paths relative to it. Empty when the ledger is not in a git tree
# (a tarball or non-git directory): those checks then skip rather than fail,
# and a record with no reachable history is reported on its own terms.
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
    echo "census.sh: find failed to enumerate $LEDGER_DIR: $find_err (10:empty-ledger)" >&2
  else
    echo "census.sh: no *.json records under $LEDGER_DIR (10:empty-ledger)" >&2
  fi
  STATUS=10
fi

# --- Schema -----------------------------------------------------------------
# One jq program per record validates the declared shape (eight top-level
# required fields plus the one optional source field) and emits "ok"; a non-"ok" result is the (fixed, jq-generated)
# violation message. jq stderr is discarded: an unparseable record is
# distinguished from a schema failure by the follow-up `jq empty` probe, and raw
# record bytes are never echoed back into the diagnostic line.
SCHEMA_JQ='
  def is_iso: (.date | type) == "string"
    and (.date | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"));
  # The calendar probe only makes sense for a date string; any non-string
  # reaches the report as the (more accurate) "not a valid ISO-8601" message.
  def cal_ok: (if (.date | type) == "string" then
    (if .date[5:7] | tonumber as $m | $m >= 1 and $m <= 12 then true else false end)
    and (if .date[8:10] | tonumber as $d | $d >= 1 and $d <= 31 then true else false end)
    and (if .date[11:13] | tonumber as $h | $h <= 23 then true else false end)
    and (if .date[14:16] | tonumber as $mi | $mi <= 59 then true else false end)
    and (if .date[17:19] | tonumber as $s | $s <= 60 then true else false end)
    else false end);
  def has8:
    has("id") and has("date") and has("asked_by") and has("questions")
    and has("by") and has("scope") and has("status") and has("supersedes");
  # The closed set is the eight required fields plus the one optional
  # source field: exactly eight keys when source is absent, nine when
  # present.
  def closed8: ((keys_unsorted | length) == 8
    or ((keys_unsorted | length) == 9) and has("source"));
  # source: absent or null is fine; present-and-non-null it must be an
  # object with exactly the two fields (issue_number, comment_id), each a
  # JSON integer. A JSON integer is a number whose textual form carries
  # no decimal point or exponent; the floor check alone would pass an
  # integral float (42.0), so both conditions must hold. This is the rule
  # census.py mirrors exactly with isinstance(int) plus not-bool, and the
  # two entry points must agree on every source shape.
  def is_int: (type == "number")
    and (tostring | test("^-?[0-9]+$"))
    and (. == floor);
  def source_ok:
    ((has("source") | not) or (.source == null) or
      ((.source | type) == "object")
      and ((.source | has("issue_number")) and (.source | has("comment_id")))
      and (((.source | keys_unsorted) - ["issue_number","comment_id"]) | length == 0)
      and (.source.issue_number | is_int)
      and (.source.comment_id | is_int));
  def questions_ok:
    ((.questions | type) == "array")
    and ((.questions | length) >= 1) and ((.questions | length) <= 4)
    and (all(.questions[];
      has("id") and has("text") and has("options")
      and ((.options | type) == "array")
      and ((.options | length) >= 2) and ((.options | length) <= 4)
      and (all(.options[]; type == "string"))
      and (if has("answer")
           then (.answer == null or (.answer | type) == "string")
           else true end)
      and ((if has("answer") then 4 else 3 end) == (keys_unsorted | length))
    ));
  def status_ok: (.status | IN("decided","open","superseded"));
  def id_ok: ((.id | type) == "string") and ((.id | length) > 0);
  def by_ok: ((.by | type) == "string") and ((.by | length) > 0);
  def asked_by_ok: ((.asked_by | type) == "string") and ((.asked_by | length) > 0);
  def scope_ok: ((.scope | type) == "string") and ((.scope | length) > 0);
  def sup_type_ok: ((.supersedes == null) or
    ((.supersedes | type) == "string") and ((.supersedes | length) > 0));
  # The empty string is rejected: it is neither "no supersede" (null) nor a
  # valid record id, and accepting it would make the chain walk ambiguous.
  # (sup_type_ok already covers this via length > 0; stated here so the
  # intent is explicit.)
  if has8 and closed8 and is_iso and cal_ok and questions_ok and status_ok
     and id_ok and by_ok and asked_by_ok and scope_ok and sup_type_ok and source_ok
  then "ok"
  else
    [ (if has8 then "" else
        "missing field(s): " + ([
          (if has("id") then "" else "id" end),
          (if has("date") then "" else "date" end),
          (if has("asked_by") then "" else "asked_by" end),
          (if has("questions") then "" else "questions" end),
          (if has("by") then "" else "by" end),
          (if has("scope") then "" else "scope" end),
          (if has("status") then "" else "status" end),
          (if has("supersedes") then "" else "supersedes" end)
        ] | map(select(. != "")) | join(",")) end),
      (if closed8 | not then "unknown field(s): " + (((keys_unsorted // []) - ["id","date","asked_by","questions","by","scope","status","supersedes","source"]) | join(",")) else "" end),
      (if source_ok | not then "source must be null or an object with issue_number and comment_id" else "" end),
      (if is_iso | not then "date is not a valid UTC ISO-8601 string" else "" end),
      (if cal_ok | not then "date components out of range (month 1-12, day 1-31, hour 0-23, minute 0-59, second 0-60)" else "" end),
      (if questions_ok | not then "questions array or option bounds violated" else "" end),
      (if status_ok | not then "status not one of decided|open|superseded" else "" end),
      (if id_ok | not then "id missing or not a non-empty string" else "" end),
      (if by_ok | not then "by missing or not a non-empty string" else "" end),
      (if asked_by_ok | not then "asked_by missing or not a non-empty string" else "" end),
      (if scope_ok | not then "scope missing or not a non-empty string" else "" end),
      (if sup_type_ok | not then "supersedes must be null or a non-empty string" else "" end)
    ] | map(select(. != "")) | join("; ")
  end
'
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

  sc="$(jq -r "$SCHEMA_JQ" "$f" 2>/dev/null)"
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
  # $rec prefixed with "./" so a leading dash can never be read as a git
  # option. The NUL separator keeps fields with embedded spaces safe.
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
    if [ -n "${by_git:-}" ]; then
      by_report="$by_git"
    fi
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
# Runs only when no schema violation (exit 10) was found: the chain walk
# needs schema-valid records, and it reads PAIRS, which was accumulated from
# the validated pass-1 records above (a malformed record never contributes a
# pair). When a higher-priority code (12) already fired, the chain walk
# is skipped and the report says so: the documented precedence is
# 10 < 12 < 20.
if [ "$STATUS" -ne 10 ]; then
  if [ "$STATUS" -ne 0 ]; then
    echo "census.sh: exit $STATUS already reported; the supersede chain check was not evaluated (priority 10 < 12 < 20)" >&2
  else
    # status map (id -> status) from the validated report rows ($ROWS field 4);
    # $ROWS holds only data lines (the header is printed to stdout, not $ROWS).
    status_file="$(mktemp)" || { rm -f "$ROWS" "$PAIRS"; echo "census.sh: cannot allocate a temp file (mktemp failed)" >&2; exit 3; }
    awk -F'\t' 'NF >= 6 && $1 != "ERR" { print $1 "\t" $4 }' "$ROWS" > "$status_file"

    # id/sup are indexed by row number; the walk follows row -> supersedes id
    # -> row via the id_to_row map, so a walk by id string never works.
    # Chain aggregation only applies to roots that are real records (in files):
    # a record whose supersedes target does not exist (dangling) gets no
    # chain/livecount entry, so the dangling diagnostic stands alone.
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
      {
        echo "CHAIN:"
        printf '%s\n' "$broken" | sed '/^$/d' | sed '$d'
      } >&2
    fi
  fi
fi

# --- Report -------------------------------------------------------------------
printf 'id\tdate\tby\tstatus\tlive\tsupersedes\n'
[ -f "$ROWS" ] && cat "$ROWS"

exit "$STATUS"
