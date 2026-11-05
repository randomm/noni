# Quickstart

Two pages tell a first-time reader how to run noni: the README's try-it block,
which records one decision and reads the census in five minutes, and this page,
which covers what that block cannot: how to install noni when no package index
carries it, where the state root may live, and the two routes to it.

`docs/PRODUCT.md` §7 is the binding statement of the state-root rule; this page
is the commands. Every tree this page names and every command in it is run
against a throwaway repository by the suite, so a step that stopped working
fails a test rather than a first run.

## Install noni

noni is not published. `pip install noni` installs some other project's wheel,
so every route to it names this repository, and none of them runs `pip` against
your system Python. On a distribution that marks that interpreter
externally-managed, a system `pip install` stops there with no `noni` on the
path, and forcing it past the marker installs noni's dependencies into the
system packages.

The form that also puts `noni` on your PATH is `uv tool install`:

```bash
git clone https://github.com/OWNER/noni noni
uv tool install ./noni
```

`uv` is a reader-side tool and not a dependency of noni; the git URL of your own
fork is an equally good target for the second line. Where you would rather not
install `uv`, build a clean virtual environment instead:

```bash
python3 -m venv .venv
.venv/bin/pip install ./noni
```

On Debian and Ubuntu that first line needs the `python3-venv` package installed,
and a venv creation that failed part way leaves a half-made `.venv` you have to
delete before the next attempt. Either route installs the same code the clone
carries: no package index sits between you and it, and neither is a release.

The wrappers under `skills/<skill>/scripts/` import the package rather than
carrying logic, so one of three states has to hold before any of them runs:
installed as above, installed editable, or `PYTHONPATH=<clone>/src`. A wrapper
whose package is missing says so on one line and exits 3; it does not raise.

`noni` and the wrapper paths are the same code and print the same bytes. Use
whichever the rest of this page makes shorter to type. `.venv/bin/noni <tool>` is
the same command on the venv route, where `noni` is not yet on your PATH.

## The state root

Every `noni/` path a tool reads or writes resolves from `--repo`, the one flag
that names the state root. Nothing else does: not the tool's own location, not
the current directory beyond `--repo`'s default, and no environment variable. A
`--repo` that is missing or is not a directory stops the command with a clear
message and that tool's own argument-refusal code.

Two routes. Both are supported, and both are covered below.

- **In-project state** (the default): the state root is the project's own
  repository, so state sits at `<project>/noni/` and is committed with the
  project. Every tool works without `--repo`.
- **A separate private state repository**: the state root is a clone of a
  second repository carrying the same `noni/` layout, and every command names
  it with `--repo .noni-state`. Clone it *inside* the project folder and add
  the ignore rule below, so an agent confined to the project folder can reach
  it. Choose it when the code repository is public and the direction should not
  be published with it.
- **Where the writers commit**: every noni writer commits straight to the branch
  it finds checked out in the `--repo` tree, and it never opens a branch or a pull
  request of its own. Route A therefore asks for direct commits to that branch: on a
  branch-protected or PR-only project, use Route B, whose commits land on the
  state repository's own branch.

## Route A: state inside the project

From the root of your own repository, with the identity the writers commit
under:

```bash
cd your-project
git config user.name "Casey"
git config user.email "casey@example.invalid"
noni decide --repo . --slug release-scope --scope release --asked-by team-lead \
  --question "q1=Ship the beta this week?" \
  --option "q1=Ship it" --option "q1=Wait a week" \
  --answer "q1=Wait a week"
noni census --repo .
```

The record lands at `noni/decisions/<date>-release-scope.json`, committed in
the same step the writer wrote it. The census reads the tree and recomputes
everything from git history plus those files, so a first run reports the two
warnings a tree without operator configuration carries — the inactive deny-list
and the ledger with nothing to arbitrate — and still ends `verdict ok`.
`git status --porcelain` is empty after the census: it never writes.

## Route B: a separate private state repository

The state repository is an ordinary git repository whose tracked content is the
`noni/` layout. Nothing about it is special except that it is private and that
every command names it.

Create the empty repository on your forge, then clone it inside the project and
tell your project's git to ignore the directory:

```bash
cd your-project
git clone git@forge.example:you/your-project-direction.git .noni-state
echo "/.noni-state/" >> .gitignore
```

The ignore rule is what keeps the direction out of the code repository: with it
the state clone is invisible to `git add .` in the project, and the state
repository's own history stays the only place the direction is committed. It is
a line you add once, to the project's `.gitignore`.

On a PR-only project, adding a line to `.gitignore` is itself a change to the
code repository, so write the rule where git reads it without tracking it
instead — `.git/info/exclude`, which git applies to every worktree of that
repository:

```bash
printf '/.noni-state/\n' >> .git/info/exclude
```

Give the clone an identity, and make its first commit. A clone of a repository
that has never held a commit has no branch at all, so there would be nothing for
a first push to name; the writers commit their own records onto that branch and
the push at the end of this section sends them. One empty commit is the simplest
way to create the branch, and it carries no content:

```bash
git -C .noni-state config user.name "Casey"
git -C .noni-state config user.email "casey@example.invalid"
git -C .noni-state commit --allow-empty -m "direction: first commit"
```

Now every command names the state clone. Same flags, same writers, same census
as Route A, with one path added:

```bash
noni decide --repo .noni-state --slug release-scope --scope release \
  --asked-by team-lead \
  --question "q1=Ship the beta this week?" \
  --option "q1=Ship it" --option "q1=Wait a week" \
  --answer "q1=Wait a week"
noni intent --repo .noni-state set --from ./intent-draft.md --decision <record-id>
noni order --repo .noni-state add 12 --decision <record-id>
noni census --repo .noni-state
```

`<record-id>` is the `<date>-<slug>` of a record in the ledger: both direction
files cite a decision that exists, so run the `decide` line first and read the id
off the `wrote noni/decisions/<id>.json` line it printed — the id is the date the
command ran plus `-release-scope`. On this route the line prints
`.noni-state/noni/decisions/<id>.json`, and the id is the file name without the
`.json` suffix. `intent-draft.md` starts from
`skills/direction/references/intent-template.md`, which validates as it stands;
the writer restamps its `Last-confirmed:` line to this run's UTC day and commits
the file as `intent: <record-id>`. Both direction files are optional: a project
that has written neither earns no `intent` (51) or `ordering` rows at all. Sessions come next.
`register` allocates its own session id and prints it, so you never choose one,
and `claim`, `release` and `close` all take that id as `--session-id`:

```bash
noni register --repo .noni-state --identity developer
noni claim --repo .noni-state --session-id <session-id> --task "#12"
```

The census reads only the tree `--repo`
names, so the code repository's tracked files never enter it — and its hygiene
class scans the tree it audits, which here is the state clone.

Then push the branch, once. The writers commit locally (and fetch-rebase-push
onto the branch they find, with `--push`); on a repository whose branch has
never existed the only thing to push is what the commands above just committed,
and `-u` is what makes every later push and pull of that branch work without
naming the remote again.

```bash
git -C .noni-state push -u origin main
```

## Run the census in CI

One shell step, run from the root of the repository whose state you want gated,
after the clone-and-install of the [Install](#install-noni) section: it is the
census line of Route A, and nothing else. No CI system is assumed and no workflow
file ships here. The page a team copying this into one specific CI needs is
[`integrations/github-issues/README.md`](../integrations/github-issues/README.md).

```bash
noni census --repo .
```

Route B runs the same step with the state clone as `--repo`:

```bash
noni census --repo .noni-state
```

The census audits only the tree `--repo` names, so on Route B the state clone is
what the build gates on and the code repository's tracked files never enter the
run.

Run it without `--strict`, and gate the build on these two sets, which are the
census's own classes split by their default severity:

- **fail the build** on 10, 12, 15, 20, 30, 31, 32 and 51;
- **report without failing** on 40, 41, 42, 43, 44, 45, 46 and 50.

`skills/census/SKILL.md` owns that table with the class names beside each code.
A warning never moves the exit code on its own, so a first CI run on a tree with
no deny-list exits 0 and prints the inactive row (`deny-list class inactive
(absent)`) as its only finding: that is the expected output, not a failure, and
[the deny-list section](#the-deny-list-and-why---strict-fails-on-a-fresh-attach)
says what switches the class on. `--strict` is the opt-in a team adds once that
file holds at least one usable entry, and under it every warn class above fails
the build at its own code.

## The deny-list, and why --strict fails on a fresh attach

`--strict` promotes every warn class to a failure at its own code, `hygiene`
(50) included. A freshly attached project has no deny-list, so the hygiene
class is inactive, and a `--strict` run fails on it even though nothing in the
tree is wrong. The row is honest about the state it found: `deny-list class
inactive (absent)`, or `corrupt`, or `present but empty`.

The file is `.noni-scrub-denylist`, one entry per line, held at the root of the
tree being audited — `<project>/.noni-scrub-denylist` on Route A,
`.noni-state/.noni-scrub-denylist` on Route B. `NONI_SCRUB_DENYLIST` names a
different file when the tree carries no default of its own. Blank lines and
lines starting with `#` are not entries, so a file that holds only those is
`present but empty` and still inactive: at least one usable entry is what
switches the class on.

```
# one name per line: an operator name, an external project or tool name,
# or a hostname the scan must never find in a tracked file
example-corp
```

Keep it untracked, and say so in the tree's `.gitignore` the way this repository
does, with a rule for the file's own name (`/.noni-scrub-denylist`): it is the
half of the public-repo hygiene rule the committed patterns cannot carry, because
the names themselves must not be committed. `docs/PUBLISHING.md` step 1 is the
checklist that uses it, and the gate it runs — not a clean census — is this, from
the clone's own root:

```bash
python scripts/public_safety.py
```

That CLI exits 2 when the class was not active, so it cannot report a false
"clean" on a tree whose deny-list is absent, corrupt or empty.

## The --issue-state map, and what the census skips without it

The census never contacts a tracker. Whether an ordered issue is closed reaches
it only through `--issue-state FILE`: a JSON object mapping each issue number,
spelled as a bare decimal string, to `"open"` or `"closed"`. Without the flag
the `ordering-closed` (46) class is not evaluated at all, so a run with no rows
from it does not mean every ordered issue is open.

The census says so out loud when you look at it in human-readable mode: one
line, `note: ordering-closed was not evaluated: no --issue-state FILE was
given`, printed beside the report. A CI run that gates on the exit code can skip
the note and read the rows instead: `--json` mode prints no such line — that
stream is findings and a summary, and a notice about a class that did not run
is neither — so read the note from a run without `--json`, and keep the
ordering group in the run (`--only` must name an ordering class, or name none).

The census ships no producer. A tracker with a command line and `jq` produce
one:

```bash
gh issue list --json number,state --jq \
  'map({key: (.number | tostring), value: (.state | ascii_downcase)}) | from_entries' \
  > issue-state.json
noni census --repo . --issue-state issue-state.json
```

Two details in that recipe are the whole of its correctness. `.number |
tostring` is what makes the key the bare decimal string the census looks up:
`"007"`, `"+7"`, `0` and a non-ASCII digit are all refused as
`ordering-malformed` (15) rather than read as silence. `.state | ascii_downcase`
is what makes the value one of the two words the file may name; anything else
is the same refusal.

A map may be partial — an issue the file does not mention earns a
`cannot-tell` row of the same class, not a clean bill — and a run whose tree
holds no `noni/direction/order.json` earns no ordering rows at all, because the
ordering layer is optional.

## Prerequisites

Three things outside noni decide whether a first run works:

- **`jq`** for `census.sh`, the ledger shim, which exits 3 naming the machine
  when it is missing. The unified census (`census.py`) does not need it.
- **A git identity in the state tree**: `git config user.name` and
  `user.email` are read from the tree `--repo` names, not from your shell's
  directory. `decide.py` refuses with exit 3 and names the command that fixes
  it; the writers need `user.email` for the commit itself. On Route B that
  means the state clone, not the project.
- **A Python 3 on the reading machine** for `census-sessions.sh`, which runs
  the interpreter named by `NONI_PYTHON` and defaults to `python3`. That
  interpreter also has to import the package, so the wrappers under
  `skills/<skill>/scripts/` need the install above or `PYTHONPATH=<clone>/src`
  whichever route you took.
