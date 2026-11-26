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
run the command with `--repo "$(git rev-parse --show-toplevel)"`.

Two departures from the pi hook's rule are deliberate, and a reader who knows that
page needs to know them. There is no `NONI_STATE_ROOT` rung: noni's core names no
environment variable that selects a state root, and Codex builds a command hook's
environment outside this page, so a snippet cannot read one. And there is no failure
arm: the hook prints what `noni brief` printed and nothing else, so a wrong state
root gives the model a brief over an empty page rather than the line the pi hook
prints when it cannot read one. [docs/PRODUCT.md](../../docs/PRODUCT.md) section 7 is
the rule both pages answer to, and this one resolves the root by argv alone.

Either way `noni` must be on your PATH: Codex runs whichever `noni` is first on PATH,
so the hook trusts whatever that resolves to. Before you trust the hook, run
`command -v noni` and `noni --version` in the project and check both answers are the
install you mean. The quickstart's
[Install noni](../../docs/QUICKSTART.md#install-noni) section owns those commands and
what each answer means; this page does not reprint them.

## When it runs

`SessionStart` with the matcher `startup|resume|clear|compact` fetches the brief on
every start that needs one and after each compaction, and Codex adds what the
command printed on stdout to the model's context as extra developer context.
`UserPromptSubmit` prints the reminder, and Codex adds that plain stdout to the
model's context on each user prompt. `UserPromptSubmit` ignores any matcher, so the
reminder reaches every user prompt, a subagent's included. A subagent gets that
reminder and never the brief: the brief is registered only on `SessionStart`, which
is the event of the session itself.

Hooks are on by default. To turn them off, set `hooks = false` under `[features]` in
your own `config.toml`; the Codex hooks reference ("Turn hooks off") is the page that
names that key, so a reader who cannot find it should re-check that spelling before
believing hooks are off.

## The limit of that rule

What the reminder buys is one sentence per prompt, and what it can lose is
everything else. A prompt that arrives before `SessionStart`'s command returned gets
the reminder and no brief, because the two hooks are independent and neither waits
for the other. The reminder is also the same sentence every turn, so it keeps the
order in view without carrying it: the brief is the only thing that names what that
order currently is.

The brief itself is a bounded payload. Its handler carries `additionalContextLimit`
(8000 tokens) because Codex caps a command hook's additional context at 2500 tokens
without the key and spills the whole of it to a file above whatever limit the handler
names, so the number the snippet ships is what bounds the context it injects.

The two handlers fail differently, and the difference is the operator's, not the
model's. A start hook that exits non-zero leaves the session with no brief, which is
what the state-root check below looks for. A per-turn hook that exits non-zero has
the worse end: for `UserPromptSubmit` a non-zero exit blocks the prompt itself, so
the operator cannot type. That is why the per-turn command is a bare `echo` of one
fixed sentence and nothing else, capped at 5 seconds: it spawns no `noni`, reads no
state root, and has no failure arm to fire.

Two things on this page run under the attached project's own state rather than
noni's. The git substitution in the brief command is resolved by the shell with that
tree's git config in force, so a config there can make session start wait for the
30 second timeout. And the hook trusts whatever `noni` PATH resolves: `command -v
noni` is the check that shows which binary that is.

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
            "command": "echo \"noni holds this project's product direction and decisions. Work in the order it gives and follow its decisions; invent none. The brief outranks your summary or memory: check it first. When the operator corrects you, put it to them as a candidate and record their answer with the noni decide command.\"",
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

Then run these from the project root, the first two being what the hook itself runs:

```
noni brief --repo "$(git rev-parse --show-toplevel)/.noni-state"
command -v noni
noni --version
```

The brief is the wiring: read what it printed, because the exit code is not the
signal. A state root that holds no `noni/` directory still exits 0 and prints the
standing rules over an empty page, so `Purpose: not readable`, `top 10: the order is
empty` and a `recent decisions` block with no rows mean the hook is briefing the
model on nothing. `summary: not-run; 0 finding(s); verdict fail` is the other
sentence to look for: it is the brief's own way of saying the arbiter never judged
the tree. Either way fix the state root, or run `noni census --repo
"$(git rev-parse --show-toplevel)/.noni-state"` to see the whole report behind that
one line.

The last two commands say which `noni` the hook will exec and which version it
carries, which is what tells a shadowed install apart from the one you meant. A
failed start hook gives the model no context at all, so the session runs as if
nothing were wired up, with the reminder printed on top of an order that is not
there. `/hooks` is where you see whether the hook ever ran.
