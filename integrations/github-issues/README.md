# GitHub-issues adapter

The adapter for a GitHub-issues tracker: implements both seams of the
noni adapter interface (see [`../README.md`](../README.md)) for issues and
their comments.

## Question legitimacy

A steering question is an **issue comment with checkbox options**:

```
q1: Which release carries the new scheduler?
- [ ] next train
- [ ] after that
- [ ] drop it
```

The operator answers by ticking an option (editing the comment). The
adapter reads the comment **and its edit timeline** — the legitimacy rule
is about the *comment's last edit* and its actor, so the recorded payload
must carry the edit history, not just the final comment body:

- **`one`** — exactly one option ticked in the comment's last state, and
  the comment's last edit was made by an allow-listed account. The answer
  is that option's label.
- **`none`** — no option ticked.
- **`many`** — more than one option ticked (ambiguous — persisted as
  `status: open` with the answer written as `null`, never as an answer).
- **`stranger`** — the comment's last edit was made by an account not on
  the allow-list (a foreign edit voids the reply).

The last editor wins, not the first: an allow-listed account ticks an
option and a stranger later edits the same comment (re-ticking the same or
a different option) yields `stranger`; a stranger ticks first and an
allow-listed account later edits the comment (re-ticking the same option)
yields `one`.

## Label authorization

The seam is `label_authorization(payload, label, allowlist)`: the label
is an **explicit argument** — it is never inferred from the issue's
current label set. It answers from the timeline, not from the issue's
current label state. The label is **authorized** iff the allow-list is
active and the latest `labeled` event whose label name matches `label`
(casefolded) names an allow-listed actor. It reads the **account behind
the label event**, not the label's presence:

- the label's current presence on the issue does not matter: a label
  applied by an allow-listed account stays authorized if someone later
  removes it (the removal is a different event and does not re-attribute
  the application);
- a label applied by a stranger is **unauthorized** whether or not it is
  still present on the issue;
- a label with no recorded `labeled` event is unauthorized: without the
  event there is no evidence of an allow-listed applier;
- an empty or non-str `label` argument names nothing to authorize — it is
  unauthorized in **every** allow-list state (active, absent or refused),
  including an active allow-list; there is no "nothing to check, so True"
  path;
- an absent or refused allow-list authorizes nothing, no matter what the
  payload says;
- label names compare case-insensitively on both sides (the label
  argument and the label named in the event must name the same label).

An issue with several labels is not a special case: asking about any one
of them is decided by that label's own timeline events, not by the
first label on the issue.

## The allow-list

Never hard-coded. Sources, in precedence order:

1. the untracked file `.noni-adapter-allowlist` in the root of the repository
   noni is attached to — the one whose `noni/` state and issues the adapter is
   reading (in .gitignore, so it can never be committed);
2. the file named by the env var `NONI_ADAPTER_ALLOWLIST`.

The adapter is a pure function of (payload, allow-list) and resolves no working
directory of its own, so the caller passes the attached repository's root to
`default_allowlist_file(repo_root)`. With no usable root (none given, or a path
that is not a directory) there is no default candidate and only the env var can
supply a file; with neither source the allow-list is reported `absent` — it
never falls back to a wider default.

Format: one account per line; blank lines and `#` comments ignored. With
no local configuration the allow-list is empty and nothing is authorized
or legitimized.

## Offline / fixture-driven

Both seams are pure functions of (payload, allow-list). The adapter does
no I/O itself: the caller (a core script or an agent) fetches the tracker
JSON and passes it in. All tests run against the recorded JSON fixtures
under `tests/fixtures/gh-adapter/` — synthetic users and repos only, no
network.

## Running the census in this forge's CI

The generic step is the quickstart's [Run the census in
CI](../../docs/QUICKSTART.md#run-the-census-in-ci) section: one shell line, the
same for every CI system, and the exit-code sets are documented there. This
section is the copy for one forge. It is the only page in this repository that
names CI-system vocabulary, and no workflow file ships here: a team pastes the
step into their own pipeline.

The install is the quickstart's [Install](../../docs/QUICKSTART.md#install-noni)
step, so the clone and the `pip install` are linked rather than reprinted here.

Route A keeps its state in the repository the pipeline already checked out, so
the step is the census line on its own. The `runs-on:` line is the pipeline's own
choice of machine and is shown once, above the first step, so the fragment below
can be pasted under a `jobs:` and `steps:` mapping of your own:

```yaml
    runs-on: ubuntu-latest
  - name: Census
    run: |
      noni census --repo .
```

Route B keeps the direction in a private state repository. Clone it inside the
workspace first, because the census audits only the tree `--repo` names: with
the state clone as `--repo` the code repository's tracked files never enter the
run, and pointing the census at the workspace instead would report a clean verdict
for a state tree it never read.

```yaml
  - name: Census (private state repository)
    run: |
      git clone git@forge.example:you/your-project-direction.git .noni-state
      noni census --repo .noni-state
```

Gate the build on the census's own classes, split by default severity: fail on
10, 12, 15, 20, 30, 31, 32 and 51, and report without failing on 40, 41, 42, 43,
44, 45, 46 and 50. Run it without `--strict`: the hygiene class is inactive on a tree
with no deny-list, and a CI checkout has none, so the first run ends exit 0 with
the inactive row as its only finding. Under `--strict` that row alone would fail
the job, which is why `--strict` is the opt-in a team adds once the tree being
audited holds a deny-list with at least one usable entry: `.noni-scrub-denylist` at
its root (so `.noni-state/.noni-scrub-denylist` on Route B, where the state clone is
what `--repo` names), or the file `NONI_SCRUB_DENYLIST` points at.

## Usage

```python
import sys
sys.path.insert(0, "integrations")
sys.path.insert(0, "integrations/github-issues")
import adapter_protocol
import github_issues_adapter as adapter

assert adapter_protocol.check_interface(adapter) == []  # two seams present

allowlist = adapter_protocol.load_allowlist(
    adapter.ALLOWLIST_ENV_VAR,
    adapter.default_allowlist_file(attached_repo_root),  # Path of the attached repo
)
verdict = adapter.question_legitimacy(payload, allowlist)   # QuestionVerdict
ok = adapter.label_authorization(payload, "steer", allowlist)  # bool
```
