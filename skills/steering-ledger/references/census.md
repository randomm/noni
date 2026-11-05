# The census

`noni census` (`skills/census/scripts/census.py`, documented in
`skills/census/SKILL.md`) is the entry point that enforces the ledger invariants.
`scripts/census.sh`, the subject of this page, is the ledger shim (with its
`--sessions` dispatch to the sessions-claims twin): the read-only, jq-based twin
kept for callers that already run it. It is a
bash script, so it runs under `bash` or through its own executable bit and its
bash shebang — never under `python3`, which reads its braces as Python and dies
on a syntax error before any check runs. This is the one page that states that
rule for this shim; `SKILL.md` and the sessions shim's reference point here.
It never
writes; it reads `noni/decisions/*.json`, the git history, and reports an honest
exit code. It enforces the invariants that git and the files can prove. What
git cannot prove — that an answer was the operator's, not an agent's — the
census does not check and does not claim to (see
`references/modes.md`, Anti-fabrication).

## Usage

```
bash scripts/census.sh <state-root>/noni/decisions   the decisions census (E1)
bash scripts/census.sh --sessions <state-root>/noni/sessions  the sessions census (E2)
bash scripts/census.sh --help         the usage and exit-code table
```

Each line is one bash script, so `bash <path>` is the form that always runs:
it works whatever the file mode a checkout happened to land at. The direct form
(`scripts/census.sh <dir>`) is the same script where the executable bit is set.

The one argument each check takes is the state directory of the state root —
the directory `--repo` names for the writers — and neither check has a
current-directory default. Pass the absolute path of a clone's ledger to census
a tree other than the one you are in; run with no argument, either path is a
usage error (2) rather than a census of whatever `noni/` happened to sit next
to the caller.

## Exit codes

| code | meaning |
|---|---|
| `0` | clean — every record valid, chain intact |
| `2` | usage: no ledger directory was given (the state root is named by the caller, never by the cwd) |
| `3` | `jq` not found on the reading machine, or the schema program `scripts/census-schema.jq` is missing from beside the shim (`3:schema-program-missing`). Either way the census cannot apply a schema, so it exits honestly rather than reporting a false clean |
| `10` | a record is missing or malformed (schema violation), or the ledger is unusable: the directory does not exist, cannot be enumerated, a filename is not a plain `<name>.json` path segment, or the git tree is unreadable on a real repo |
| `12` | a record was edited after commit (the committed bytes differ from the working tree) |
| `20` | the supersede chain is broken (dangling, duplicate, orphan, cycle, or a chain resolving to zero or more than one live record) |

A `decisions/` directory that exists and can be read but holds no `*.json`
record is not a failure: the shim names it `(42:ledger-empty)` on stderr and
exits `0`, which is what the unified census's `ledger-empty` warn means (the
unified census promotes that warn to 42 under `--strict`, which this shim has no
flag for), so the two agree on a freshly attached tree (issue #97). A directory
it could not enumerate is still `10:empty-ledger` — a read that happened nowhere
is not an empty ledger.

**Ledger shim.** This table is the contract of `census.sh`, the ledger
shim. `noni census` is the entry point that enforces. The unified census
(`skills/census/scripts/census.py`, documented in
`skills/census/SKILL.md`) owns `ledger-empty` (42, warn; fail under `--strict`)
for the states where there is no decision record to arbitrate, carrying one of
the state words `absent`, `not a directory`, `symlink`, or `empty` (`noni/`
present with no `decisions/` directory, or a `decisions/` directory that holds
no `*.json` record — operator decision on issue #33, so a freshly attached
project censuses clean at exit 0). That class only adds rows: a record that is
bad JSON or violates the schema stays the `ledger-record` exit 10 in both
censuses, so the code-10 row of this table still covers the malformed and
unreadable records. The
unified census also owns three classes this shim does not have: `session-same-identity` (43),
`session-deleted` (44) and `hygiene` (50). Where the two disagree, the unified
census is the arbiter and this table describes the shim's own exit codes only.

The codes are distinct so a single failing census tells the operator which class
of invariant broke without re-reading the report. When several classes are
violated at once, the **lowest number wins** (`10 < 12 < 20`) and the
higher-numbered checks may not have been evaluated — the stderr message says
so.

## What each check reads

- **`0` (clean):** every `noni/decisions/*.json` parses, has all eight fields,
  the `questions` array has 1-4 entries each with 2-4 options (or exactly one
  option when the record carries the `single_option` marker), and the
  supersede chain resolves to exactly one live record per chain. The `by` field
  is only schema-checked (non-empty string): the report takes `by` from git
  when available, so a body value that disagrees with the commit is reported
  as the git author, not flagged. The optional `decided_by` and `on_behalf_of`
  are schema-checked the same way plus one line: each is a non-empty single-line
  string. Neither is reported — the report keeps its six columns and `by` keeps
  coming from git — and no identity is verified.
- **`2` (no ledger named):** the run was given no ledger directory. The census
  has no current-directory default, so it refuses rather than auditing the
  caller's cwd.
- **`3` (jq or the schema program missing):** `command -v jq` fails, or
  `scripts/census-schema.jq` — the sibling file the shim reads its record rules
  from — is not beside the script (`3:schema-program-missing` on stderr). The
  script cannot validate without either and exits honestly rather than reporting
  a false clean: a census that read the ledger and printed nothing would be
  claiming a verdict it never established. A packaging or install fault, not a
  ledger state.
- **`10` (schema violation):** a record is missing one of the eight fields, carries
  a key outside the closed set (the eight required plus the four optional — tested
  as a set, so a key nobody declared is refused whatever the record's key count
  is), a
  `questions` array is empty or has more than four entries, a question has fewer
  than two or more than four options (a question with one option is a violation
  unless the record carries the `single_option` marker), the marker is set without
  any question of the record holding exactly one option, or a field has the wrong
  type — including an empty, blank, non-string or multi-line `decided_by` or
  `on_behalf_of`, or a `single_option` that is not the JSON `true` literal. All
  of these are the same `ledger-record` class at exit 10 naming the field: no
  new check class and no new code was added for the new fields.
- **`12` (edited after commit):** the working-tree bytes of a committed record
  differ from the bytes in the last commit that touched that path. The census
  reads `git show <last commit>:<path>` and compares to the file on disk. A
  difference means someone edited the record instead of superseding it.
- **`20` (broken chain):** a `supersedes` names a record that does not exist
  (dangling), two records both supersede the same id (duplicate), a root
  (supersedes: null) is marked `superseded` with no live successor (orphan), a
  `supersedes` cycle exists, or a chain resolves to zero or more than one live
  record (a record is live when its `status` is not `superseded`).
  A record with an earlier date than the record it supersedes is **not** a
  violation — the supersede chain is the authoritative ordering; the date is
  a tie-break for records with no supersede relationship.

## Reading the report

The report goes to stdout: one tab-separated header line followed by one line
per record, in filename order (six columns):

```
id\tdate\tby\tstatus\tlive\tsupersedes
```

`date` is the record's `date` field; `by` is the git author of the commit
that last touched the record's path (falling back to the body's `by` when the
ledger is not in a git tree or the path has no history); `status` is the
record's `status` field; `live` is `yes` when that status is `decided` or
`open` and `no` when it is `superseded` — so within a valid chain the `live`
column marks the single record the chain resolves to, and a chain with zero
or more than one `yes` row is exit 20; `supersedes` is the `supersedes` field
(or `null`). When the chain walk fails (exit 20), a `CHAIN:` block is
printed to stderr naming the broken chains, e.g. one line per problem:
`dangling: <id> supersedes <id> (no such record)`, `duplicate: <id> is
superseded by more than one record`, `orphan: <id> is marked superseded but no
record supersedes it`, `cycle: record <id> is in a supersedes cycle`,
`zero-live: chain <id> resolves to no live record (every record in it is
superseded)`, `multi-live: chain <id> resolves to more than one live record
(expected exactly one)`. Exit `0` prints only the records and no `CHAIN`
block. A non-zero exit prints the offending record(s) and the reason on
stderr.
