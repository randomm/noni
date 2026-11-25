# noni hook for pi

A harness hook, not a tracker adapter: `noni.ts` wires `noni brief` into the
main agent of a pi session, so the agent cannot skip the direction layer. It
fills neither seam of the [adapter interface](../README.md) and is not the
thing that page's "Existing adapters" list is about.

It does two things, and nothing else. Every turn it adds one standing reminder
to the prompt guidelines: noni holds the project's direction and decisions, so
work in the order it gives, follow the recorded decisions, invent none, and
ask the operator and record the answer when something is undecided. At session
start and after each compaction it starts `noni brief` without blocking, and
hands the model what it printed on the next user turn. It registers no tool, no
command and no renderer.

## Which state root it reads

Resolved in this order, and the resolution lives in this file: noni's core
reads neither the environment nor the working directory for a state root.

1. `NONI_STATE_ROOT`, when it is set. A root named this way that holds no
   `noni/` directory takes the failure arm: the reminder still applies and the
   model is told the brief could not be read.
2. `<cwd>/.noni-state`, when that directory holds a `noni/` directory.
3. `<cwd>` itself, when it holds a `noni/` directory.
4. Otherwise nothing: no reminder and no brief.

## When it runs

pi loads a project-local extension only after the project is trusted. An
untrusted project skips it silently: no reminder and no brief. Trust the
project, or the hook does nothing.

The brief is fetched on every `session_start` (startup, resume, reload, new,
fork) and again after each `session_compact`, and injected on the next user
turn. The fetch does not block the session: the hook starts it without waiting.
A user turn that arrives while a fetch is still running waits for it, for at
most the 30 second timeout, and that first user turn is where the brief lands.
When a start follows another before the first fetch returned, the newest brief
wins: the hook numbers each start, lets only the newest one publish what it
fetched, and drops a fetch that finished late. What reaches the model is the
newest fetched brief, handed to the next user turn once: the slot is emptied as
it is handed over, and one fetch hands its brief over once. That is what
newest brief wins means in the code, and it is not a promise that no brief is
ever shown twice.

## Install

Copy or link the file into the project's own extension directory, where pi
loads project-local extensions after the project is trusted:

```
mkdir -p .pi/extensions
cp integrations/pi/noni.ts .pi/extensions/noni.ts
```

The prerequisite is that `noni` is on your PATH. The hook runs whichever `noni`
is first on PATH, so put the install you mean first. The quickstart's
[Install noni](../../docs/QUICKSTART.md#install-noni) section owns those
commands; this page does not reprint them. Where the binary is missing the hook
does not block the session: the model gets one short line naming the failure,
with any path in it replaced by the words "state root", and the reminder
applies as usual.

## Main agent only, and the limit of that rule

The brief is fetched and injected only in interactive terminal sessions: the
gate reads the session's run mode and fetches in `"tui"` alone, which is the
interactive terminal. A session in RPC, JSON or print mode gets the reminder
and never a copy of the brief, and so does a child agent that runs headless.
The gate is the run mode and not the UI flag, because pi reports that flag true
for RPC sessions as well as the terminal. Note that pi gives no reliable way to
tell a child session from the main one, because a child inherits the parent's
environment, so the terminal check is the approximation and not a guarantee.

## Verifying it

Start pi in the attached project and ask the model what noni's current order
is: it answers from the brief, which it was handed before its first reply. Run
`/compact` and ask again, and it answers from a fresh brief. Then set
`NONI_STATE_ROOT` to a directory holding no `noni/` directory and start again:
the model reports that the brief could not be read, and the session runs.

With no interactive session, as when pi runs headless, the hook fetches no
brief, so the check is the same command run by hand from the project root:
`noni brief --repo <root>`, where `<root>` is `NONI_STATE_ROOT` when it is set, else the `.noni-state` directory in the project, else the
project root. A state root kept elsewhere needs `NONI_STATE_ROOT` exported into
the pi process, or the hook reads a root you did not mean. The first line of
what it prints is the standing rules; a page that answers `Purpose: not readable`
or `the order is empty` means the root is wrong, not that the project has no
direction.
