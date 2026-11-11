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
3. **Census** — the read-only script that is also the arbiter: it flags
   protocol violations, and emits NDJSON
   metrics. It is the enforcement mechanism for every invariant (§6).

## 2. What noni is not

Not an agent, not a task tracker, not a CI system, not a coordination daemon,
not a database. No fleet manager, backlog UI or coordination framework is
adopted wholesale. The mechanisms noni takes from elsewhere are taken as
conventions — answer-legitimacy parsing — and the ones it
leaves at the door are the external truth stores, the daemons, and treating a
worktree's isolation as a claim.

## 3. Doctrine (owner-set; compensate for, never re-litigate)

- **Git + plain files are the only truth. No daemons, no databases.**
  Scripts exist only where atomicity and exit-code honesty demand them
  (census, flock where a host-local lock genuinely helps).
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
  writer enforces and the census checks), free-text escape hatch always
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

Noni keeps no claim state. A work driver of a team's own owns per-issue state,
worktree claims and a queue, and a second claim system written beside it by hand
disagrees with the first: the two drift, and only one of them is read by whatever
arbitrates. So the product states the position instead of shipping the mechanism:
claim state belongs to the driver that already keeps it, and noni's census asks no
claim question. Where a team wants a driver's claim state visible beside the
direction layer, the place for it is an adapter under `integrations/` that mirrors
the driver's own state (§8), not a register the team maintains by hand.

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
```

Both files under `direction/` are optional and each has exactly one writer:
`intent.py` writes `intent.md` and `order.py` writes `order.json`. Absence is a
state, not a fault, and the census adds no row for a file that was never written.

**Precedence** is the rule that makes the intent file answerable rather than
decorative. When a question comes up, the answer is the most recent applicable
record in `decisions/` (the end of its supersede chain); otherwise the four
sections of `intent.md` (`Purpose`, `Principles`, `Never`, `Ask first`); and if
neither settles it, the agent asks the operator and does not guess. An entry under
`Ask first` is never decided autonomously. Because standing direction is
traceable, the writer refuses to install an intent whose `--decision` the ledger
does not hold or has superseded, and the census reports an intent whose last
commit cites no live record (§7's `intent` class, 51).

The state root is a directory holding (or about to hold) that `noni/` tree, and
`--repo` is the only flag that names it. The mark is the `noni/` entry itself,
whatever it holds: a `noni/` that holds nothing yet is the state root of a
project that has not steered, and the census words its contents as their own
states (`absent`, `empty`, `not a directory`) rather than collapsing an empty
directory into a missing one. A directory with no `noni/` at all is the wrong
tree, and is refused as one (below).

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
`--ordering`, `--intent` and `--issue-state` overrides do not select
it either; they replace the path under it, and a leading `~` given by the caller is
expanded in those four values and nowhere else. Every shipped tool resolves
every other `noni/` path from `--repo` — never from the tool's own location, and
never from the current directory beyond `--repo`'s default.

A `--repo` that is missing, or is not a directory, stops the command with a
clear message and a non-zero code (the fail-closed rule, §6). The code is the
one that command already uses for a mistake in its own arguments: 2 for
`intent`, `order` and the unified census, 3 for `decide` (the same
refusal `decide` gives a `--repo` that is
not a git work tree). The codes are not interchangeable — each is that tool's
existing refusal, and a caller tells a wrong path from a fault of the tree by
which one it gets.

A `--repo` that *is* a directory but holds no `noni/` directory is the same
mistake wearing a different face, and it gets the same treatment on the same
code: `order` and `intent` refuse it with one line naming the path and saying it
is not a noni state root (no `noni/` directory), plus a fix line naming `--repo`.
`order` refuses `move`, `remove` and `confirm` that way; `add` is admitted
because its first entry is a sanctioned creator of `noni/direction`, and its
`--decision` is still resolved against the ledger. `intent set` is admitted for
the same reason (its first file creates `noni/direction/intent.md`). `decide`
refuses it too, and is admitted only when the caller passes `--init`: it is the
one writer that can bring `noni/` into being, and a run pointed at a project
checkout by mistake must not create direction content there. `--init` admits a tree
whose `noni/` is absent, or one that exists and holds no entry at all: the two states
a fresh state root arrives in. A `noni/` that holds an entry but neither the
`noni/decisions` ledger nor a `noni/direction` directory is residue of an aborted or
mis-targeted run, and `decide` refuses it with its own line at the same code, with or
without the flag: that tree is not one this run was asked to create, and mkdir'ing a
ledger beside the residue would commit direction into somebody else's repository. The
refusal names
the path as the caller spelled it, says the tree holds no `noni/` (or no ledger under
it), and sends the
caller to `--repo` or to `--init`; the `--init` sentence belongs to `decide` alone,
since no other command has the flag and each answers it as an unknown one. On a
tree that already holds a ledger or a `noni/direction` directory `--init`
changes nothing, and `--no-commit` no longer stands in for the flag. What makes
an admitted first `decide` auditable rather than silent is that it is a real,
reported commit: the run names the state root and the record it wrote, and leaves
the tree clean. The question is asked before the ledger is read, so a first record
never lands behind a half-checked tree. What none of them may do is
answer a *read* with "no decision record … is in the ledger" about a repository
that holds no ledger at all: that sentence is true of the ledger and useless as
an account of the wrong `--repo`, so the state root is checked before the reads.
The unified census changes no exit code for this state (a no-`noni/` tree stays
0, and 42 under `--strict` for a run that names `ledger-empty`) and instead
prints one note ahead of its rows saying that no `noni/` directory was found
under `--repo`; in `--json` mode the same sentence rides the summary row's
`not_evaluated` field. The note is not printed when any of `--ledger`,
`--ordering` or `--intent` replaces the path under the state root,
because then the state need not live under `--repo` at all.

The three writers of the direction layer (`order`, `intent`, `decide`) refuse the
same shape at their own paths: every directory from the state root down to the one
each reads or writes — `noni/`, and `noni/direction/` plus the `noni/decisions/`
ledger it cites for the two direction writers, or `noni/decisions/` for `decide` —
that is not a plain path this writer may read or write through (a symlink, a plain
file, a socket or a device, none of them read or written through), asked of `lstat`
before the first read, write or `mkdir`, with the offending path named and nothing
written; an absent directory is no refusal, because the first run creates it, and an
ancestor of the state root is never examined. The codes are the ones those tools
already use for a wrong path: 2 for `intent` and `order`, 3 for `decide`.

Results are recomputed on demand by the census (no `census/` directory). The
census is read-only: running it leaves `git status --porcelain` empty. Trends,
if ever wanted, are recomputed from git history.

The brief is the other read-only tool, and the only one that answers a person
rather than a check: `noni brief --repo DIR` prints four parts and exits — the
standing intent's `Purpose`, the head of the order, the five newest live decision
records with their questions, answers and reasons, and the census's own `summary:`
line, echoed and never recomposed. An order row names its subject and reads no
further: an entry that names an issue prints `#N` and nothing else. It writes nothing, so running it
leaves `git status --porcelain`
empty too, and
it prints the same bytes twice over one tree at one `--now`. It has no verdict of
its own about a file it cannot read: a part whose artifact is absent prints empty,
one whose artifact is there and unreadable prints `not readable`, and the census —
run a moment later in the same command — is what words the fault. Its exit codes
are the fail-closed pair: 0 whenever the page rendered, whatever it said about the
tree, and 2 for a command line it will not act on (no `--repo`, a `--repo` that is
not a directory, or an `--now` that is not a UTC instant), with the report on
stdout and the refusal on stderr so a caller can tell the two apart by stream.
The page is bounded: at most 20 lines of purpose, ten order entries, five recent
decisions and 200 lines in all, with the recent decisions the first thing the budget
withholds and the order entries next, so the head of the order outlasts them.

Metrics are derived, never self-reported: the census reads git history and
these files. An adapter may additionally join its own run analytics to noni
artifacts by issue number for outcome questions ("do steered runs park less,
rework less, merge faster?").

## 8. Adapters

Adapters live under `integrations/`, one clearly-marked directory per tool, and
the core is viable with none of them installed. The generic tracker adapter maps
noni's artifacts onto a public tracker: it renders a question, reads an answer,
and joins run analytics to noni artifacts by issue number. Its
coexistence position — which layers a team with a driver of their own still runs
— is documented in `docs/QUICKSTART.md` (*Using noni alongside a driver that
keeps its own claims*); no commitment is made here on any adapter's shape.
