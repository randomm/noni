# Integrations (adapters)

Adapters are the only place where noni meets a specific tracker or tool.
They sit here, under `integrations/`, one clearly-marked directory per
tool, and they are the **only** files in the repository that may carry the
vocabulary of a specific driver, tracker or tool. Everything else (the
skills under `skills/`, the docs, the scrub) stays pure.

## The two-tier purity rule

- **Core** (`skills/`, `scripts/`, `docs/`) carries neither project content
  nor vocabulary from any specific driver, tracker or project. The core
  must remain viable with **no adapter installed**: nothing under `skills/`
  or `scripts/` imports, invokes or otherwise depends on anything under
  `integrations/`.
- **Adapters** (here) may name the tool they adapt. They are optional
  extras: deleting this entire directory changes nothing about the core's
  behaviour, its exit codes, or its test suite.

## The adapter interface

An adapter is a plain Python module (no package, no `__init__.py` — the
same `sys.path` insertion pattern every other noni script uses) that
implements exactly **two seams**:

1. **Question legitimacy** — given the tracker-side representation of a
   steering question, return the operator's answer and a verdict. The
   verdict is one of `none` | `one` | `many` | `stranger`. A `many` or
   `stranger` verdict is never stored as an answer; the caller persists
   such a steer as `status: open` with the answer absent.
2. **Label authorization** — given a label on an issue, return whether the
   **account that applied the label** is on the allow-list. It reads the
   account behind the label event, not the label's presence: a label
   applied by a stranger is unauthorized even if it is present on the
   issue, and a label applied by an allow-listed account stays authorized
   if someone later removes it.

The contract is documented and enforced by `test_adapter_interface.py`;
any module that implements both seams satisfies the interface. There is no
base class and no import from the core: the contract is small enough that
a docstring plus a test is the whole enforcement (the product rule: prose
is convention, the test is the check).

## The allow-list

Adapters take their allow-list of trusted accounts from **local
configuration only — never hard-coded**. For the GitHub-issues adapter the
sources, in precedence order, are:

1. the untracked file `.noni-adapter-allowlist` in the repository root
   (one account per line; blank lines and `#` comments ignored);
2. the untracked file named by the env var `NONI_ADAPTER_ALLOWLIST`.

When neither exists the adapter refuses to authorize anything (an empty
allow-list authorizes no account) and reports that clearly. The allow-list
file is git-ignored, like the scrub's deny-list: it is local operator
configuration and can never be committed.

## Existing adapters

- [`github-issues/`](github-issues/) — the GitHub-issues adapter:
  steering question as an issue comment with checkbox options; label
  authorization from the issue's label timeline. Fixture-driven, offline.

Adapters for any other tool live outside this repository and implement the
same two seams.
