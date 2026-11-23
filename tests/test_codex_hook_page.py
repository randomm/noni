"""The prose of the Codex hook page, checked where a reader would look for it.

Split out of ``test_codex_hook.py``, which keeps the checks over the snippet's
bytes: the shape of the config, both argvs, and the two bounds a handler carries.
What lives here is the other half of the same page: the sentences a reader needs
before pasting it, and the commands that page then tells them to run by hand.

The split is the pi suite's, for the same reason (see
``test_pi_extension_failure_line.py``): the page has two kinds of claim, and a
check over a sentence and a check over a JSON key fail for different reasons.

- :func:`test_the_page_names_the_trust_gates_the_state_root_and_the_path_rule`
  drives the ``(literal, reason)`` pairs of :data:`PAGE_RULES` over the flowed page,
  then reads each section on its own, so a clause that wandered out of the heading
  a reader would look under is caught rather than satisfied from elsewhere.
- :func:`test_the_verifying_fence_is_the_command_the_page_ships` reads the fence
  under "Verifying it" through :func:`codex_hook_source.verify_commands`, so the
  command the reader runs by hand and the command the snippet registers are the same
  bytes and cannot drift apart.
- :func:`test_the_page_never_names_the_deprecated_feature_key` and
  :func:`test_the_page_has_no_em_dash` are the two prohibitions the page carries.
"""

from __future__ import annotations

import shlex

from _harness import REPO
from codex_hook_source import (
    BRIEF_COMMAND,
    BRIEF_VERIFY_COMMAND,
    EM_DASH,
    EMPTY_STATE_ROOT_SIGNALS,
    HOOK_FILES,
    INSTALL_TARGET,
    LIMIT_SECTION_HEADING,
    PAGE_RULES,
    PATH_VERIFY_COMMANDS,
    page,
    verify_commands,
)
from docs_promises import section_body
from pi_extension_source import string_literal
from quickstart_page import flowed_text


def _reminder() -> str:
    """The reminder, read through the pi source reader rather than restated.

    The two adapter pages owe the operator the same sentence, and each would stay
    green on its own while telling them something different about what noni holds.
    """
    return string_literal(
        (REPO / "integrations" / "pi" / "noni.ts").read_text(encoding="utf-8"),
        "REMINDER")


def _section(title: str) -> str:
    """One ``##`` section of the page, so a claim is checked where it belongs.

    A fact that only has to appear somewhere on the page can be satisfied by a
    sentence in the wrong place: a reader looking for the trust step under Install
    would still have to guess. So the gates, the state-root rule and the verification
    steps are each located under their own heading, and a clause that wandered into
    another section is a failure rather than a silent pass.
    """
    return section_body(page(), title)


def _flowed(title: str) -> str:
    """One section of the page with its line wrapping collapsed."""
    return flowed_text(_section(title))


def _status_gate(section: str) -> bool:
    """Whether the section names how to check a hook's status.

    The bare token ``/hooks`` is carried by the filename ``.codex/hooks.json`` as
    much as by the command that opens the hook browser, so the reader that pins this
    fact cannot settle for the token somewhere in the section: it has to be the
    command, quoted as the page writes it, or the words that name the browser.
    """
    return any(token in section for token in ("`/hooks`", "hooks browser",
                                              "hook browser"))


def test_the_page_names_the_trust_gates_the_state_root_and_the_path_rule() -> None:
    """What a reader needs from the page, and nothing the snippet does not do.

    Both gates a hook has to clear are named apart: the project has to be trusted and
    the definition has to be reviewed and trusted, and a reader who satisfies only one
    of them gets a hook that is skipped with no brief and no reminder, which reads
    exactly like a hook that was never written. Each sits under the heading a reader
    would look under, so a clause that wandered off into another section is caught.
    """
    text = page()
    flowed = flowed_text(text)
    for wanted, why in PAGE_RULES:
        assert wanted in text or wanted in flowed, why
    install = _flowed("Install")
    for clause, why in (("project has to be trusted",
                         "Install does not name the project trust gate"),
                        ("reviewed and trusted",
                         "Install does not name the hook review gate"),
                        ("skipped: no brief and no reminder",
                         "Install does not say what a skipped hook leaves the session"),
                        (INSTALL_TARGET,
                         "Install does not name where the snippet is copied")):
        assert clause in install, why
    assert _status_gate(install), (
        "Install does not name where to check a hook's status")
    # The page's check tells the reader what a wrong state root looks like. `noni
    # brief` exits 0 for any directory that exists -- the only state-root refusal it
    # has is for a --repo that is no directory at all -- so a page that pointed the
    # reader at the exit code would leave them trusting a wiring that briefs the
    # model on nothing, the failure this adapter exists to close.
    verifying = _flowed("Verifying it")
    for clause, why in ((BRIEF_COMMAND,
                         "Verifying it does not print the command to run by hand"),
                        ("still exits 0",
                         "Verifying it still claims an exit code where the tool gives "
                         "one, or does not tell the reader what a state root holding "
                         "no noni/ actually prints"),
                        ("command -v noni",
                         "Verifying it does not print the command that names which "
                         "`noni` the hook execs"),
                        ("noni --version",
                         "Verifying it does not print the command that names the "
                         "version that binary carries")):
        assert clause in verifying, why
    for signal in EMPTY_STATE_ROOT_SIGNALS:
        assert signal in verifying, (
            f"Verifying it does not name {signal!r}, what the brief prints for a "
            "state root that holds no direction")
    assert _status_gate(verifying), (
        "Verifying it gives no way to check whether the hook ran")
    root = _flowed("Which state root it reads")
    for clause, why in (("first on PATH",
                         "the state-root section does not say which `noni` runs"),
                        ("command -v noni",
                         "the state-root section names no way to check the resolved "
                         "install"),
                        ("noni --version",
                         "the state-root section names no version to check it against"),
                        ("docs/QUICKSTART.md#install-noni",
                         "the state-root section drops the quickstart's Install link"),
                        ("git rev-parse --show-toplevel",
                         "the state-root section does not name the git-root anchor"),
                        ("NONI_STATE_ROOT",
                         "the state-root section does not say why this hook has no "
                         "env-var rung where the pi hook has one"),
                        (_reminder(),
                         "the state-root section no longer carries the reminder the "
                         "per-turn hook prints")):
        assert clause in root or clause in install or clause in verifying, why
    assert "bounded" in _flowed(LIMIT_SECTION_HEADING), (
        "the page no longer argues the brief is a bounded payload")


def test_the_verifying_fence_is_the_command_the_page_ships() -> None:
    """The command the reader runs by hand is the command the snippet registers.

    The reader's check is only a check while it is the same command: a page that
    changed the fence under "Verifying it" and not the snippet would leave a reader
    verifying a wiring they do not have, and both halves would stay green if each
    were compared against its own copy. :func:`verify_commands` reads the fence from
    the page, so the two are pinned to the same bytes.
    """
    commands = verify_commands(page())
    briefs = [argv for argv in commands if argv[1:3] == ["brief", "--repo"]]
    assert len(briefs) == 1, f"the page prints {len(briefs)} brief commands to run"
    assert shlex.split(BRIEF_COMMAND) == briefs[0], (
        f"the command to run by hand is not the snippet's: {briefs[0]}")
    for command in PATH_VERIFY_COMMANDS:
        argv = shlex.split(command)
        assert argv in commands, f"the page's fence does not print {command}"
    assert shlex.split(BRIEF_VERIFY_COMMAND) == briefs[0], (
        "the command the helper names and the command the page prints disagree")


def test_the_page_never_names_the_deprecated_feature_key() -> None:
    """Codex still parses the old key as an alias, which is exactly why printing it
    here would be a slow leak: a page that names it teaches a reader a spelling the
    harness is on its way to dropping.
    """
    assert "codex_hooks" not in page(), "the page names the deprecated feature key"


def test_the_page_has_no_em_dash() -> None:
    """The repo's plain-prose convention, gated for the adapter page itself."""
    for path in HOOK_FILES:
        assert path.is_file(), f"{path} is missing"
        assert EM_DASH not in path.read_text(encoding="utf-8"), f"{path.name} has one"
