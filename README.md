# noni

noni makes sure two agents working on one project never take the same task, and
that a decision outlives the session that made it. It is an attachable direction
layer for a Git project: standing intent, decisions, the agreed order of work,
the session register and the claims are plain files committed to the repo, and
one read-only script reports where the work has drifted. No service, no database.

## The problem

- Decisions get made in a session and die with it. The next session reopens the
  same question, or quietly contradicts the answer.
- Two workers take the same task. Neither knows: nothing says who means what.
- Nobody can say whether the work still matches the direction. The order was set
  weeks ago, several issues in it are closed, and nothing reports that.
- What the project is for, and what it will not do, live in someone's head.

## What you get

Five artifacts, all committed files under `noni/`, all read by the census. The
order is of issues your tracker holds, by their positive numbers: noni is no
backlog and no notes tool, so unfiled work has nowhere to go.

| artifact | what it holds | who writes it |
|---|---|---|
| standing intent | what the project is for, its principles, its never-do list, and what must be asked first, in `noni/direction/intent.md` | `intent.py` |
| steering ledger | one JSON file per dated, attributed decision under `noni/decisions/` | `decide.py` |
| ordering | the issues you want worked next, in order, in `noni/direction/order.json` | `order.py` |
| session register | one file per session under `noni/sessions/`, with its claims | `register.py`, `claim.py`, `release.py` and `close.py` |
| census | nothing: it reads the four above and reports | read-only |

Claims are signals, not locks. A claim tells everyone else what you intend to
work on; the census is what flags two active claims on one task. The intent file
is a statement, not a lock either: it tells a session how to decide, and the
census is what flags one that has drifted from its shape or its citation.

Every path above resolves from `--repo`, the one flag that names the state root:
by default the repository you run in, so the state sits at `<project>/noni/`, or
a separate directory holding the same `noni/` layout to keep the direction in a
private state repository, which holds the `noni/` layout and nothing else; a
missing or non-directory `--repo` stops the command with a clear message.

## Try it in five minutes

The full first run, including a separate private state repository, is in
[docs/QUICKSTART.md](docs/QUICKSTART.md). The short version: clone noni next to
your project, run its scripts from the root of your own repository with
`--repo .` naming it. Nothing is copied into your project, and the
census's hygiene checker stays present beside the scripts it runs:

```bash
git clone https://github.com/OWNER/noni noni
cd your-project

git config user.name "Casey"
git config user.email "casey@example.invalid"

python3 ../noni/skills/steering-ledger/scripts/decide.py --repo . \
  --slug release-scope --scope release --asked-by team-lead \
  --question "q1=Ship the beta this week?" \
  --option "q1=Ship it" --option "q1=Wait a week" \
  --answer "q1=Wait a week"

python3 ../noni/skills/census/scripts/census.py --repo .
```

Run these from a commit of noni you trust: no release or tag exists yet, so pin
a commit, and remember they run noni's scripts.

Installing is the other route, and the same code either way. Those scripts import
the `noni` package, so it must be installed or importable for them to run: see the
*Install noni* section of [docs/QUICKSTART.md](docs/QUICKSTART.md#install-noni),
which installs it with `uv tool install` or in a clean virtual environment. There
is no PyPI package and the name will be `noni-noni`, so every route names this
repository, and none runs `pip` at a system Python, which current distributions
refuse. One `noni` command replaces a path per tool (`census`, `decide`, `register`,
`claim`, `release`, `close`, `order`, `intent`), printing the same bytes.

The census is read-only: it never writes, so `git status --porcelain` is empty.
Read the result. A run with rows ends with the line

```
summary: W warning(s); N finding(s); verdict ok
```

where `W` counts the warnings among the `N` rows above it (on a first tree, a
missing deny-list and a ledger with nothing to arbitrate), and does not move it.

## How it works

Read `noni/skills/<skill>/SKILL.md` for what each writer accepts and refuses;
the steering-ledger and sessions-claims skills keep record-shape detail in their
`references/` directories. `noni --help` names the nine subcommands and
`noni <tool> --help` the flags of one.

Everything noni keeps in your repository lives in one directory:

```
<project>/noni/
  decisions/   one JSON record per dated decision
  direction/   intent.md: what the project is for and will not do
               order.json: the ordered list of issues to work next
  sessions/    one Markdown file per session, one writer each
```

Nothing else is state. The writers above are the only things that create those
files, and each commits what it writes in one atomic step. The try-it run above
creates the ledger record only: `intent.md` appears when you first run
`intent.py`, `order.json` when you first run `order.py`, and a session file when
you first run `register.py`. All four are optional, and only a run that counted
no row and skipped no check reads all-clear (`census: no findings; all checks
passed`, `summary: clean; 0 finding(s); verdict ok`); the try-it run above does
not: the always-reporting hygiene class leaves a first tree a warn row. The
census also reads input it does not own: the `--issue-state` map an adapter or
the operator supplies, whose absence it reports as an unevaluated check. It
recomputes everything from git history plus those files, so metrics are derived,
never self-reported. Each `skills/<skill>/SKILL.md` names its script, flags and
exit codes; [docs/ONBOARDING.md](docs/ONBOARDING.md) covers the skills.

## Status

Shipped, and covered by the test suite: the steering ledger with its supersede
chain, the session register with its claim, release and close verbs, the
ordering artifact, the standing intent file with its precedence rule, the
unified census with its honest exit codes, and the `noni` package that carries
them (installed from a clone or a git URL, then `noni <tool>`: no PyPI package,
distribution name `noni-noni`).

Not yet: the adapters that fill the tracker-side inputs the census reads.
`docs/PRODUCT.md` is the product document and the deep reference for record
shapes, the claim protocol and the census exit codes.

noni's own direction lives in a private state repository, so `git ls-files noni`
here is empty: pass `--repo` at the tree that holds the `noni/` layout.

## Purity

noni holds no project-specific content: no tickets, no backlog entries, no
references to any attached project. The generic how ships here; the what belongs
to the attached project. Adapters for one tracker or driver live under
`integrations/`, and the core stays usable with none of them installed.

## Contributing

Set up the venv and run the gates in [CONTRIBUTING.md](CONTRIBUTING.md). Before
publishing, follow [docs/PUBLISHING.md](docs/PUBLISHING.md): names and hostnames
are caught only by its untracked deny-list, not by the committed check.

License: Apache-2.0 ([LICENSE](LICENSE)). Report security problems privately:
[SECURITY.md](SECURITY.md).
