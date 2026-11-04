"""The quickstart's commands, as a literal list, in the order the page prints them.

This module *is* the harness's threat model. The page under test is
``docs/QUICKSTART.md``, a file this repository writes, reviews and owns, so the
question the launcher asks is not "what if this page were hostile" but "does the
page still print the commands we reviewed, in this order, per section". The answer
is a comparison against the lists below: parsed argv, token for token, against the
literal text in this file.

Consequences of that one decision, all load-bearing:

- **A page change must come here.** Any command the page gains, drops, reorders or
  reworded fails the golden comparison, so the review of a documentation change is
  a review of the list in this file. That is the human gate the previous harness
  tried to approximate with a push guard, a ``git config`` grammar and an
  allow-list of launchable words, all of which defended against a page nobody was
  writing.
- **Nothing runs that is not in a list below.** The launcher takes its argv from
  the same parse that the golden comparison checks, and the comparison runs first
  in every walk (see :mod:`quickstart_runner`). There is no vocabulary to keep
  current, because a command outside these lists never reaches an ``exec``.
- **Placeholders stay literal tokens here.** ``<record-id>`` and ``<session-id>``
  are what the page prints, so they are what the golden list carries; the values a
  reader (or a running tree) supplies are a plain mapping in
  :mod:`quickstart_runner`. Likewise the OWNER URL, the forge remote and the
  reader's own directory are printed exactly as the page spells them.

The install and recipe sections are listed too, because a reader copies them and
the suite must notice a change in them. Two of these commands are not *launched*:
the ``git clone`` of the OWNER URL and the ``python3 -m pip install ./noni`` that
follows it stand for the fixture's materialised clone and its venv install (see
:func:`quickstart_topology.build_installed_world`), and the ``gh issue list`` recipe is run
by ``jq`` over a planted payload rather than by ``gh``
(:func:`quickstart_runner.recipe_gh_argv`). The comparison is over all of them;
only the launching chooses.
"""

from __future__ import annotations

# The sections the golden list covers, keyed by the prefix of the ``##`` heading
# that owns them, in the order the page prints them. The key is what
# ``docs_promises.section_body`` selects by, so a block moved under a different
# heading is a golden failure rather than a silent re-scoping.
INSTALL: tuple[str, ...] = ("Install",)
ROUTE_A: tuple[str, ...] = ("Route A",)
ROUTE_B: tuple[str, ...] = ("Route B",)
CI: tuple[str, ...] = ("Run the census in CI",)
DENYLIST: tuple[str, ...] = ("The deny-list",)
ISSUE_STATE: tuple[str, ...] = ("The --issue-state",)

# The commands of each section as the page prints them, parsed by
# ``docs_commands.block_commands``: line continuations joined, shell quoting
# removed, the page's own ``#`` prose lines dropped.
#
# The route headings each open with ``cd your-project``: the page names a
# directory it cannot know, so the launcher asserts that line and does not run it
# (every launched command already carries the scratch tree as its cwd).
GOLDEN: dict[tuple[str, ...], list[list[str]]] = {
    INSTALL: [
        ["git", "clone", "https://github.com/OWNER/noni", "noni"],
        ["python3", "-m", "pip", "install", "./noni"],
    ],
    ROUTE_A: [
        ["cd", "your-project"],
        ["git", "config", "user.name", "Casey"],
        ["git", "config", "user.email", "casey@example.invalid"],
        ["noni", "decide", "--repo", ".",
         "--slug", "release-scope", "--scope", "release", "--asked-by", "team-lead",
         "--question", "q1=Ship the beta this week?",
         "--option", "q1=Ship it", "--option", "q1=Wait a week",
         "--answer", "q1=Wait a week"],
        ["noni", "census", "--repo", "."],
    ],
    ROUTE_B: [
        ["cd", "your-project"],
        ["git", "clone", "git@forge.example:you/your-project-direction.git",
         ".noni-state"],
        ["echo", "/.noni-state/", ">>", ".gitignore"],
        ["git", "-C", ".noni-state", "config", "user.name", "Casey"],
        ["git", "-C", ".noni-state", "config", "user.email", "casey@example.invalid"],
        ["git", "-C", ".noni-state", "commit", "--allow-empty", "-m",
         "direction: first commit"],
        ["noni", "decide", "--repo", ".noni-state",
         "--slug", "release-scope", "--scope", "release", "--asked-by", "team-lead",
         "--question", "q1=Ship the beta this week?",
         "--option", "q1=Ship it", "--option", "q1=Wait a week",
         "--answer", "q1=Wait a week"],
        ["noni", "order", "--repo", ".noni-state", "add", "12", "--decision",
         "<record-id>"],
        ["noni", "census", "--repo", ".noni-state"],
        ["noni", "register", "--repo", ".noni-state", "--identity", "developer"],
        ["noni", "claim", "--repo", ".noni-state", "--session-id", "<session-id>",
         "--task", "#12"],
        ["git", "-C", ".noni-state", "push", "-u", "origin", "main"],
    ],
    # The CI section prints one census line per route and nothing else: the
    # install lines are linked, not reprinted, so the page carries one copy of
    # them and the review of a step that gates a build stays this pair of lines.
    CI: [
        ["noni", "census", "--repo", "."],
        ["noni", "census", "--repo", ".noni-state"],
    ],
    DENYLIST: [
        ["python", "scripts/public_safety.py"],
    ],
    ISSUE_STATE: [
        ["gh", "issue", "list", "--json", "number,state", "--jq",
         "map({key: (.number | tostring), value: (.state | ascii_downcase)})"
         " | from_entries",
         ">", "issue-state.json"],
        ["noni", "census", "--repo", ".", "--issue-state", "issue-state.json"],
    ],
}

# Every section the golden list claims to cover. A page section that gained a bash
# fence appears in neither key nor fence list, so the census of fences in
# ``test_quickstart.py`` compares this tuple against the page rather than trusting
# the walk to have chosen well.
COVERED_SECTIONS: tuple[tuple[str, ...], ...] = (
    INSTALL, ROUTE_B, ROUTE_A, CI, DENYLIST, ISSUE_STATE,
)
