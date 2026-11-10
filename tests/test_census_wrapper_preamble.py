"""The shell census wrapper runs one preamble, from one source.

The second arbiter was retired by making ``census.sh`` a thin wrapper over the
unified census (issue #99). What keeps it thin is that its interpreter lookup,
its import probe and its exec are one string in ``noni/wrapper_bash.py``, and
these tests pin the shipped file to it.

That is the regression this file exists for. The entry points disagreed before
precisely because each carried its own reading of the ledger: the census gained a
verdict, one script did not, and a team's CI chose its exit code by which script
it called (issue #97). A shared source plus an assertion is weaker than a shared
function and much stronger than a comment telling the next editor to keep the
script in step.
"""

from __future__ import annotations

import subprocess

from _harness import REPO, subprocess_env

from noni.wrapper_bash import preamble

LEDGER_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

# The shipped wrapper and the three arguments that generate its running body.
_SCRIPTS = ((LEDGER_SH, "census.sh", "decisions", "census.py"),)


def _body(path) -> str:
    """The script from ``set -u`` on: everything that runs, not the header."""
    text = path.read_text(encoding="utf-8")
    marker = "set -u\n"
    assert text.count(marker) == 1, (
        f"{path.name}: the shared body must start at exactly one `set -u`")
    return text[text.index(marker):]


def test_each_wrapper_carries_the_shared_preamble_verbatim():
    """Each shipped wrapper's running body is byte-for-byte ``preamble(...)``.

    Asserted against the generated text rather than against another script: files
    compared to each other can both be wrong, and the source of truth is the
    module the docs point a reader at.
    """
    for path, label, noun, script in _SCRIPTS:
        assert _body(path) == preamble(label, noun, script), (
            f"{path.name} no longer carries the shared preamble of "
            "noni/wrapper_bash.py verbatim: either the script drifted or the "
            "module changed without the script being regenerated")


def test_the_wrapper_names_jq_nowhere():
    """The wrapper mentions ``jq`` nowhere: not as a dependency, not as a comment.

    The word survives only where it describes what was removed (the docs, and
    the tests that prove the removal), never in a script a caller runs.
    """
    for path, label, _noun, _script in _SCRIPTS:
        text = path.read_text(encoding="utf-8")
        assert "jq" not in text, (
            f"{label} still names jq, which the census does not use and the "
            f"wrapper must not depend on: {text}")


def test_a_wrapper_with_no_argument_refuses_with_the_usage_code():
    """Zero arguments is exit 2 with the wrapper's own usage line.

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
