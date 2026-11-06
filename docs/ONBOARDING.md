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

noni ships four core skills, one directory each, and each one's entry point is its
`SKILL.md`. All four are named below, each by the path a loader reads.

| skill | its page | what it owns |
|---|---|---|
| steering-ledger | [`skills/steering-ledger/SKILL.md`](../skills/steering-ledger/SKILL.md) | the dated decision records under `noni/decisions/` |
| direction | [`skills/direction/SKILL.md`](../skills/direction/SKILL.md) | the standing intent and the ordered list under `noni/direction/` |
| sessions-claims | [`skills/sessions-claims/SKILL.md`](../skills/sessions-claims/SKILL.md) | the session register and its claims under `noni/sessions/` |
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

One agent session in an attached project follows five steps. Each row names the
skill that owns the step, and the link is where the how lives. The three
sessions-claims rows are taken only if your team uses noni's sessions and claims;
the direction and steering-ledger rows are taken by every team. Where a work
driver of your own already keeps claim state, skip the three and read the
quickstart's coexistence section, named at the foot of this page, before you do.

| when | step | owning skill |
|---|---|---|
| at start | read the standing intent first, when the project has written one | [`skills/direction/SKILL.md`](../skills/direction/SKILL.md) |
| at start | register the session, which allocates its id and commits its own file | [`skills/sessions-claims/SKILL.md`](../skills/sessions-claims/SKILL.md) |
| at start | read the current order, and claim the task you mean to work before you work it | [`skills/sessions-claims/SKILL.md`](../skills/sessions-claims/SKILL.md) |
| during work | record a decision through the steering-ledger writer when the operator steers you | [`skills/steering-ledger/SKILL.md`](../skills/steering-ledger/SKILL.md) |
| at the end | release the claim you no longer hold, and close the session when it is finished | [`skills/sessions-claims/SKILL.md`](../skills/sessions-claims/SKILL.md) |

Two of those steps need a word about what they are for, because an agent that
skips them is the failure mode the census exists to catch. Both words apply to a
team that runs the two steps:

- **Claim before you work.** Claims are signals, not locks: nothing refuses a second
  agent, and the census's double-claim check is what flags two active claims on one
  task. Working without a claim is invisible to everyone else.
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
- Record shapes, the claim protocol, the state-root rule and the census's classes:
  `docs/PRODUCT.md`, which is the binding reference.
- Where noni's direction is committed, and what a team already running its own work
  driver does about claims: the quickstart's own coexistence section.
