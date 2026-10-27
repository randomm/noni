# noni

noni is an attachable direction layer for a Git project that several agents or
people work on at once. It keeps the decisions, the agreed order of work, the
session register and the claims as plain files committed to the repository, and
one read-only script reports where the work has drifted from that direction.
There is no service to run and no database to keep in step.

## The problem

- Decisions get made in a session and die with it. The next session reopens the
  same question, or quietly contradicts the answer.
- Two workers take the same task. Neither knows, because nothing in the
  repository says who means to do what.
- Nobody can say whether the work still matches the direction. The order was set
  weeks ago, several issues in it are closed, and nothing reports that.

## What you get

Four artifacts, all committed files under `noni/`, all read by the census:

| artifact | what it holds | who writes it |
|---|---|---|
| steering ledger | one JSON file per dated, attributed decision under `noni/decisions/` | `decide.py` |
| ordering | the issues you want worked next, in order, in `noni/direction/order.json` | `order.py` |
| session register | one file per session under `noni/sessions/`, with its claims | `register.py` and `claim.py` |
| census | nothing: it reads the three above and reports | read-only |

Claims are signals, not locks. A claim tells everyone else what you intend to
work on; the census is what flags two active claims on one task.

## Try it in five minutes

Clone noni next to your project, go to the root of your own repository, and
run its scripts with `--repo .` naming that repository. Nothing is copied into
your project, and the census's hygiene checker stays present beside the scripts
it runs:

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

Run these from a release of noni you trust: they execute its scripts.

The census is read-only: it never writes, so `git status --porcelain` is empty
after either run.

Read the result. A run with nothing to complain about ends with a summary line
of this shape:

```
summary: clean; N finding(s); verdict ok
```

The count names the rows above it; warnings (a missing deny-list, a ledger with
nothing to arbitrate) are counted there and do not change the verdict.

Read `noni/skills/<skill>/SKILL.md` for what each writer accepts and refuses.
The steering-ledger and sessions-claims skills keep record-shape detail in
their `references/` directories.

## How it works

Everything noni keeps in your repository lives in one directory:

```
<project>/noni/
  decisions/   one JSON record per dated decision
  direction/   order.json: the ordered list of issues to work next
  sessions/    one Markdown file per session, one writer each
```

Nothing else is state. The writers above are the only things that create those
files, and each commits what it writes in one atomic step. The try-it run above
creates the ledger record only: `order.json` appears when you first run
`order.py`, and a session file when you first run `register.py`. The census also
reads input it does not own: the `--issue-state` map an adapter or the operator
supplies, whose absence it reports as an unevaluated check. The census recomputes
everything it reports from git history plus those files on every run: metrics
are derived, never self-reported.

The skills are the unit of product. An agent working in your repository loads
`skills/<skill>/SKILL.md`, which names the script to run, the flags it takes and
the exit codes it returns.

## Status

Shipped, and covered by the test suite: the steering ledger with its supersede
chain, the session register and claim protocol, the ordering artifact, and the
unified census with its honest exit codes.

Not yet: packaging, so until it lands you run the scripts from a clone of
noni rather than installing one `noni` command, and the direction features
above the ordering artifact (release trains, standing direction). The epic map
(E1-E5) lives in `docs/PRODUCT.md` §8, which is the product document and the
deep reference for record shapes, the claim protocol and the census exit codes.

noni's own `noni/decisions/` is still empty: this repository does not yet run
the ledger it ships.

## Purity

noni holds no project-specific content: no tickets, no backlog entries, no
references to any attached project. The generic how ships here; the what belongs
to the attached project. Adapters for one tracker or driver live under
`integrations/`, and the core stays usable with none of them installed.

## Contributing

Set up the venv and run the gates in [CONTRIBUTING.md](CONTRIBUTING.md). Before
publishing a public tree, follow the scrub checklist in
[docs/PUBLISHING.md](docs/PUBLISHING.md). The committed check covers
machine-local paths and secret shapes; operator names, external project or tool
names and hostnames are covered only by the untracked deny-list that checklist
requires.
