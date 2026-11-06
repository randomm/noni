# noni — product document

## 1. What noni is

noni is an **attachable product-direction layer** for agentic coding work: a
skill-pack you add to any Git-based project so that the agents working in it —
and the operator steering them — share one durable record of **where the
project is going, in what order, why, and who said so**.

It owns four artifacts:

1. **Steering ledger** — dated, attributed, git-committed decision records.
   The operator steers either by answering bounded multiple-choice questions
   or by free chat that an agent distills into a candidate record the operator
   confirms. Every steering act survives the session that produced it and is
   replayable by any later session or clone.
2. **Backlog & ordering** — the Now-state: what the operator wants worked next,
   in what order, and a "why this order" provenance field per row.
   GitHub issues remain the work carrier; noni owns the direction layer above them.
3. **Session register + claims** — concurrent agent sessions on one project
   register themselves as one committed file each, and claim tasks by commit.
   Claims are signals, not locks (see §5); the census is the arbiter.
4. **Census** — the read-only script that is also the arbiter: it flags
   double-claims, stale sessions, protocol violations, and emits NDJSON
   metrics. It is the enforcement mechanism for every invariant (§6).

## 2. What noni is not

Not an agent, not a task tracker, not a CI system, not a coordination daemon,
not a database. No fleet manager, backlog UI or coordination framework is
adopted wholesale. The mechanisms noni takes from elsewhere are taken as
conventions — a claim discipline, answer-legitimacy parsing — and the ones it
leaves at the door are the external truth stores, the daemons, and treating a
worktree's isolation as a claim.

## 3. Doctrine (owner-set; compensate for, never re-litigate)

- **Git + plain files are the only truth. No daemons, no databases.**
  Scripts exist only where atomicity and exit-code honesty demand them
  (claim mutation, census, flock where a host-local lock genuinely helps).
- **SKILL.md is the unit of product.** Everything that can be expressed as a
  portable skill is; state lives outside the skill directory (no reload
  convention exists across runtimes). Packaging follows the Agent Skills
  spec: core skills stay inside the six spec frontmatter fields.
- **Two-tier purity.** Core skills carry neither project content nor
  vocabulary from any specific driver, tracker or project. Integrations are
  clearly-marked adapters (one directory per project, e.g.
  `integrations/github-issues/`). The core must be viable with no adapter
  installed.
- **Adapters mirror the tools a team already runs.** Where a generic product
  need overlaps with a mechanism a mature tracker or work driver already has
  (question-render / answer legitimacy parsing, cycle lock liveness,
  label-event authorization), the adapter under `integrations/` maps onto that
  mechanism rather than reinventing it.
- **A ping is a hint; the commit is the truth.** Any live transport
  (MCP-elicitation prompt, future A2A) is a notification cache over
  git-committed state, never the state itself. A2A: ignore now, dated re-check.

## 4. The steer, concretely

Two input modes, one record shape, on the bounds the question-answer loops in
this field have converged on:

- **Multiple-choice**: agent asks 1–4 questions × 2–4 options (the bounds the
  writer enforces and both censuses check), free-text escape hatch always
  offered. Answer must name the question
  it answers (id pairing). Never auto-answer for the operator (anti-fabrication).
- **Free chat**: agent distills the conversation into a candidate record;
  the operator confirms; the confirmation is committed.
- **Record shape** (an ADR skeleton plus the fields a steer needs): `{id, date, asked_by, question,
  options[], answer, by, scope, status, supersedes}` under the repo's ledger
  path. `status` adopts one/many/stranger semantics with the git-attribution
  caveat: `by` is a commit author, forgeable locally — default posture is
  signed commits; stranger-detection is advisory until forge-verified pushes.

## 5. Claims — why the census decides

The claim protocol follows from three properties of git: a rejected push works
as compare-and-swap; edits to one shared claim file conflict at merge, but
whether a conflict fires at all is a matter of file layout; and per-session
claim files, each holding a different path, land both claims without
conflicting. So the **census must detect
double-claims at read time**. Therefore: per-session files (single writer each),
claim-as-signal
committed to the repo, **census double-claim check as the deterministic
arbiter**, merge conflict as a bonus net. "No-steal" is an aspiration, not a
promise: git delays the second claimant, it does not lock them out.

## 6. Enforcement rule (product invariant)

**SKILL.md prose is convention, not enforcement.** Every noni invariant gets
either a script with an honest exit code or a census check that catches its
violation. Prose states the protocol; scripts and census hold the line.

## 7. State layout and the state root

All noni state of one project lives under one **state root**, in this layout:

```
<state root>/noni/
  direction/   intent.md: the standing intent; order.json: the ordered list of work
  decisions/   steering ledger: one file per dated record
  sessions/    one committed file per session (registration + claims), one writer
               each; optional, and absent until a session first registers
```

Both files under `direction/` are optional and each has exactly one writer:
`intent.py` writes `intent.md` and `order.py` writes `order.json`. The
`sessions/` directory is optional in the same way and has four writers
(`register`, `claim`, `close`, `release`): a team that does not run them has no
session register at all, which is a clean state and not a fault — see the
driver-coexistence position in `docs/QUICKSTART.md`. Absence is a state, not a
fault, and the census adds no row for a file that was never written.

**Precedence** is the rule that makes the intent file answerable rather than
decorative. When a question comes up, the answer is the most recent applicable
record in `decisions/` (the end of its supersede chain); otherwise the four
sections of `intent.md` (`Purpose`, `Principles`, `Never`, `Ask first`); and if
neither settles it, the agent asks the operator and does not guess. An item under
`Ask first` is never decided autonomously. Because standing direction is
traceable, the writer refuses to install an intent whose `--decision` the ledger
does not hold or has superseded, and the census reports an intent whose last
commit cites no live record (§7's `intent` class, 51).

The state root is a directory holding (or about to hold) that `noni/` tree, and
`--repo` is the only flag that names it:

- **Default: the attached project's own repository**, so the state is the tree
  at `<project>/noni/` and every tool run without `--repo` reads and writes
  there. Direction stays next to the code it steers, its history is the
  repository's history, and there is no second repository to clone.
- **Alternative: a separate private state repository** carrying the identical
  `noni/` layout, selected by passing its path as `--repo`. Choose it when the
  code repository is public and the direction should not be published with it,
  or when a team keeps the direction of several repositories in one private
  place. Same layout, same writers, same census: only the path changes. Such a
  repository holds the `noni/` layout and nothing else: it is a new, empty,
  private repository, not a folder of other work, because the census's hygiene
  class reads every tracked file of the tree `--repo` names.

Every noni writer commits straight to the branch it finds checked out in the
`--repo` tree, so the in-project route asks a project for direct commits to its
own branch: on a branch-protected or PR-only project, use Route B, whose commits
land on the state repository's own branch.

There is no third mechanism that *selects* the state root: no environment
variable and no config file names it. The unified census's `--ledger`,
`--sessions`, `--ordering`, `--intent` and `--issue-state` overrides do not select
it either; they replace the path under it, and a leading `~` given by the caller is
expanded in those five values and nowhere else — the sessions census takes one
plain path argument and does no expansion of it. Every shipped tool resolves
every other `noni/` path from `--repo` — never from the tool's own location, and
never from the current directory beyond `--repo`'s default.

A `--repo` that is missing, or is not a directory, stops the command with a
clear message and a non-zero code (the fail-closed rule, §6). The code is the
one that command already uses for a mistake in its own arguments: 2 for
`intent`, `order`, `register` and the unified census, 4 for `claim`, `close` and
`release`, 3 for `decide` (the same refusal `decide` gives a `--repo` that is
not a git work tree). The codes are not interchangeable — each is that tool's
existing refusal, and a caller tells a wrong path from a fault of the tree by
which one it gets.

The four session writers (`register`, `claim`, `close`, `release`) refuse two
further states the same way. A `--repo` that is itself a symlink: `git` works on
the resolved path of the tree it is pointed at, so a linked state root is where
the writer's own path arithmetic and git's stop agreeing, and the marker and the
audit trail would be kept against a path nobody named. The run stops with a
message naming the real path of the state root, on the same code that tool
already uses for a wrong path: 2 for `register`, 4 for `claim`, `close` and
`release`. A project directory reached *through* a link is not this state: only
a `--repo` that is itself a link is refused.

The same four writers refuse a session file that is a symlink, and any directory
from the state root down to it — `noni/sessions/` and the `noni/` that holds it —
that is not a plain path this writer may follow (a link, a plain file, a socket or
a device, none of them read or written through).
`is_file()` follows a link, so a symlinked session file reads as present and the
writer's atomic replace lands on the link's target: the link is replaced by a
regular file holding bytes the run composed, and a symlinked `noni/sessions/` — or
`noni/` itself — sends the file outside the tree altogether. Every one of those
paths is refused before any read, write or `mkdir`, with the offending path named,
and a refusal creates no directory, writes no file and leaves the marker and HEAD
where they were. A dangling link gets this refusal and not the "no such session
file" exit, because the check is `lstat`, not `is_file()`: `lstat` reads only the
last component, which is why the guard asks the same question of every directory
above the file rather than of the two it happens to write into. A project reached
through a linked ancestor is not this state either: only the session file and the
paths beneath the state root are examined, never an ancestor of the state root.

The check is `lstat`, never `is_file()`: a dangling link is a refusal, not a
missing session. The symlinked session file, the symlinked `noni/sessions/` and the
symlinked `noni/` are answered with the same codes as the state-root refusal above:
2 for `register`, 4 for `claim`, `close` and `release`.

Results are recomputed on demand by the census (no `census/` directory). The
census is read-only: running it leaves `git status --porcelain` empty. Trends,
if ever wanted, are recomputed from git history.

Metrics are derived, never self-reported: the census reads git history and
these files. An adapter may additionally join its own run analytics to noni
artifacts by issue number for outcome questions ("do steered runs park less,
rework less, merge faster?").

## 8. Adapters

Adapters live under `integrations/`, one clearly-marked directory per tool, and
the core is viable with none of them installed. The generic tracker adapter maps
noni's artifacts onto a public tracker: it renders a question, reads an answer,
and joins run analytics to noni artifacts by issue number. The follow-up is a
driver-claims adapter: one that mirrors a work driver's own claim state into the
session register instead of the team keeping a second register by hand. Its
coexistence position — which layers a team with a driver of their own still runs
— is documented in `docs/QUICKSTART.md` (*Using noni alongside a driver that
keeps its own claims*); no commitment is made here on the adapter's shape.
