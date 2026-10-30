# AGENTS.md

## Operator choices

- **Gate files:** `AGENTS.md`, `.github/workflows/`, `pyproject.toml`, `scripts/public_safety.py`, `.pi/`.
- **Merge authority:** Agents may squash-merge a pull request into `main` only when all of these hold:
  - CI is green on the PR's current head commit.
  - The PR is not a draft.
  - The adversarial and lens reviews have passed at that same head commit with no open CRITICAL or HIGH findings.
  - The PR does not change the **Merge authority** or **Review blocking level** bullets in Operator choices. Changes to those need the operator's merge.
  - The PR does not delete or weaken an existing test assertion, unless all of these hold:
    - the operator ordered that change in their own words in a comment on the linked issue (a comment written by the operator, not a decision an agent posted on their behalf);
    - the PR body links that comment, quotes it, and lists each deleted or weakened assertion;
    - the merging agent re-reads the comment on the tracker immediately before merging. If it cannot be read, the exception does not apply.

    Otherwise it needs the operator's merge.

  The governing rule is the AGENTS.md on `main`, not the copy in the PR branch. CI and both reviews must be at the PR's current head commit. Any new push needs CI and both reviews again. CI red, pending or missing means no merge. The agent re-checks every condition immediately before merging. Agents never push to `main` directly and never force-push.
- **Review blocking level:** Review findings are blocking at HIGH severity and above.
- **Project-specific constraints:** Purity rule is binding: core carries no project content and no vocabulary from any specific driver, tracker or project; adapters only under integrations/. docs/PRODUCT.md sections 3, 6 and 7 are binding for all epics.
- **Public-repo hygiene:** noni is published as a public repository. No tracked file may contain personal information about the operator (names, employer names, hostnames or network details), machine-local absolute home paths, names or paths of other projects, tools, drivers or repositories outside noni, or secrets or credentials. Use generic wording instead ("a driver", "an issue runner", "a tracker", "a separate repository"). The rule itself names no banned project or tool.


## Code Style

- Purity rule: repo holds only generic product content (positioning, research, design, specs, shipped skills): no tickets, backlog entries, or any attached project's content
- Two-tier purity: core skills carry neither project content nor vocabulary from any specific driver, tracker or project; adapters live under `integrations/` (one clearly-marked adapter directory per project, e.g. `integrations/github-issues/`); core must be viable with no adapter installed
- SKILL.md is the unit of product; state lives outside the skill directory; core skills stay within the six Agent Skills spec frontmatter fields
- Git + plain files are the only truth: no daemons, no databases; scripts only where atomicity and exit-code honesty demand them
- Prose is convention, not enforcement: every invariant needs a script with an honest exit code or a census check
- Steering never auto-answers for the operator; multiple-choice answers name the question id they answer

## Architecture Notes

- Attached project's `noni/` dir: direction/ (standing direction, release trains), decisions/ (steering ledger, one file per dated record), sessions/ (one committed file per session, single writer)
- Census is the arbiter: claims are committed signals, not locks; double-claim detection happens at read time via the census
- Metrics are derived from git history plus noni/ files, never self-reported
- the primary integration is a specific driver/tracker ecosystem (adapters map onto its mechanisms); live transports are caches over git-committed state, never the state
- GitHub issues remain the work carrier; noni owns only the direction layer above them
- Epic map: E1 steering ledger (#1), E2 sessions+claims (#2), E3 census (#3), E4 adapters (#4), E5 measurement/eval (#5)
- Docs-only at v0: README.md + docs/PRODUCT.md; evidence briefs live outside the repo, in a local working tree the operator holds separately

# Minimalist Engineering

Every line of code is a liability. Before creating anything:

- **Is this explicitly required** by the GitHub issue?
- **Can existing code/tools** solve this instead?
- **What's the SIMPLEST** way to meet the requirement?
- **Am I building for hypothetical** future needs?

If you cannot justify necessity, DO NOT CREATE IT.

# Git Workflow

## Conventional commits

```
<type>(<scope>): <description>
```

Types: `feat` | `fix` | `refactor` | `docs` | `test` | `chore`

## Branch naming

```
feature/issue-{N}-brief-description
```

## Branch protection

- ❌ NO direct commits to `main`
- ✅ All work on feature branches → PR
- ✅ PRs squash-merged

# Documentation Policy

## The 200-PR test

Before adding documentation: *"Will this be true in 200 PRs?"*

- **YES** (enduring principle) → Document the principle (WHY)
- **NO** (implementation detail) → Skip, or use code comments (WHAT/HOW)

## Forbidden documentation

- ❌ Issue drafts, implementation summaries, fix notes, scratch files
- ❌ `TODO` comments: create GitHub issues instead

# Issue-Driven Development

## Before starting

1. GitHub issue exists for the work
2. Issue clearly describes the requirement
3. Your approach matches issue scope exactly
4. No scope expansion without updating the issue

## Linking

Link PRs to issues via `Closes #N` in the PR body. Use the issue number
in the branch name, never in the commit scope.

# Code Review Doctrine

## Quality gates (blocking)

All checks must pass locally before push:

- [ ] Tests passing (0 failures): `pytest`
- [ ] Coverage meets threshold: `coverage run -m pytest`, `coverage combine`, `coverage report`
- [ ] Linting passing (0 errors): `ruff check .`
- [ ] Source files within the line limits: `pytest tests/test_file_size_limit.py`

No type checker runs in this project, in CI or locally, so there is no type
checking gate to tick. If one is ever added, it goes here and into CI together.

## Suppressions

One rule per suppression, with the reason on the same line:
`# noqa: E402  (src/ goes on sys.path just above)`. An unused suppression is a
failure: ruff's RUF100 is enabled in `pyproject.toml`, so a `# noqa` that
stopped suppressing anything must be deleted rather than left in place.

# Context7 Protocol

Before writing ANY code, check Context7 for current documentation:
- Library APIs and syntax
- Framework patterns and best practices
- Configuration options

Training data is often months out of date. Context7 provides
authoritative, up-to-date docs. Skip it for the project's own code
standard-library features, or meta-questions about the project.

# Testing Standards

- TDD preferred: write the failing test first, then the minimal
  implementation that passes it; refactor with the tests green.
- Coverage threshold: **≥80%** for new code.
- Coverage for lower-risk areas (documentation, config, formatting)
  may be lower; the threshold is the floor for logic, not a target for
  boilerplate.
- A bug fix ships with its regression test. A fix without a test that
  failed first is an incomplete fix.

## Environment

- Manifest: `pyproject.toml`
- Language: `python`
- CI workflows: `.github/workflows/ci.yml`


## Commands

| kind | command |
| --- | --- |
| test | `pytest` |
| lint | `ruff check .` |
| size | `pytest tests/test_file_size_limit.py` |


## Quality Gates

Run these before pushing. These are the commands CI runs (see
`.github/workflows/ci.yml`: lint, then the suite under coverage), plus the size
test. All must pass locally:

- **pytest**: `pytest`
- **coverage gate**: `coverage run -m pytest`, then `coverage combine`, then `coverage report`
- **ruff**: `ruff check .`
- **file size**: `pytest tests/test_file_size_limit.py`

## Project conventions

These are working conventions. The checks that enforce rules are the ones under Quality Gates. A convention without a check is guidance.

- No ALL_CAPS scratch files (PLAN.md, DESIGN.md, NOTES.md, RESEARCH.md, TODO.md and the like). The issue thread holds plans and notes.
- Docs change in the same PR as the behaviour they describe. Never leave the repo claiming something that is not true.
- Prose in docs, comments, commit messages and PR text is plain and direct: short sentences, no em dashes, no hype. Comments explain why, not what; leave a comment out if the code already says it.
- Source file size: every tracked source file is at or under 500 lines, and every `SKILL.md` at or under 400. Tracked source means a `.py` file, a `.sh` file, a workflow YAML under `.github/workflows/`, and any tracked file whose first line is a shebang; suffixes match without regard to case, so `.PY` counts. A tracked path missing from the working tree is an offender, not a skip; a tracked symlink is skipped, because its target is measured itself if it is tracked. Markdown other than `SKILL.md`, JSON and data files are exempt. No exceptions, no grandfathering, no override flag: split the file along a natural seam. Enforced by `tests/test_file_size_limit.py`.
- Never commit secrets or tokens, `.env` files, raw model output, scratch files, or local research artifacts.
- Scope discipline: change only the files the issue covers (check `git diff --name-only origin/main...HEAD` before opening a PR). A bug found along the way gets its own issue and a note in the PR.
- Tests are offline and deterministic: no network, no real accounts; use fixtures and stubs.
- Fail closed: a missing or malformed setting stops the command with a clear message; never fall back to something wider.
- Scratch work goes in one ignored folder per issue (`tmp/issue-N/`), never in the tree root or a tracked directory.
- Commit subjects are at most 72 characters.
- Run any command that can hang under a time limit (`timeout 1500 pytest`, and a `timeout=` on a subprocess a test launches).
- Dependencies come from the public package registry only: no vendored copies, no private index, no git URL.
- Never run `git config` against this repository or a worktree of it. Tests that need git settings use a throwaway repo under `tmp_path`.
- Work cycles do not edit their own gates: a gate file (see Gate files) is changed by people (or by the agents-md tool on the operator's request), not by a work cycle. The governing copy of these rules is the one on `main`, and a PR that changes a gate file needs the operator's merge (see Merge authority).

