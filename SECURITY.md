# Reporting a vulnerability

Report a security problem privately, through the **Report a vulnerability** form
on this repository's Security tab (GitHub private vulnerability reporting). The
report is visible to the maintainers and to nobody else until it is disclosed.

**Do not open a public issue, pull request or discussion for a security
problem.** A public report discloses the flaw to everyone before a fix exists.

## In scope

- The `noni` package: the console command and everything under `src/noni/`,
  including the git and file writes the writers make in your repository.
- The skill scripts under `skills/*/scripts/`, which are the wrappers an agent
  runs directly.
- The census, including its exit codes: a census that reports clean when the
  work has drifted, or that runs something it should not have read, is a
  security problem for this project, not a bug report.

## Out of scope

The repository's own CI, and any tool you run noni beside. If a finding needs
the tracker or the forge, report it to that service instead.

## What noni reads and runs

- State under the state root: `noni/decisions/*.json`, `noni/direction/order.json`,
  `noni/direction/intent.md`; files you name too: `--ledger`, `--ordering`,
  `--intent`, `--issue-state`, `--from`; the scrub deny-list `.noni-scrub-denylist`
  or `NONI_SCRUB_DENYLIST`, and the tracked `.noni-scrub-allowlist`.
- The public-hygiene check reads the content of every git-tracked file, not only
  `noni/`, size-capped; one it cannot read is a finding.
- No code looks for `.env`, `.netrc`, `.ssh/*` or `.git-credentials` by name (a
  tracked one is read only by the scan above), and none makes a network call.
- The only program it runs is `git`, always as `git -C <path>`, with hooks, external
  protocols and fsmonitor off and a time limit. Writer calls drop every `GIT_` name
  but identity, config-pin and transport; `HOME` and the rest pass through, so git
  reads its own config and helpers as usual, and census reads pin global and system
  config to null. The adapter under `integrations/` is outside this statement.

## What helps

The command you ran, with its flags, the shape of the repository it ran in, and
what you expected against what happened. A failing test is welcome; a public
link to one is not.
