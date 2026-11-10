# Quickstart

Two pages tell a first-time reader how to run noni: the README's try-it block,
which records one decision and reads the census in five minutes, and this page,
which covers what that block cannot: how to install noni when no package index
carries it, where the state root may live, and the two routes to it.

`docs/PRODUCT.md` §7 is the binding statement of the state-root rule; this page
is the commands.

## Install noni

noni is not published, and the distribution name will be `noni-noni`. `pip install
noni` installs some other project's wheel, so every route to it names this
repository, and none of them runs `pip` against your system Python. On a
distribution that marks that interpreter externally-managed, a system `pip install`
stops there with no `noni` on the path, and forcing it past the marker installs
noni's dependencies into the system packages.

The form that also puts `noni` on your PATH is `uv tool install`:

```bash
git clone https://github.com/OWNER/noni noni
uv tool install ./noni
```

`uv` is a reader-side tool and not a dependency of noni; the git URL of your own
fork is an equally good target for the second line. Where you would rather not
install `uv`, build a clean virtual environment and use its own `pip`:

```bash
python3 -m venv .venv
.venv/bin/pip install ./noni
```

On Debian and Ubuntu that first line needs the `python3-venv` package installed,
and a venv creation that failed part way leaves a half-made `.venv` you have to
delete before the next attempt. Where that package is missing the venv is built
without `pip` at all, the second line stops naming `.venv/bin/pip`, and only the
`PYTHONPATH` fallback below works: install the distro's venv and pip packages,
which carry `ensurepip` — what puts `pip` in a new venv — delete the pip-less
`.venv`, and run the two lines again. Either route installs the same code the
clone carries: no package index sits between you and it, and neither is a
release.

Before you run anything, check what you are about to run. An older noni already
on your PATH shadows the install you just made, and it prints the same version
string, so nothing but its own location tells you which one answered:
`command -v noni` prints the path the shell will exec, and it must be the one you
just installed (`.venv/bin/noni`, or uv's tool directory). An install that has to
replace an existing one is re-run over it — the same line a second time, not a
second install beside the first.

The wrappers under `skills/<skill>/scripts/` import the package rather than
carrying logic, so before any of them runs the package must be installed, installed
editable, or importable on `PYTHONPATH=<clone>/src`; every skill page that prints one
points back here. On that last state the command to type is
`PYTHONPATH=<clone>/src python3 -m noni <tool>`, which runs the same CLI as
`noni <tool>`; there is no `noni` on your PATH yet, because nothing was installed. A
wrapper whose package is missing says so on one line and exits 3; it does not raise.

`noni` and the wrapper paths are the same code and print the same bytes. Use
whichever the rest of this page makes shorter to type. `.venv/bin/noni <tool>` is
the same command on the venv route, where `noni` is not yet on your PATH.

## The state root

Every `noni/` path a tool reads or writes resolves from `--repo`, the one flag
that names the state root. Nothing else does: not the tool's own location, not
the current directory beyond `--repo`'s default, and no environment variable. A
`--repo` that is missing or is not a directory stops the command with a clear
message and that tool's own argument-refusal code, and so does a `--repo` holding no `noni/` (§7).

Two routes. Both are supported, and both are covered below.

- **In-project state** (the default): the state root is the project's own
  repository, so state sits at `<project>/noni/` and is committed with the
  project. Every tool works without `--repo`.
- **A separate private state repository**: the state root is a clone of a
  second repository whose tracked content is the `noni/` layout and nothing else,
  and every command names it with `--repo .noni-state`. Clone it *inside* the
  project folder and add the ignore rule below, so an agent confined to the
  project folder can reach it. Choose it when the code repository is public and the
  direction should not be published with it. Make it a new, empty, private
  repository: the census's hygiene class reads every tracked file of the tree
  `--repo` names, so anything beside the layout is scanned as direction too.
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
and the ledger with nothing to arbitrate — and still ends `verdict ok`: its last
line names them, `summary: W warning(s); N finding(s); verdict ok`. `clean` and
the all-clear banner `census: no findings; all checks passed` belong to a run
that counted no row and skipped no check. The census never writes.

## Route B: a separate private state repository

The state repository is an ordinary git repository whose tracked content is the
`noni/` layout and nothing else — no source, no build output, no notes of your
own, because the hygiene scan reads every tracked file of the tree `--repo` names
and reports what it finds as direction. Make it a new, empty, private repository
rather than a folder of things you already have. Nothing about it is special
except that it is private and that every command names it.

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
off the `wrote .noni-state/noni/decisions/<id>.json` line it printed — the id is the date the
command ran plus `-release-scope`, and it is the file name without the `.json`
suffix. Every writer names the file it wrote the same way on both routes: `--repo`
joined to the path under the state root, spelled identically with and without
`--no-commit`, so a state clone never reads as a stray `noni/` directory beside
your project. `intent-draft.md` starts from
`skills/direction/references/intent-template.md`, which validates as it stands;
the writer restamps its `Last-confirmed:` line to this run's UTC day and commits
the file as `intent: <record-id>`. Both direction files are optional: a project
that has written neither earns no `intent` (51) or `ordering` rows at all.

The census reads only the tree `--repo`
names, so the code repository's tracked files never enter it — and its hygiene
class scans the tree it audits, which here is the state clone.

Then write the state clone's scrub deny-list: the untracked file the section below
explains. It sits at the clone's root, not the project's, and must stay untracked: a
committed list of the names being scanned for is the leak the file exists to prevent.

The example names are the ones the deny-list section below shows; put your own in
their place. Then ignore the file in the clone and commit that rule:

```
example-corp
```

```bash
echo '/.noni-scrub-denylist' >> .noni-state/.gitignore
git -C .noni-state add .gitignore
git -C .noni-state commit -q -m 'chore: keep the scrub deny-list untracked'
```

Then push the branch, once. The writers commit locally (and fetch-rebase-push
onto the branch they find, with `--push`); on a repository whose branch has
never existed the only thing to push is what the commands above just committed,
and `-u` is what makes every later push and pull of that branch work without
naming the remote again.

```bash
git -C .noni-state push -u origin HEAD
```

`HEAD` is deliberate: it names whatever branch the clone happens to be on, so the
line works whether the forge seeded it with `main`, `master` or a name of your
own. Naming a branch is what broke the pilot run — a fresh `git init` does not
have to default to `main`, and the page cannot know which branch yours is on.

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

- **fail the build** on 10, 12, 15, 20 and 51;
- **report without failing** on 41, 42, 45, 46 and 50.

`skills/census/SKILL.md` owns that table with the class names beside each code.
A warning never moves the exit code on its own, so a first CI run on a tree with
no deny-list exits 0 and prints the inactive row (`deny-list class inactive
(absent)`) as its only finding: that is the expected output, not a failure, and
[the deny-list section](#the-deny-list-and-why---strict-fails-on-a-fresh-attach)
says what switches the class on. `--strict` is the opt-in a team adds once that
file holds at least one usable entry, and under it every warn class above fails
the build at its own code.

## Using noni alongside a driver that keeps its own claims

A team attaching noni may already run a work driver of its own: one that keeps
per-issue state, worktree claims and a queue. noni does not compete with it.

- **The direction layer is always used.** The steering ledger
  (`noni/decisions/`) and the ordering artifact (`noni/direction/order.json`) are
  the shared direction layer, and a team that attaches noni runs them.
- **The claim state stays the driver's.** Where a driver already owns
  claim state, noni does not keep a second copy of it. Never both by hand:
  two claim systems written by hand disagree, and only one of them is read
  by the thing that arbitrates.
- **The census still runs, and it asks no claim question at all.**
  That is the state this page documents for such a team, and the state is that
  `noni/sessions/` **does not exist**: do not create it as an empty directory.
  A tree that holds no claim files is a clean state, and the census adds no row
  for an artifact it was never given.

## The deny-list, and why --strict fails on a fresh attach

`--strict` promotes every warn class to a failure at its own code, `hygiene`
(50) included. A freshly attached project has no deny-list, so the hygiene
class is inactive, and a `--strict` run fails on it even though nothing in the
tree is wrong. The row is honest about the state it found: `deny-list class
inactive (absent)`, or `corrupt`, or `present but empty`.

The file `.noni-scrub-denylist` holds one entry per line, at the root of the tree
being audited — `<project>/.noni-scrub-denylist` on Route A,
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
"clean" on a tree whose deny-list is absent, corrupt or empty. A gate that could not
run is a different answer, always exit 3: `noni` not importable, or the committed
`.noni-scrub-allowlist` not readable -- `path | label | reason` per exact path and
label, letting a fixture keep a token-shaped string (step 1 of
[Publishing noni](PUBLISHING.md#before-publishing) owns it).
## The --issue-state map, and what the census skips without it

The census never contacts a tracker. Whether an ordered issue is closed reaches
it only through `--issue-state FILE`: a JSON object mapping each issue number,
spelled as a bare decimal string, to `"open"` or `"closed"`. Without the flag
the `ordering-closed` (46) class is not evaluated at all, so a run with no rows
from it does not mean every ordered issue is open.

The census says so out loud whichever mode you read it in, and it says it in the
part of the report a gate reads. Over an order that holds issues, the class
reports itself: one `ordering-closed` row whose subject is the order file, saying
the closed state was not checked. Without `--strict` it is a `warn` and the exit
code stays 0; under `--strict` it is promoted and earns its own 46, so a CI step
that gates on the exit code cannot stay green over an order whose issues have all
been closed. A run over an empty order, an absent order, or one whose class you
skipped by name prints no such row and no code, because nothing was left
unasked.

In human-readable mode the report also says it in its first line and in one
`note:` line, so a person scanning a terminal learns the same thing. A run that
carries no row of the class opens `census: no findings; <class> did not run`, and
one that carries the row names the class on the count line; either way the
summary line ends `ordering-closed not checked` rather than the word `clean`:

```text
note: ordering-closed was not evaluated: no --issue-state FILE was given, so whether an ordered issue is closed is not asked (the census never contacts a tracker)
```

In `--json` mode no such line goes to stdout — that stream stays findings and
one summary — and the same sentence is instead carried on the summary row as its
`not_evaluated` field, a list of the classes the run did not evaluate and why.
The field is the machine's record of the unasked question and the row is the
report's verdict on it: both are present, and a consumer that reads only the
summary row still sees the class. Keep the ordering group in the run either way
(`--only` must name an ordering class, or name none), because a run that never
reached the class reports nothing about it.

The census ships no producer. A tracker with a command line and `jq` produce
one:

```bash
gh issue list --state all --json number,state --jq \
  'map({key: (.number | tostring), value: (.state | ascii_downcase)}) | from_entries' \
  > issue-state.json
noni census --repo . --issue-state issue-state.json
```

Three details in that recipe are the whole of its correctness. `--state all` is
what makes a closed issue appear at all: `gh issue list` reports open issues
unless you say otherwise, so without the flag an ordered issue you closed last
week is simply absent from the map, and the census reads it as a `cannot-tell`
row of the `ordering-closed` class rather than as closed. `.number |
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

Two things outside noni decide whether a first run works:

- **A git identity in the state tree**: `git config user.name` and
  `user.email` are read from the tree `--repo` names, not from your shell's
  directory. `decide.py` refuses with exit 3 and names the command that fixes
  it; the writers need `user.email` for the commit itself. On Route B that
  means the state clone, not the project.
- **A Python 3 on the reading machine** for every entry point under
  `skills/<skill>/scripts/`, including the ledger shim `census.sh`,
  which runs the interpreter named by `NONI_PYTHON` and defaults to `python3`. That
  interpreter also has to import the package, so the wrappers need the install
  above or `PYTHONPATH=<clone>/src`
  whichever route you took.
  A wrapper whose interpreter or package is missing names the fault on one plain
  line and exits 3 rather than printing a traceback. The shim needs no `jq`: the
  unified census is the one arbiter of both.
