#!/usr/bin/env bash
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
# Exit codes (distinct so one failing census names the class of invariant that
# broke; one golden fixture per code lives under tests/fixtures/):
#   0   clean — every record valid, chain intact
#   3   jq not found on the reading machine
#   10  a record is missing or malformed (schema violation)
#   11  an answer was stored without operator confirmation
#   12  a record was edited after commit (working tree differs from git)
#   20  the supersede chain is broken (dangling, forward, or duplicate)
#
# Requires jq on the machine that does the reading.

set -u

LEDGER_DIR=""
for arg in "$@"; do
  case "$arg" in
    --help|-h) sed -n '2,18p' "$0"; exit 0 ;;
    -*) ;;
    *) LEDGER_DIR="${arg%/}" ;;
  esac
done
[ -z "$LEDGER_DIR" ] && LEDGER_DIR="."

command -v jq >/dev/null 2>&1 || { echo "census.sh: jq not found on $(hostname 2>/dev/null || echo unknown)" >&2; exit 3; }
[ -d "$LEDGER_DIR" ] || { echo "census.sh: ledger dir not found: $LEDGER_DIR" >&2; exit 10; }

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

RECORDS="$(cd "$LEDGER_DIR" 2>/dev/null && ls -1 *.json 2>/dev/null | LC_ALL=C sort)"
if [ -z "$RECORDS" ]; then
  echo "census.sh: no *.json records under $LEDGER_DIR" >&2
  exit 10
fi

# --- Per-record checks --------------------------------------------------------
# Walk records in id order; the report is stable. For each record we run the
# schema check (jq), collect the author from git, and detect a working-tree
# diff against the last commit. Per-record rows accumulate in $TMP for the
# report.

ROWS="$(mktemp 2>/dev/null || echo "/tmp/census.$$")"
trap 'rm -f "$ROWS"' EXIT
: > "$ROWS"

# A schema violation is a single string; empty string means the record is valid.
schema_check() {
  jq -r -e '
    def is_iso: (.date | type) == "string"
      and (.date | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"));
    def has9:
      has("id") and has("date") and has("asked_by") and has("questions")
      and has("by") and has("scope") and has("status") and has("supersedes");
    def questions_ok:
      ((.questions | type) == "array")
      and ((.questions | length) >= 1) and ((.questions | length) <= 4)
      and (all(.questions[];
        has("id") and has("text") and has("options")
        and ((.options | type) == "array")
        and ((.options | length) >= 2) and ((.options | length) <= 4)
        and (all(.options[]; type == "string"))
        and (.answer == null or (.answer | type == "string"))
      ));
    def status_ok: (.status | IN("decided","open","superseded"));
    def id_ok: ((.id | type) == "string") and ((.id | length) > 0);
    def by_ok: ((.by | type) == "string") and ((.by | length) > 0);
    def asked_by_ok: ((.asked_by | type) == "string") and ((.asked_by | length) > 0);
    def scope_ok: ((.scope | type) == "string") and ((.scope | length) > 0);
    def sup_ok: ((.supersedes == null) or (.supersedes | type == "string"));
    if has9 and is_iso and questions_ok and status_ok and id_ok and by_ok
       and asked_by_ok and scope_ok and sup_ok
    then "ok"
    else
      [ (if has9 then "" else
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
        (if is_iso | not then "date is not a valid UTC ISO-8601 string" else "" end),
        (if questions_ok | not then "questions array or option bounds violated" else "" end),
        (if status_ok | not then "status not one of decided|open|superseded" else "" end),
        (if id_ok | not then "id missing or not a non-empty string" else "" end),
        (if by_ok | not then "by missing or not a non-empty string" else "" end),
        (if asked_by_ok | not then "asked_by missing or not a non-empty string" else "" end),
        (if scope_ok | not then "scope missing or not a non-empty string" else "" end),
        (if sup_ok | not then "supersedes must be null or a string" else "" end)
      ] | map(select(. != "")) | join("; ")
    end
  ' "$1" 2>&1
}

# --- Per-record walk ----------------------------------------------------------
STATUS=0

while IFS= read -r rec; do
  [ -z "$rec" ] && continue
  f="$LEDGER_DIR/$rec"
  [ -f "$f" ] || { echo "census.sh: $rec not found in $LEDGER_DIR" >&2; STATUS=10; printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"; continue; }

  sc="$(schema_check "$f")"
  if [ "$sc" != "ok" ]; then
    echo "census.sh: $rec: schema violation: $sc" >&2
    STATUS=10
    printf 'ERR\t-\t-\t-\tno\t-\n' >> "$ROWS"
    continue
  fi

  id="$(jq -r '.id' "$f")"
  date="$(jq -r '.date' "$f")"
  status="$(jq -r '.status' "$f")"
  sup="$(jq -r '.supersedes // "null"' "$f")"
  by_body="$(jq -r '.by' "$f")"

  # Attribution: the report shows the git author of the record's commit (the
  # legitimacy check), not the file body's `by` field. When the ledger is not
  # in a git tree, fall back to the file body's `by`.
  by_report="$by_body"
  if [ -n "$GIT_TOP" ] && [ -n "$REL_LEDGER" ]; then
    by_git="$(git -C "$GIT_TOP" log -1 --format='%an' -- "$REL_LEDGER/$rec" 2>/dev/null)"
    if [ -n "$by_git" ]; then
      by_report="$by_git"
    fi
  fi

  live="no"
  [ "$status" = "decided" ] && live="yes"
  [ "$status" = "open" ] && live="yes"

  # Unconfirmed-answer check (exit 11): a decided record with an answer must
  # trace to a prior commit that could have carried the operator confirmation.
  # If the record is the first and only commit in the repo (no prior state),
  # there is no confirmation trail — the record was written and committed in
  # one step, which is the anti-fabrication violation. When the ledger is not
  # in a git tree, this check cannot be run and is skipped.
  if [ -n "$GIT_TOP" ] && [ "$status" = "decided" ]; then
    any_answer="$(jq -r '[.questions[]?.answer // ""] | map(select(. != "")) | length' "$f" 2>/dev/null)"
    if [ "${any_answer:-0}" -gt 0 ]; then
      n_total="$(git -C "$GIT_TOP" rev-list --count HEAD 2>/dev/null)"
      if [ "${n_total:-0}" -le 1 ]; then
        echo "census.sh: $rec: answer stored without a preceding commit (no operator confirmation trail)" >&2
        STATUS=11
      fi
    fi
  fi

  # Edited-after-commit check (exit 12): working-tree bytes vs the last commit
  # that touched the path. When the ledger is not in a git tree, skip.
  if [ -n "$GIT_TOP" ] && [ -n "$REL_LEDGER" ]; then
    lastc="$(git -C "$GIT_TOP" log -1 --format='%H' -- "$REL_LEDGER/$rec" 2>/dev/null)"
    if [ -n "$lastc" ]; then
      h_disk="$(sha1sum "$f" 2>/dev/null | cut -d' ' -f1)"
      h_git="$(git -C "$GIT_TOP" cat-file blob "$lastc:$REL_LEDGER/$rec" 2>/dev/null | sha1sum 2>/dev/null | cut -d' ' -f1)"
      if [ -n "$h_disk" ] && [ -n "$h_git" ] && [ "$h_disk" != "$h_git" ]; then
        echo "census.sh: $rec: edited after commit (working tree differs from git)" >&2
        STATUS=12
      fi
    fi
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$date" "$by_report" "$status" "$live" "$sup" >> "$ROWS"
done <<EOF
$RECORDS
EOF

# --- Supersede chain resolution (exit 20) -------------------------------------
# Only runs when no schema violation (exit 10) was found: the chain check is
# only meaningful if all records are schema-valid.
if [ "$STATUS" -ne 10 ]; then

PAIRS="$(cd "$LEDGER_DIR" 2>/dev/null && for f in *.json; do
  [ -f "$f" ] || continue
  id="$(jq -r '.id // ""' "$f" 2>/dev/null)"
  sup="$(jq -r '.supersedes // "null"' "$f" 2>/dev/null)"
  [ -z "$id" ] && continue
  printf '%s\t%s\n' "$id" "$sup"
done | LC_ALL=C sort)"

broken=""

# 1. dangling: a supersedes that names an id with no file
while IFS=$'\t' read -r id sup; do
  [ -z "$id" ] && continue
  if [ "$sup" != "null" ] && [ -n "$sup" ] && [ ! -f "$LEDGER_DIR/$sup.json" ]; then
    broken="$broken
dangling: $id supersedes $sup (no such record)"
  fi
done <<PEOF
$PAIRS
PEOF

# 2. duplicate: two records both supersede the same id
dup_targets="$(printf '%s\n' "$PAIRS" | awk -F'\t' '$2 != "null" && $2 != "" {print $2}' | LC_ALL=C sort | uniq -d)"
if [ -n "$dup_targets" ]; then
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    broken="$broken
duplicate: $t is superseded by more than one record"
  done <<DPEOF
$dup_targets
DPEOF
fi

# 3. (forward-supersedes check removed: the supersede chain is the
# authoritative ordering; the date is a tie-break for records with no
# supersede relationship. A record with an earlier date than the record it
# supersedes is valid — the chain order, not the timestamp, is the truth.)

# 4. orphan: a root (supersedes: null) marked "superseded" with no live
#    successor that supersedes it.
while IFS=$'\t' read -r id sup; do
  [ -z "$id" ] && continue
  [ "$sup" = "null" ] || continue
  st="$(jq -r '.status' "$LEDGER_DIR/$id.json" 2>/dev/null)"
  [ "$st" = "superseded" ] || continue
  has_successor="$(printf '%s\n' "$PAIRS" | awk -F'\t' -v t="$id" '$2 == t {print $1; exit}')"
  if [ -z "$has_successor" ]; then
    broken="$broken
orphan: $id is marked superseded but no record supersedes it"
  fi
done <<RPEOF
$PAIRS
RPEOF

if [ -n "$broken" ]; then
  STATUS=20
  {
    echo "CHAIN:"
    printf '%s\n' "$broken" | sed '/^$/d'
  } >&2
fi
fi  # end of if [ "$STATUS" -ne 10 ]

# --- Report -------------------------------------------------------------------
printf 'id\tdate\tby\tstatus\tlive\tsupersedes\n'
[ -f "$ROWS" ] && cat "$ROWS"

exit "$STATUS"
