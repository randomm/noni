# noni — product document

Status: v0 positioning · 2026-10-22 · owner-approved epic map below
Evidence base: three verified research runs + a lead-run prototype; see
`docs/briefs/` pointers in §8 and the decision log at
`~/outputs/.plans/noni-backlog-competitors.md` (authoritative working record).

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
conventions (beads' claim discipline, tehas' answer-legitimacy parsing) or
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
  pi-rukas/tehas vocabulary. Integrations are clearly-marked adapters
  (`integrations/tehas/`, `integrations/github-issues/`). The core must be
  viable with neither adapter installed.
- **tehas is the primary integration, pi-rukas the reference driver** —
  overlap with tehas is allowed where the generic product needs it, and the
  adapters map onto tehas source mechanisms (q_render/q_answer legitimacy,
  cycle flock liveness, label-event authorization) rather than reinventing them.
- **A ping is a hint; the commit is the truth.** Any live transport
  (MCP-elicitation prompt, future A2A) is a notification cache over
  git-committed state, never the state itself. A2A: ignore now, dated re-check.

## 4. The steer, concretely

Two input modes, one record shape, per the verified prior art (AG2, LangGraph,
Claude AskUserQuestion, tehas all converge):

- **Multiple-choice**: agent asks 1–4 questions × 2–4 options (production-verified
  bounds), free-text escape hatch always offered. Answer must name the question
  it answers (id pairing). Never auto-answer for the operator (anti-fabrication).
- **Free chat**: agent distills the conversation into a candidate record;
  the operator confirms; the confirmation is committed.
- **Record shape** (ADR skeleton + tehas fields): `{id, date, asked_by, question,
  options[], answer, by, scope, status, supersedes}` under the repo's ledger
  path. `status` adopts one/many/stranger semantics with the git-attribution
  caveat: `by` is a commit author, forgeable locally — default posture is
  signed commits; stranger-detection is advisory until forge-verified pushes.

## 5. Claims — the prototype verdict

Two-clone experiments (2026-10-22, scratch tree `noni-claim-proto2`) showed:
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

## 7. Proposed state layout in an attached project (E1/E2 specs finalize)

```
<project>/noni/
  direction/   standing direction, release trains, Now-state ordering
  decisions/   steering ledger: one file per dated record
  sessions/    one committed file per session (registration + claims), one writer each
  census/      on-demand reports (NDJSON); git history is the metric source
```

Metrics are derived, never self-reported: the census reads git history and
these files. The tehas adapter additionally joins `analytics.db` runs to
noni artifacts by issue number for outcome questions ("do steered runs park
less, rework less, merge faster?").

## 8. Epic map (filed via the plan driver as the issue set)

- **E1 steering-ledger** — record format + both steer modes + anti-fabrication +
  attribution posture. Evidence: Run 3 T1/T3.
- **E2 sessions+claims** — register layout, claim protocol per §5, don't-touch
  signalling. Evidence: Run 3 T4 + the prototype.
- **E3 census** — arbiter checks (double-claim, stale session, provenance
  completeness), `report` mode NDJSON, heartbeat multi-store honesty.
- **E4 adapters** — `integrations/tehas/` (primary: q_render/q_answer mapping,
  cycle-lock reading, label-event authorization, analytics.db join) and
  `integrations/github-issues/` (generic). Core viable with neither.
- **E5 measurement/eval** — baseline capture, scenario eval on `to-bench`
  (two concurrent sessions, planted double-claim), optional noni arm on the
  existing pi-ab-bench harness (Harbor, SWE-bench Pro V2, pinned).

Evidence briefs (run 1: autonomous-agent landscape — adjacent context, demoted
class; run 2: backlog/direction competitors — adopt-nothing-wholesale verdict,
borrow beads' claim discipline and seeds' release-train vocabulary; run 3:
skill-first & coordination) live in the working tree at `outputs/` and are
summarized here so the repo stays self-contained. The epic issue set is filed
on this repo's GitHub issues via the pi-rukas plan driver.

## 9. First dogfood

noni on noni's own repo: E1–E5 are filed as GitHub issues (the work carrier),
noni's own `noni/` state will hold the direction layer (the direction), and
the plan/work drivers in this ecosystem are the first agent sessions to
register, claim and get censused.
