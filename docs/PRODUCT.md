# noni — product document

Status: v0 positioning · 2026-10-22 · owner-approved epic map below
Evidence base: three verified research runs + a lead-run prototype; see
§8 for the brief summaries and the local working-tree decision log
(authoritative working record, held outside the repo).

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
2. **Backlog & ordering** — the Now-state: what is in the next release train,
   what order it ships in, and a "why this order" provenance field per row.
   GitHub issues remain the work carrier; noni owns the direction layer above them.
3. **Session register + claims** — concurrent agent sessions on one project
   register themselves as one committed file each, and claim tasks by commit.
   Claims are signals, not locks (see §5); the census is the arbiter.
4. **Census** — the read-only script that is also the arbiter: it flags
   double-claims, stale sessions, protocol violations, and emits NDJSON
   metrics. It is the enforcement mechanism for every invariant (§6).

## 2. What noni is not

Not an agent, not a task tracker, not a CI system, not a coordination daemon,
not a database. No fleet manager, backlog UI or framework from the surveyed
class is adopted wholesale; the surveyed mechanisms are either borrowed as
conventions (a surveyed project's claim discipline, the primary integration's
answer-legitimacy parsing) or
left at the door (Dolt/Postgres truth stores, daemons, worktree-isolation-as-claiming).

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
- **The primary integration is a specific driver/tracker ecosystem, and a
  reference driver is the integration model** —
  overlap with the primary integration is allowed where the generic product
  needs it, and the adapters map onto its source mechanisms (question-render /
  answer legitimacy parsing, cycle lock liveness, label-event authorization)
  rather than reinventing them.
- **A ping is a hint; the commit is the truth.** Any live transport
  (MCP-elicitation prompt, future A2A) is a notification cache over
  git-committed state, never the state itself. A2A: ignore now, dated re-check.

## 4. The steer, concretely

Two input modes, one record shape, per the verified prior art (AG2, LangGraph,
Claude AskUserQuestion, the primary integration all converge):

- **Multiple-choice**: agent asks 1–4 questions × 2–4 options (production-verified
  bounds), free-text escape hatch always offered. Answer must name the question
  it answers (id pairing). Never auto-answer for the operator (anti-fabrication).
- **Free chat**: agent distills the conversation into a candidate record;
  the operator confirms; the confirmation is committed.
- **Record shape** (ADR skeleton + the primary integration's fields): `{id, date, asked_by, question,
  options[], answer, by, scope, status, supersedes}` under the repo's ledger
  path. `status` adopts one/many/stranger semantics with the git-attribution
  caveat: `by` is a commit author, forgeable locally — default posture is
  signed commits; stranger-detection is advisory until forge-verified pushes.

## 5. Claims — the prototype verdict

Two-clone experiments (2026-10-22, scratch tree kept outside the repo) showed:
push-rejection works as compare-and-swap; shared-file claim edits conflict at
merge but conflict-firing is file-layout luck; per-session claim files always
auto-merge, so both claims land and the **census must detect double-claims at
read time**. Therefore: per-session files (single writer each), claim-as-signal
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
  direction/   standing direction, release trains, Now-state ordering
  decisions/   steering ledger: one file per dated record
  sessions/    one committed file per session (registration + claims), one writer each
```

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
  place. Same layout, same writers, same census: only the path changes.

There is no third mechanism that *selects* the state root: no environment
variable and no config file names it. The unified census's `--ledger`,
`--sessions`, `--ordering` and `--issue-state` overrides do not select it
either; they replace the path under it, and a leading `~` given by the caller is
expanded in those four values and nowhere else — the sessions census takes one
plain path argument and does no expansion of it. Every shipped tool resolves
every other `noni/` path from `--repo` — never from the tool's own location, and
never from the current directory beyond `--repo`'s default.

A `--repo` that is missing, or is not a directory, stops the command with a
clear message and a non-zero code (the fail-closed rule, §6). The code is the
one that command already uses for a mistake in its own arguments: 2 for
`order`, `register` and the unified census, 4 for `claim`, `close` and
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
that is not a directory at all (a link, a plain file, a socket or a device).
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
symlinked `noni/` are answered with the code each tool already uses for a wrong
path: 2 for `register`, 4 for `claim`, `close` and `release`.

Results are recomputed on demand by the census (no `census/` directory). The
census is read-only: running it leaves `git status --porcelain` empty. Trends,
if ever wanted, are recomputed from git history (E5).

Metrics are derived, never self-reported: the census reads git history and
these files. The primary integration's adapter additionally joins its local
run analytics to noni artifacts by issue number for outcome questions ("do
steered runs park less, rework less, merge faster?").

## 8. Epic map (filed via a plan driver as the issue set)

- **E1 steering-ledger** (#1) — record format + both steer modes + anti-fabrication +
  attribution posture. Evidence: Run 3 T1/T3.
- **E2 sessions+claims** (#2) — register layout, claim protocol per §5, don't-touch
  signalling. Evidence: Run 3 T4 + the prototype.
- **E3 census** (#3) — arbiter checks (double-claim, stale session, provenance
  completeness), `report` mode NDJSON, heartbeat multi-store honesty.
- **E4 adapters** (#4) — the primary integration adapter (question-render /
  answer mapping, cycle-lock reading, label-event authorization, run-analytics
  join) and `integrations/github-issues/` (generic). Core viable with neither.
- **E5 measurement/eval** (#5) — baseline capture, scenario eval on an
  existing benchmark harness (two concurrent sessions, planted double-claim),
  optional noni arm on the harness's pinned suite.

Evidence briefs (run 1: autonomous-agent landscape — adjacent context, demoted
class; run 2: backlog/direction competitors — adopt-nothing-wholesale verdict,
borrow a surveyed project's claim discipline and another's release-train
vocabulary; run 3: skill-first & coordination) live in a local working tree
held outside the repo and are summarized here so the repo stays self-
contained. The epic issue set is filed as issues #1–#5 on this repo via the
plan driver (label `epic`).

## 9. First dogfood

noni on noni's own project: E1–E5 are filed as GitHub issues (the work carrier),
noni's own `noni/` state lives in a private state repository that holds the
direction layer (the direction), and the plan/work driver sessions are the
first agent sessions to register, claim and get censused. This public
repository holds none of that state: it documents the layout (§7) and ships
the skills, the writers and the census. Run its tools with `--repo` naming the
state repository, and this checkout is never the state root.
