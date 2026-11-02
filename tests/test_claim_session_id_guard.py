"""The session-id guard of the four writers, measured through claim.py's CLI.

Every session writer derives one name from ``--session-id`` before it reads,
writes or stages anything, and the derivation is one function
(``_session_git.writer_name``). claim.py is where that guard is measured, because
claim was the writer that had none: its comment beside the derivation said a
token guard ran "above", and nothing did, so the only thing between an id and a
committed path was the root judgement in ``relative_name`` -- a judgement about
the *name*, which cannot see an id whose name normalises back inside the root.
close.py and release.py already refused a bad id on this code and in this
wording; the pair below is what makes claim say the same thing, and what keeps
the wording shared rather than per-writer (see the same test pair in
``test_session_release.py`` and the name tables in
``test_session_name_contract.py``).

Both cases assert the state rather than the exit code alone: a refused run must
leave the bytes of the file it might have written exactly as it found them, and
must not have moved HEAD. That is the contract the #57 writer-honesty tests
established, and it is the one a message-only assertion cannot keep.
"""

from __future__ import annotations

from _harness import _git, run_claim
from claim_fixtures import (
    _git_text,
    _make_session,
    _session_body,
    _session_path,
)

# A claim that gets as far as the register is refused for a duplicate (exit 2) or
# a terminal session (exit 2), and the traversal cases below must reach the guard
# under test rather than one of those, so their victim file is a real register
# that carries a status no writer calls terminal and never a row for the task the
# run names.
_VICTIM_BODY = _session_body("someone-else")


def test_claim_refuses_a_session_id_with_whitespace(tmp_path):
    """A --session-id with embedded whitespace is a usage error (exit 4), said in
    the same wording close and release use for a bad --session-id.

    The three writers that name a session all refuse it the same way now, and the
    row grammar is the reason: a claim row is one line, and an id carrying a space
    is not the name of one file under ``noni/sessions/``. A tab is in the set
    because the writers strip before they validate, so only a *non*-stripping
    whitespace character can tell the guard from the strip: one that survives it
    must still be refused.
    """
    repo = _make_session(tmp_path)
    body_before = _session_path(repo).read_text(encoding="utf-8")

    for bad in ("a b", "   ", "a\tb", "2026-10-01 aaaaaa", "2026-10-01-aaaaaa b"):
        proc = run_claim(repo, bad, "#42")
        assert proc.returncode == 4, (
            f"--session-id {bad!r}: expected exit 4, got {proc.returncode}: "
            f"{proc.stderr}")
        assert "session" in proc.stderr.lower(), proc.stderr
        # The value is quoted with !r, so a control character appears escaped --
        # compare the rendered form rather than the raw one.
        assert repr(bad) in proc.stderr, f"the refusal must name the value: {proc.stderr}"

    # A usage refusal lands before any write: the register is byte-identical.
    assert _session_path(repo).read_text(encoding="utf-8") == body_before
    assert _git_text(repo, "status", "--porcelain") == "", "a refused run dirtied the tree"


def test_claim_refuses_a_session_id_that_walks_out_of_the_sessions_directory(tmp_path):
    """The traversal the id-level guard exists for, measured on committed bytes.

    ``sub/../../../victim`` is one token and carries no separator: a check for
    "no whitespace, no slash" admits it, and the name built from it
    (``noni/sessions/sub/../../../victim.md``) normalises to ``victim.md`` -- a
    file at the state root the writer was never pointed at. The root judgement
    alone cannot see this, because it is a judgement about the name and the
    normalised name is inside the root.

    So the assertion is the state, not the message: a ``victim.md`` committed at
    the root is byte-identical afterwards, the run exits with claim's usage code,
    and HEAD has not moved. Remove the id guard in ``_session_git.writer_name``
    (let any token through) and this run appends its claim row to ``victim.md``
    and commits it: the bytes and HEAD both move and the test goes red.
    """
    repo = _make_session(tmp_path)
    victim = repo / "noni" / "sessions" / "victim.md"
    victim.write_text(_VICTIM_BODY, encoding="utf-8")
    _git(repo, "add", "noni/sessions/victim.md")
    _git(repo, "commit", "-q", "-m", "the victim file")
    victim_before = victim.read_bytes()
    head_before = _git_text(repo, "rev-parse", "HEAD").strip()

    for bad in ("sub/../../../victim", "noni/sessions/../../../victim"):
        proc = run_claim(repo, bad, "#42")
        assert proc.returncode == 4, (
            f"--session-id {bad!r}: expected the usage code, got "
            f"{proc.returncode}: {proc.stderr}")
        assert "session" in proc.stderr.lower(), proc.stderr

    # Nothing was read from or written to the file the traversal names, and the
    # clone holds no commit this run made.
    assert victim.read_bytes() == victim_before, (
        "a traversal --session-id wrote the committed file at the state root")
    assert _git_text(repo, "rev-parse", "HEAD").strip() == head_before, (
        "a refused run committed into the state root")
    assert _git_text(repo, "status", "--porcelain") == "", "a refused run left dirt"
    assert _git_text(repo, "diff", "--cached", "--name-only").split() == [], (
        "a refused run staged a path")
