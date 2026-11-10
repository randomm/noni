# Agent onboarding

Two pages tell a newcomer how to run noni: the README's try-it block records one
decision and reads the census in five minutes, and [docs/QUICKSTART.md](QUICKSTART.md)
covers installing it and the two state-root routes. This page is the third: it tells
a team how to make noni's skills available to the agents working in their repository,
and what one of those agents does at the start of a session, while it works, and at
the end.

Nothing here is a command. Each step names the skill that owns it and links its
`SKILL.md`; the flags, the exit codes and the worked examples live there and in the
quickstart, and this page deliberately restates none of them, so there is one place
to correct when a writer changes.

## Making the skills available to your agents

noni ships four core skills, one directory each, and each one's entry point is
its `SKILL.md`. All four are named below, each by the path a loader reads.

| skill | its page | what it owns |
|---|---|---|
| noni | [`skills/noni/SKILL.md`](../skills/noni/SKILL.md) | the start-here read an agent runs first, and the route from it to the pages below |
| steering-ledger | [`skills/steering-ledger/SKILL.md`](../skills/steering-ledger/SKILL.md) | the dated decision records under `noni/decisions/` |
| direction | [`skills/direction/SKILL.md`](../skills/direction/SKILL.md) | the standing intent and the ordered list under `noni/direction/` |
| census | [`skills/census/SKILL.md`](../skills/census/SKILL.md) | the read-only arbiter that reads all of the above |

The mechanism is the plain one: put those four directories where your agent runtime
loads skills from, by copying or linking them from the noni clone into your own
skills directory, and have your agents read the `SKILL.md` in each. The Agent Skills
frontmatter is what a loader reads, and nothing noni does depends on the copy being
the clone's own location: the writers resolve every path from `--repo`, never from
where the skill sits.

That is the whole instruction. **No runtime-specific installer ships here:** nothing
in this repository detects a runtime, writes a runtime's config file or installs a
skill for you, and no page here names the runtimes a team might use. Where your
loader expects a layout other than `skills/<name>/SKILL.md`, the copy is yours to
shape; the four `SKILL.md` paths above are the product surface it has to preserve.

## The per-session protocol

One agent session in an attached project follows three steps. Each row names the
skill that owns the step, and the link is where the how lives. Every team takes
all three. The start-here page is what the agent reads before any of them: it is
the read that tells the agent what the three steps are for.

| when | step | owning skill |
|---|---|---|
| at start | read the start-here page, and the screen it tells you to run | [`skills/noni/SKILL.md`](../skills/noni/SKILL.md) |
| at start | read the standing intent first, when the project has written one | [`skills/direction/SKILL.md`](../skills/direction/SKILL.md) |
| at start | read the current order, so you work on what the operator put first | [`skills/direction/SKILL.md`](../skills/direction/SKILL.md) |
| during work | record a decision through the steering-ledger writer when the operator steers you | [`skills/steering-ledger/SKILL.md`](../skills/steering-ledger/SKILL.md) |

One of those steps needs a word about what it is for, because an agent that skips
it is the failure mode the census exists to catch:

- **Record the steer, do not infer it.** When the operator answers a question or
  corrects your direction, that answer is a ledger record run through the writer, not
  a note in your own session. An unrecorded steer dies with the session and the next
  one reopens the same question.

The protocol is not enforced by the writers, which only refuse what they refuse. Run
the census at the end of a session, or in CI, to have it read what the session left
behind: [`skills/census/SKILL.md`](../skills/census/SKILL.md) owns its exit codes and
what each row means, and the quickstart owns the one line that runs it.

## Where the detail lives

- Flags, verbs and exit codes for one writer: the `SKILL.md` links above.
- Runnable commands for install, both state routes, the CI step and the two optional
  inputs: [docs/QUICKSTART.md](QUICKSTART.md).
- Record shapes, the state-root rule and the census's classes:
  `docs/PRODUCT.md`, which is the binding reference.
- Where noni's direction is committed, and what a team already running its own work
  driver does about claims: the quickstart's own coexistence section.
