# The census

`scripts/census.sh` is the read-only, jq-based arbiter for the ledger. It is a
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
| `3` | `jq` not found on the reading machine (missing dependency) |
| `10` | a record is missing or malformed (schema violation), or the ledger is unusable: the directory does not exist, contains no `*.json` records, a filename is not a plain `<name>.json` path segment, or the git tree is unreadable on a real repo |
| `12` | a record was edited after commit (the committed bytes differ from the working tree) |
| `20` | the supersede chain is broken (dangling, duplicate, orphan, cycle, or a chain resolving to zero or more than one live record) |

**Legacy shim.** This table is the contract of `census.sh`, the per-epic entry
point. The unified census (`skills/census/scripts/census.py`, documented in
`skills/census/SKILL.md`) added `ledger-empty` (42, warn; fail under `--strict`)
for the states where there is no decision record to arbitrate, carrying one of
the state words `absent`, `not a directory`, `symlink`, or `empty` (`noni/`
present with no `decisions/` directory, or a `decisions/` directory that holds
no `*.json` record — operator decision on issue #33, so a freshly attached
project censuses clean at exit 0). That class only adds rows: a record that is
bad JSON or violates the schema stays the `ledger-record` exit 10 in both
censuses, so the code-10 row of this table still covers the malformed and
unreadable records. The shim keeps its own exit 10 for an empty ledger
directory (`10:empty-ledger`), where the unified census reports the warn. The
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
  the `questions` array has 1-4 entries each with 2-4 options, and the
  supersede chain resolves to exactly one live record per chain. The `by` field
  is only schema-checked (non-empty string): the report takes `by` from git
  when available, so a body value that disagrees with the commit is reported
  as the git author, not flagged.
- **`2` (no ledger named):** the run was given no ledger directory. The census
  has no current-directory default, so it refuses rather than auditing the
  caller's cwd.
- **`3` (jq missing):** `command -v jq` fails. The script cannot validate
  without jq and exits honestly rather than reporting a false clean.
- **`10` (schema violation):** a record is missing one of the eight fields, a
  `questions` array is empty or has more than four entries, a question has fewer
  than two or more than four options, or a field has the wrong type.
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
