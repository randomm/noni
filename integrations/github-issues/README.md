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
is about the *last edit that ticked the answer*, so the recorded payload
must carry the edit history, not just the final comment body:

- **`one`** — exactly one option ticked, and the last edit that ticked it
  was made by an allow-listed account. The answer is that option's label.
- **`none`** — no option ticked.
- **`many`** — more than one option ticked (ambiguous — persisted as
  `status: open` with no answer, never as an answer).
- **`stranger`** — the last edit that ticked an option was made by an
  account not on the allow-list (a foreign edit voids the reply).

The last ticker wins, not the first: an allow-listed account ticks an
option and a stranger later edits the same comment (re-ticking the same or
a different option) yields `stranger`; a stranger ticks first and an
allow-listed account later re-ticks the same option yields `one`.

## Label authorization

The adapter reads the **account behind the label event**, not the label's
presence. For every label present on the issue it looks up the issue's
timeline for the label's (latest) `labeled` event:

- the label is **authorized** iff that event's actor is on the allow-list;
- a label present on the issue but applied by a stranger is
  **unauthorized** (the presence is not the evidence — the application
  event is);
- a label applied by an allow-listed account stays authorized if someone
  later removes it: the removal is a different event and does not
  re-attribute the application;
- a label present on the issue with no recorded `labeled` event is
  unauthorized: without the event there is no evidence of an allow-listed
  applier.

## The allow-list

Never hard-coded. Sources, in precedence order:

1. the untracked file `.noni-adapter-allowlist` in the repository root
   (in .gitignore, so it can never be committed);
2. the file named by the env var `NONI_ADAPTER_ALLOWLIST`.

Format: one account per line; blank lines and `#` comments ignored. With
no local configuration the allow-list is empty and nothing is authorized
or legitimized.

## Offline / fixture-driven

Both seams are pure functions of (payload, allow-list). The adapter does
no I/O itself: the caller (a core script or an agent) fetches the tracker
JSON and passes it in. All tests run against the recorded JSON fixtures
under `tests/fixtures/gh-adapter/` — synthetic users and repos only, no
network.

## Usage

```python
import sys
sys.path.insert(0, "integrations")
sys.path.insert(0, "integrations/github-issues")
import adapter_protocol
import github_issues_adapter as adapter

assert adapter_protocol.check_interface(adapter) == []  # two seams present

allowlist = adapter.load_allowlist(
    adapter.ALLOWLIST_ENV_VAR, adapter.default_allowlist_file()
)
verdict = adapter.question_legitimacy(payload, allowlist)   # QuestionVerdict
ok = adapter.label_authorization(payload, allowlist)        # bool
```
