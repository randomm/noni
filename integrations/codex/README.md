# noni hook for Codex

A harness hook, not a tracker adapter: the snippet below wires `noni brief` into a
Codex session, so the agent cannot skip the direction layer. It fills neither seam
of the [adapter interface](../README.md) and is not the thing that page's "Existing
adapters" list is about.

It does two things, and nothing else. At session start, and again after each
compaction, it runs `noni brief` and hands the model what it printed as extra
developer context. Every user prompt it adds the one standing reminder: noni holds
the project's direction and decisions, so work in the order it gives, follow the
recorded decisions, invent none, and ask the operator and record the answer when
something is undecided. It registers no tool and no script of its own.

## Which state root it reads

The state root is the `--repo` argument of the one command in the snippet, and this
page ships it git-rooted: `"$(git rev-parse --show-toplevel)/.noni-state"`, the form
that survives being started from a subdirectory.

Codex runs a hook command with the session's working directory as its cwd, so a
relative `--repo` would name a different directory in every subdirectory the session
happens to sit in. When the state lives inside the project, drop `/.noni-state` and
run the command with `--repo "$(git rev-parse --show-toplevel)"`. Either way
`noni` must be on your PATH: Codex runs whichever `noni` is first on PATH, so put
the install you mean first. The quickstart's
[Install noni](../../docs/QUICKSTART.md#install-noni) section owns those commands;
this page does not reprint them.

## When it runs

`SessionStart` with the matcher `startup|resume|clear|compact` fetches the brief on
every start that needs one and after each compaction, and Codex adds what the
command printed on stdout to the model's context as extra developer context.
`UserPromptSubmit` prints the reminder, and Codex adds that plain stdout to the
model's context on each user prompt. `UserPromptSubmit` ignores any matcher, so the
reminder reaches every user prompt, a subagent's included. A subagent gets that
reminder and never the brief: the brief is registered only on `SessionStart`, which
is the event of the session itself.

Hooks are on unless your own config turns them off, which the file the same page
calls `config.toml` does with `hooks = false` under `[features]`.

## The limit of that rule

What the reminder buys is one sentence per prompt, and what it can lose is
everything else. A prompt that arrives before `SessionStart`'s command returned gets
the reminder and no brief, because the two hooks are independent and neither waits
for the other. The reminder is also the same sentence every turn, so it keeps the
order in view without carrying it: the brief is the only thing that names what that
order currently is.

## Install

The one file the snippet is copied into is `.codex/hooks.json` in the project root:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "noni brief --repo \"$(git rev-parse --show-toplevel)/.noni-state\"",
            "timeout": 30,
            "statusMessage": "Reading noni's direction",
            "additionalContextLimit": 8000
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo \"noni holds this project's product direction and decisions. Work in the order it gives and follow its recorded decisions; do not invent direction. When something is undecided, ask the operator and record the answer with the noni decide command.\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Two gates sit between that file and the model, and until both hold the hook is
skipped: no brief and no reminder. The project has to be trusted, because Codex
loads hooks only from trusted project layers. And the hook has to be reviewed and
trusted, because Codex records trust against the definition's own hash, so a pasted
or edited definition is marked for review and skipped until you trust it. Open
`/hooks` in the CLI to check either gate: it lists the sources, marks a hook that is
new, changed or untrusted, and is where you trust or disable one. A hook that is
being skipped says little in the session itself, so the check below runs the hook's
own command by hand rather than trusting what the model answers.

## Verifying it

Start Codex in the attached project and ask the model what noni's current order is:
it answers from the brief, which it was handed before its first reply. Run a
compaction and ask again, and it answers from a fresh brief.

Then run the hook's own command by hand from the project root:

```
noni brief --repo "$(git rev-parse --show-toplevel)/.noni-state"
```

Exit 0 with the brief on stdout is the wiring working. A state root holding no
`noni/` directory is not: the command exits nonzero, and a failed start hook gives
the model no context at all, so the session runs as if nothing were wired up, with
the reminder printed on top of an order that is not there. Fix the state root before
trusting the hook, and `/hooks` is where you see whether the hook ever ran.
