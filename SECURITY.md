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

## What helps

The command you ran, with its flags, the shape of the repository it ran in, and
what you expected against what happened. A failing test is welcome; a public
link to one is not.
