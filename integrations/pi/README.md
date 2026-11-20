# noni hook for pi

A harness hook, not a tracker adapter: `noni.ts` wires `noni brief` into the
main agent of a pi session, so the agent cannot skip the direction layer. It
fills neither seam of the [adapter interface](../README.md) and is not the
thing that page's "Existing adapters" list is about.

It does two things, and nothing else. Every turn it adds one standing reminder
to the prompt guidelines: noni holds the project's direction and decisions, so
work in the order it gives, follow the recorded decisions, invent none, and
ask the operator and record the answer when something is undecided. Twice per
session, at the start and after each compaction, it runs `noni brief` and hands
the model what it printed. It registers no tool, no command and no renderer.

## Which state root it reads

Resolved in this order, and the resolution lives in this file: noni's core
reads neither the environment nor the working directory for a state root.

1. `NONI_STATE_ROOT`, when it is set. A root named this way that holds no
   `noni/` directory takes the failure arm: the reminder still applies and the
   model is told the brief could not be read.
2. `<cwd>/.noni-state`, when that directory holds a `noni/` directory.
3. `<cwd>` itself, when it holds a `noni/` directory.
4. Otherwise nothing: no reminder and no brief.

## Install

Copy or link the file into the project's own extension directory, where pi
loads project-local extensions after the project is trusted:

```
mkdir -p .pi/extensions
cp integrations/pi/noni.ts .pi/extensions/noni.ts
```

The prerequisite is that `noni` is on your PATH. The quickstart's
[Install noni](../../docs/QUICKSTART.md#install-noni) section owns those
commands; this page does not reprint them. Where the binary is missing the hook
does not block the session: the model gets one short line naming the failure,
with any path in it replaced by the words "state root", and the reminder
applies as usual.

## Main agent only, and the limit of that rule

The brief is fetched and injected only in an interactive session, so a child
agent that runs headless gets the reminder and never a copy of the brief. pi
gives no reliable way to tell a child session from the main one, because a
child inherits the parent's environment, so the interactive check is the
approximation and not a guarantee.

## Verifying it

Start pi in the attached project and ask the model what noni's current order
is: it answers from the brief, which it was handed before its first reply. Run
`/compact` and ask again, and it answers from a fresh brief. Then set
`NONI_STATE_ROOT` to a directory holding no `noni/` directory and start again:
the model reports that the brief could not be read, and the session runs.
