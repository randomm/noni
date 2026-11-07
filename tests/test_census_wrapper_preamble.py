"""The two shell census wrappers run one preamble, from one source.

The second arbiter was retired by making ``census.sh`` and
``census-sessions.sh`` thin wrappers over the unified census (issue #99). What
keeps them thin is that they are *the same script* apart from their names and
their groups: the interpreter lookup, the import probe and the exec are one
string in ``noni/wrapper_bash.py``, and these tests pin the shipped files to it.

That is the regression this file exists for. The two entry points disagreed
before precisely because each carried its own reading of the ledger: the census
gained a verdict, one script did not, and a team's CI chose its exit code by
which script it called (issue #97). A shared source plus an assertion is weaker
than a shared function and much stronger than a comment telling the next editor
to keep the two alike.
"""

from __future__ import annotations

import subprocess

from _harness import REPO, subprocess_env

from noni.wrapper_bash import preamble

LEDGER_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
SESSIONS_SH = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"

# The one difference the two scripts are allowed: their name, and the directory
# their usage line names. Everything above the shared body is comment and shebang.
_SCRIPTS = ((LEDGER_SH, "census.sh", "decisions", "census.py"),
            (SESSIONS_SH, "census-sessions.sh", "sessions", "census-sessions.py"))


def _body(path) -> str:
    """The script from ``set -u`` on: everything that runs, not the header."""
    text = path.read_text(encoding="utf-8")
    marker = "set -u\n"
    assert text.count(marker) == 1, (
        f"{path.name}: the shared body must start at exactly one `set -u`")
    return text[text.index(marker):]


def test_each_wrapper_carries_the_shared_preamble_verbatim():
    """Each shipped wrapper's running body is byte-for-byte ``preamble(...)``.

    Asserted against the generated text rather than against the other script: two
    files compared to each other can both be wrong, and the source of truth is the
    module the docs point a reader at.
    """
    for path, label, noun, script in _SCRIPTS:
        assert _body(path) == preamble(label, noun, script), (
            f"{path.name} no longer carries the shared preamble of "
            "noni/wrapper_bash.py verbatim: either the script drifted or the "
            "module changed without the script being regenerated")


def test_the_two_wrappers_differ_only_in_their_names_and_group():
    """Substituting one wrapper's label, noun and script into the other's body
    reproduces it exactly.

    The positive form of the assertion above, and the one that catches a fork: a
    line added to one script and not the other makes this fail even when both
    still match a module someone edited twice.
    """
    ledger_body = _body(LEDGER_SH)
    sessions_body = _body(SESSIONS_SH)
    assert ledger_body != sessions_body, (
        "the two wrappers are identical, so one of them lost its own usage line")
    derived = (sessions_body
               .replace("census-sessions.sh", "census.sh")
               .replace("census-sessions.py", "census.py")
               .replace("no sessions directory", "no decisions directory")
               .replace("noni/sessions", "noni/decisions"))
    assert derived == ledger_body, (
        "the two wrappers differ in more than their names and their directory:\n"
        f"--- derived from {SESSIONS_SH.name} ---\n{derived}\n"
        f"--- shipped {LEDGER_SH.name} ---\n{ledger_body}")


def test_neither_wrapper_names_jq():
    """Neither wrapper mentions ``jq``: not as a dependency, not as a comment.

    The word survives only where it describes what was removed (the docs, and
    the tests that prove the removal), never in a script a caller runs.
    """
    for path, _label, _noun, _script in _SCRIPTS:
        text = path.read_text(encoding="utf-8")
        assert "jq" not in text, (
            f"{path.name} still names jq, which the census does not use and the "
            f"wrapper must not depend on: {text}")


def test_a_wrapper_with_no_argument_refuses_with_the_usage_code():
    """Zero arguments is exit 2 with the wrapper's own usage line, on both paths.

    The one refusal the shared body makes that is not about its interpreter: a
    census of a directory nobody named would audit whatever ``noni/`` happened to
    sit beside the caller and print a clean nobody asked for.
    """
    for path, label, noun, _script in _SCRIPTS:
        proc = subprocess.run(["bash", str(path)], capture_output=True, text=True,
                              env=subprocess_env(), timeout=60)
        assert proc.returncode == 2, f"{label}: rc={proc.returncode} {proc.stderr}"
        assert label in proc.stderr, f"{label}: the refusal names nothing: {proc.stderr}"
        assert f"<state-root>/noni/{noun}" in proc.stderr, (
            f"{label}: the usage line does not say which directory to pass: "
            f"{proc.stderr}")
        assert proc.stdout == "", f"{label}: a refused run printed a report: {proc.stdout}"
