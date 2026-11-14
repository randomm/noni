---
name: noni
description: The start-here page for a fresh agent in an attached project: one read-only screen, `noni brief`, that shows the standing purpose, the ordered backlog and the operator's recorded decisions, and the routes to every act that follows. Run it before reading state files by hand or asking the operator what they already answered. Do NOT use for writing the order or the intent (that is the direction skill), for recording a decision (steering-ledger), or for reading the state's health (the census skill is the arbiter).
---

# noni

**Mission:** one page, read once, that leaves a fresh agent able to carry on. An agent
has limited context and no memory of the last session, so the fastest path to useful
work is to read what the operator already wrote down before asking or proposing
anything. noni holds those answers in committed files under the project's own `noni/`
directory, and this page is the route to them.

Read the screen, then act on it. Do not re-argue a settled question: a recorded
decision is the current word, and the census, not your judgement, is the arbiter of
whether the state is in order.

## The first action (run the screen)

At session start, run the brief over the state root:

```console
noni brief --repo DIR
```

It is read-only: it writes no file, stages no commit and runs no tracker call, so
nothing about the tree changes and no answer is committed by looking. It prints four
parts and exits.

The state root is the project's own repository by default, or a separate directory
carrying the same `noni/` layout when a team keeps its direction in a private state
repository. `--repo` names it on every run and has no default: nothing reads the
current directory or the environment for it. It is the directory that holds (or would
hold) `noni/direction/` and `noni/decisions/`.

## How to read the screen's four parts

Two lines need a word before you read them as faults. In the recent decisions block
`dropped: N line(s)` usually means the block showed its five newest records and left
the rest: the page's 200-line budget spends the recent decisions first, so a day with
more than five decisions prints five and counts the rest. A record is a plain JSON
file at `<state root>/noni/decisions/<record id>.json`, and reading it is safe: it
shows the fields this page's one line of them leaves out.
`ordering-closed not checked` on the verdict line says the screen does not know whether
the ordered issues are open, because no issue state reached the census it runs: treat the
order as possibly stale until you run the census with `--issue-state`, which the census
skill explains.

- **Part one, Purpose.** The standing intent's own prose, clipped to a page: what the
  project is for and the principles it will not trade. The direction skill is the
  writer of that file; here it is read and shown.
- **Part two, Order.** The top 10 open ordered entries, numbered 1 to 10, in the
  operator's own order, each as `N. #issue (decision id)` plus the reason for that
  position after a mark. The head is the default answer to "what now". The screen
  reads no tracker, so the record id is what says what the entry is for.
- **Part three, Recent decisions.** The five most recent live records, newest first,
  each as its question, its answer, and the reason when the operator gave one. A record
  that asked one question on purpose prints its statement and reason instead. Superseded
  records never appear here. A record with no `--date` carries the instant of its run, so the last
  written prints first; a `--date` run stamps midnight; equal instants fall back to the record id.
- **Part four, Summary.** The totals, echoed verbatim from `noni census --json`: the
  count of live records beside the count of open ordered entries, and nothing else the
  brief decided on its own.

An empty part is a state, not a fault: a project that wrote no intent, ordered nothing
and steered nothing prints four headers and a verdict. A part it could not read says no
more, because the census it runs a moment later is the tool that words a fault with a
name and a fix. Read that verdict line as the state of the tree.

## Carrying on

Three moves follow from the screen, each owned by another page, which this page routes
and restates no flags of.

1. **Take the first entry of the `top 10` list.** That is the issue the operator put
   first. The order is a signal, not a lock: nothing in the core reads it to decide
   whether work may start.
2. **When the operator decides something, record it.** An answer given in chat, in
   a comment or in passing is a hint; the committed record is the truth. Record it in
   their words, never your own summary of them, and never answer a question on their
   behalf -- a declined or cancelled question stays open and records nothing.
   [`skills/steering-ledger/SKILL.md`](../steering-ledger/SKILL.md) owns the record,
   the two steer modes and the writer.
3. **When work lands or an entry is done, update the order.** Remove it or move it,
   and re-confirm what the operator last confirmed.
   [`skills/direction/SKILL.md`](../direction/SKILL.md) owns the ordered list, the
   standing intent, and the two writers that produce them.

## Settled questions

Do not re-open a recorded decision. Read the `recent decisions` block before you
propose anything, and if a record speaks to your question, its answer stands even
where the intent file says otherwise: an operator who overrode a principle made a
dated record of it.

To change one, supersede it: a new dated record naming the record it replaces, through
the steering-ledger writer, and only on the operator's word. Never edit a committed
record, and never write one to make an inconvenient answer go away: the census's chain
class reports what a hand-edited record looks like, and the append-only rule is the
only thing that makes a record worth reading.

## Where the rest lives

noni holds the direction layer: the standing intent, the ordered list, and the decision
records. It is not a knowledge base, and learned facts about a codebase do not belong
here: they live in a separate memory tool, in that tool's own store. What noni keeps is
what the operator decided, as committed files, so a later session, a fresh clone or a
CI run reads the same truth.

| To | Read |
|---|---|
| run the census and read its classes and exit codes | [`skills/census/SKILL.md`](../census/SKILL.md) |
| the order or the intent, and how to write them | [`skills/direction/SKILL.md`](../direction/SKILL.md) |
| a decision record, its fields and the supersede chain | [`skills/steering-ledger/SKILL.md`](../steering-ledger/SKILL.md) |
| install noni, or the commands in this page verbatim | [docs/QUICKSTART.md](../../docs/QUICKSTART.md) |

The screen prints a truncated page, not the files: when a citation on it points at a
record you are about to act on, read that record itself (the JSON path above) before
you quote it. This page is the map, not the reference:
[docs/PRODUCT.md](../../docs/PRODUCT.md) states the state layout and the exit codes.
