# noni hook for Claude Code

A harness hook, not a tracker adapter: the block below wires `noni brief` into
a Claude Code main agent, so the agent cannot skip the direction layer. It
fills neither seam of the [adapter interface](../README.md) and is not the
thing that page's "Existing directories" list is about.

It does two things, and nothing else. At session start and after each
compaction it runs `noni brief` and hands the model what it printed. Every turn
it adds one standing reminder: noni holds the project's direction and
decisions, so work in the order it gives, follow the recorded decisions, invent
none, and ask the operator and record the answer when something is undecided.
The reminder is the same sentence the [pi hook](../pi/README.md) adds, so both
harnesses carry one wording.

## Install

Claude Code reads project hooks from `.claude/settings.json` in the project
root, and it merges what it finds there with the hooks the file already has. So
the block is added, not swapped in: open the project's `.claude/settings.json`,
and put the two entries below alongside any hooks it already carries. A
`.claude/settings.local.json` or a `~/.claude/settings.json` is a different
scope and a different file: neither is touched by this.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [
          {
            "type": "command",
            "command": "noni brief --repo \"$CLAUDE_PROJECT_DIR/.noni-state\"",
            "timeout": 30
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "noni brief --repo \"$CLAUDE_PROJECT_DIR/.noni-state\" 2>/dev/null || echo \"noni holds this project's product direction and decisions. Work in the order it gives and follow its recorded decisions; do not invent direction. When something is undecided, ask the operator and record the answer with the noni decide command.\""
          }
        ]
      }
    ]
  }
}
```

The prerequisite is that `noni` is on your PATH. The hooks run whichever `noni`
is first on PATH, so put the install you mean first. The quickstart's
[Install noni](../../docs/QUICKSTART.md#install-noni) section owns those
commands; this page does not reprint them.

## Which state root it reads

`noni brief` takes no default: `--repo` is required and names the state root,
the directory that holds `noni/`. The block above is anchored at
`$CLAUDE_PROJECT_DIR`, the project directory Claude Code gives a hook, rather
than at whatever directory the session happens to sit in, because a hook
command runs where the session is and Claude Code lets the agent move it.

The two roots a project has, and the one edit each needs:

- **State in a separate repository.** The state lives beside the project in
  `.noni-state/`, and the command above is already right.
- **State inside the project itself.** Then `.` is the state root, so drop the
  `/.noni-state` from both commands and the argument reads `--repo .`. This is
  the state root rule for the in-project route: `.` rather than a directory
  beside the project.

The quickstart's [Wire the project](../../docs/QUICKSTART.md#wire-the-project)
section states the same rule for the standing paragraph; this page owns the
block.

## When it runs, and the limit of it

The brief is fetched on every `SessionStart` whose matcher fires: startup,
resume, clear, compact and fork. A fork starts a new main session, so it needs
the brief as much as the others. The command carries a 30 second timeout, the
same bound the pi hook puts on its fetch: a hung `noni` costs that run its
brief, not the session.

The per-turn reminder fires on every turn the harness runs a `UserPromptSubmit`
hook for, including a turn the user did not type (a scheduled task, a
background subagent reporting in) and a turn inside a subagent. A JSON block has
no way to select the turns a human typed, and this adapter ships no script to do
it, so the reminder is billed to those turns too. It is one line, which is why
that is affordable.

## When the brief cannot be read

There is no script here, so there is no failure line either. When `noni` is
missing, or the state root holds no `noni/`, the brief command exits non-zero,
prints nothing on stdout, and the model gets no brief: the session is not
blocked. Claude Code shows the user its own notice that the hook failed, which
is where a reader looks, and the reminder still arrives every turn.

Hook stdout is capped at 10,000 characters; above it the harness replaces the
text with a path and a preview. `noni brief` bounds its own page, so on a
healthy state root the cap is never met.

## Verifying it

From the project root, run the brief command the block carries, with
`$CLAUDE_PROJECT_DIR` set to that root:

```bash
CLAUDE_PROJECT_DIR="$PWD" noni brief --repo "$CLAUDE_PROJECT_DIR/.noni-state"
```

Exit 0 with a page of output means the wiring can work. Then start Claude Code
in the project and ask the model what noni's current order is: it answers from
the brief, which it was handed before its first reply. Run `/compact` and ask
again, and it answers from a fresh brief. Point the same command at a directory
that holds no `noni/` and it exits 2, which is the case above: no brief, and the
session runs.
