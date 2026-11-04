# The decision-record schema, as one jq program. census.sh sources nothing but
# reads this file with `jq -r ... <file>`, and census.py's ledger-record pass is
# the Python twin of the same rules (both wordings are pinned by the golden
# fixtures under tests/fixtures/).
#
# Emits "ok" for a record that carries the eight top-level required fields (plus
# any of the four optional ones: source, decided_by, on_behalf_of, single_option)
# and satisfies every rule below; otherwise it emits the fixed violation message.
# The closed set is a set, not a count: a key outside those twelve names is refused
# at any total, which is the difference between this program and the key-count rule
# it replaced. tests/test_ledger_closed_key_set.py asserts this file's key literal
# against the Python schema's own field sets.
# Raw record bytes are never echoed into the diagnostic: jq stderr is discarded by
# the caller, and an unparseable record is told apart from a schema failure by the
# follow-up `jq empty` probe.

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
# The closed set is the eight required fields plus the four optional
# ones (source, decided_by, on_behalf_of, single_option), tested as a SET and
# not as a key count: every key of the record must sit in the literal below,
# so a junk key is refused whatever the record's total count is. A count was
# the old rule and it was wrong twice over: it admitted a junk key beside a
# real optional one (nine keys: source plus one name nobody declared), and it
# accepted 10-, 11- and 12-key records carrying any names at all. origin/main
# answered exit 10 on every one of those shapes; the set test is what keeps
# that answer. The tests parse the literal out of this file and compare it to
# REQUIRED_LEDGER_FIELDS + OPTIONAL_LEDGER_FIELDS in noni/ledger_schema.py.
# The literal stays inside this shell string, so it carries no $, backtick or
# backslash: just the twelve names and the jq operators.
def closed8: (((keys_unsorted // [])
  - ["id","date","asked_by","questions","by","scope","status","supersedes",
     "source","decided_by","on_behalf_of","single_option"]
  | length) == 0);
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
# The 2-4 option bound relaxes to 1-4 for exactly one kind of record: the one
# carrying the marker the writer writes, single_option as the JSON true literal,
# so a one-option question without the marker stays a schema violation. The
# record is bound to $r first: inside all() the input is the question, so a
# record-level has() there reads the question for a key the record holds and
# silently answers false for every record.
def questions_ok:
  (. as $r
   | ((.questions | type) == "array")
   and ((.questions | length) >= 1) and ((.questions | length) <= 4)
   and (all(.questions[];
     has("id") and has("text") and has("options")
     and ((.options | type) == "array")
     and ((if ($r | has("single_option")) and ($r.single_option == true) then 1 else 2 end) <= (.options | length))
     and ((.options | length) <= 4)
     and (all(.options[]; type == "string"))
     and (if has("answer")
          then (.answer == null or (.answer | type) == "string")
          else true end)
     and ((if has("answer") then 4 else 3 end) == (keys_unsorted | length))
   )));
def status_ok: (.status | IN("decided","open","superseded"));
def id_ok: ((.id | type) == "string") and ((.id | length) > 0);
def by_ok: ((.by | type) == "string") and ((.by | length) > 0);
def asked_by_ok: ((.asked_by | type) == "string") and ((.asked_by | length) > 0);
def scope_ok: ((.scope | type) == "string") and ((.scope | length) > 0);
def sup_type_ok: ((.supersedes == null) or
  ((.supersedes | type) == "string") and ((.supersedes | length) > 0));
# The two attribution names, absent or a non-empty single line, and never only
# whitespace. The line rule is what asked_by does not carry: json escapes the
# short control forms inside a string but writes U+0085, U+2028 and U+2029 raw,
# so a value can be one JSON string and still not one line. The class below is
# exactly LINE_BREAKS in noni/ledger_schema.py -- the four controls json
# escapes, the three it writes raw, and the three separators U+001C-U+001E that
# json escapes but str.splitlines (the documented basis) breaks a line on --
# matched with one test: jq-1.8 rejects the all form over a bound value inside
# a def, and test is the one spelling that stays a single expression. The
# escapes are json escapes, so the shell never sees them.
# The blank rule is the writer's, mirrored: a name that is only whitespace
# names nobody, so the flag refuses it and a hand-edited record is refused the
# same way here. The blank class is the whitespace str.strip() removes, minus
# the line breaks (a value carrying one is already refused by the class above)
# and minus U+0085, U+2028 and U+2029, which are not blank to str.strip().
# The census checks these shapes and nothing more: it never verifies an identity,
# and it does not enforce the pairing: a record naming the party a decision was
# made for without naming who made it is the writer refusal, not a census one.
# The two tests are joined by `and` so a non-string never reaches either one:
# `test` faults on a null or a number, and jq's stderr is discarded by the
# caller, so a type violation has to answer as the fixed message rather than as
# the absence of one.
def line_free: ((type == "string")
  and ((length) > 0)
  and ((test("^[ \\t\\u000b\\u000c]*$") | not))
  and ((test("[\n\r\u000b\u000c\u001c\u001d\u001e\u0085\u2028\u2029]") | not)));
def decided_by_ok: ((has("decided_by") | not) or (.decided_by | line_free));
def on_behalf_of_ok: ((has("on_behalf_of") | not) or (.on_behalf_of | line_free));
# The single-option marker is written as the JSON true literal and nothing
# else: a one-option question is malformed unless it reads true, so false, a
# string or a number is a malformed marker rather than a relaxed bound.
def single_option_ok: ((has("single_option") | not) or (.single_option == true));
# The marker is per record and the bound it relaxes is per question, but the
# marker has to be earned: with the marker present at least one question of the
# record must hold exactly one option, or the record claims a one-option question
# it does not show. census.py's validate_questions mirrors this on the same two
# facts. The // [] and the type test keep a null or a non-array questions value
# from faulting here: that shape is questions_ok's message to give, and jq's
# stderr is discarded by the caller, so a rule that faults would answer as the
# absence of a diagnostic rather than as a diagnostic.
def marker_earned: ((has("single_option") | not) or (.single_option != true)
  or ((.questions // []) as $qs
      | ((($qs | type) == "array") and (($qs | length) > 0)
         and ((([ $qs[]? | select((.options | type) == "array"
                                  and (.options | length) == 1) ] | length)) > 0))));
# The empty string is rejected: it is neither "no supersede" (null) nor a
# valid record id, and accepting it would make the chain walk ambiguous.
# (sup_type_ok already covers this via length > 0; stated here so the
# intent is explicit.)
if has8 and closed8 and is_iso and cal_ok and questions_ok and status_ok
   and id_ok and by_ok and asked_by_ok and scope_ok and sup_type_ok and source_ok
   and decided_by_ok and on_behalf_of_ok and single_option_ok and marker_earned
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
    (if closed8 | not then "unknown field(s): " + (((keys_unsorted // []) - ["id","date","asked_by","questions","by","scope","status","supersedes","source","decided_by","on_behalf_of","single_option"]) | join(",")) else "" end),
    (if source_ok | not then "source must be null or an object with issue_number and comment_id" else "" end),
    (if is_iso | not then "date is not a valid UTC ISO-8601 string" else "" end),
    (if cal_ok | not then "date components out of range (month 1-12, day 1-31, hour 0-23, minute 0-59, second 0-60)" else "" end),
    (if questions_ok | not then "questions array or option bounds violated" else "" end),
    (if status_ok | not then "status not one of decided|open|superseded" else "" end),
    (if id_ok | not then "id missing or not a non-empty string" else "" end),
    (if by_ok | not then "by missing or not a non-empty string" else "" end),
    (if asked_by_ok | not then "asked_by missing or not a non-empty string" else "" end),
    (if scope_ok | not then "scope missing or not a non-empty string" else "" end),
    (if sup_type_ok | not then "supersedes must be null or a non-empty string" else "" end),
    (if decided_by_ok | not then "decided_by must be a non-empty single-line string" else "" end),
    (if on_behalf_of_ok | not then "on_behalf_of must be a non-empty single-line string" else "" end),
    (if single_option_ok | not then "single_option must be the JSON true literal when present" else "" end),
    (if marker_earned | not then "single_option is set but no question has exactly one option" else "" end)
  ] | map(select(. != "")) | join("; ")
end
