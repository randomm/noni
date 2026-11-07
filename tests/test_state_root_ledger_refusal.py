"""The ledger sentence a writer prints when the tree holds no ledger (issue #120).

Split from ``tests/test_state_root_refusal.py``, which holds the entry points' exit
codes and the creator exception. This half is the answer the two admitted creators --
``order add`` and ``intent set`` -- still give on a code repository: they cannot be
refused at the state root, because their first write is what creates
``noni/direction``, so the ledger's own refusal has to carry the second fact (this
tree holds no ``noni/``) rather than leave the caller reading "no decision record is
in the ledger" about a repository that holds no ledger. The other half of the claim
matters as much: on a tree that DOES hold ``noni/`` the same refusal must stay the
plain sentence it always was, or the run reads as a wrong ``--repo`` to a caller who
named the right one.
"""

from __future__ import annotations

from _harness import INTENT, ORDER
from test_state_root_refusal import (
    _INTENT_DRAFT,
    NOT_A_STATE_ROOT_WORDS,
    _code_repo,
    _launch_against,
)


def test_order_add_on_a_tree_with_no_ledger_is_refused_by_the_ledger_not_the_state_root(
        tmp_path):
    """``add`` is admitted to the state-root question and still refused for the ledger.

    The two refusals must stay distinguishable: ``add`` creates ``noni/direction`` for
    its first entry, so it is admitted past the state-root question, but a tree with no
    decision record is a refusal of its own at exit 4. Collapsing them (by refusing
    ``add`` at the state root, or by letting a recordless tree write an entry) would
    break one half of this pair.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "add-no-ledger")
    proc = _launch_against(ORDER, repo, cwd, "add", "7", "--decision",
                           "2026-10-01-absent", "--now", "2026-10-02T00:00:00Z",
                           "--no-commit")
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "is in the ledger" in proc.stderr, proc.stderr
    assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, (
        f"add is the sanctioned creator and must not meet the state-root refusal: "
        f"{proc.stderr}")


def test_intent_set_is_admitted_on_a_pure_code_repo_and_refused_for_the_ledger(
        tmp_path):
    """`intent set` on a tree holding no noni/ reaches the citation, not the refusal.

    `set` is the sanctioned creator, so on a tree holding nothing of noni's it must
    be admitted past the state-root question -- the tree it is about to write is the
    point -- and then refused at exit 4 because the record it cites does not exist.
    That ordering matters: refusing `set` here would break the first intent file, and
    admitting it all the way would let a wrong --repo invent an intent. A draft the
    validator refuses is used so the exit code below can only come from the citation,
    never from the draft.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "intent-pure")
    bad_draft = tmp_path / "bad-draft.md"
    bad_draft.write_text("not an intent file at all\n", encoding="utf-8")
    proc = _launch_against(INTENT, repo, cwd, "set", "--from", str(bad_draft),
                           "--decision", "2026-10-01-absent",
                           "--now", "2026-10-02T00:00:00Z")
    assert proc.returncode == 4, (
        f"set is the sanctioned creator: expected the ledger's exit 4, got "
        f"{proc.returncode}: {proc.stderr}")
    assert NOT_A_STATE_ROOT_WORDS[0] not in proc.stderr, (
        f"a creator must not meet the state-root refusal: {proc.stderr}")
    assert not (repo / "noni").exists(), (
        f"a refused run created {repo / 'noni'}")


def test_a_writer_on_a_code_repo_names_the_state_root_it_found(tmp_path):
    """The issue's reproduction: the ledger refusal says the tree holds no noni/.

    ``order add`` and ``intent set`` are admitted past the state-root guard because
    their first write creates ``noni/direction``, so the sentence the ticket quotes is
    still the answer these two runs get. That is survivable only if the sentence tells
    the whole truth: a caller who pointed at the code repository instead of the state
    clone must learn that from the run, not from the absence of a record they were sure
    they had. Both verbs are checked, on the tree the pilot used.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "citation-names-state")
    draft = tmp_path / "draft.md"
    draft.write_text(_INTENT_DRAFT, encoding="utf-8")
    runs = (
        _launch_against(ORDER, repo, cwd, "add", "12", "--decision",
                        "2026-10-01-release-scope", "--now", "2026-10-02T00:00:00Z"),
        _launch_against(INTENT, repo, cwd, "set", "--from", str(draft),
                        "--decision", "2026-10-01-release-scope",
                        "--now", "2026-10-02T00:00:00Z"),
    )
    for proc in runs:
        assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
        assert "is in the ledger" in proc.stderr, proc.stderr
        assert "holds no noni/" in proc.stderr, (
            f"the refusal names the record and not the tree: {proc.stderr}")
        assert "steering-ledger writer" in proc.stderr, proc.stderr


def test_a_ledger_refusal_on_a_real_state_root_names_only_the_record(tmp_path):
    """The other half: a tree that holds noni/ must not be told it holds none.

    The added clause is a fact about the tree, so it appears when and only when the
    tree has no ``noni/``. On a state root whose ledger holds other records, a missing
    citation is the ordinary answer and the sentence stays the one it always was --
    otherwise the same run reads as a wrong ``--repo`` to a caller who named the right
    one, which is the confusion this ticket set out to end.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    repo = _code_repo(tmp_path, "citation-real-state")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / "2026-09-01-recorded.json").write_text(
        '{"id": "2026-09-01-recorded"}\n', encoding="utf-8")
    proc = _launch_against(ORDER, repo, cwd, "add", "12", "--decision",
                           "2026-10-01-release-scope", "--now", "2026-10-02T00:00:00Z")
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "is in the ledger" in proc.stderr, proc.stderr
    assert "holds no noni/" not in proc.stderr, (
        f"a real state root was described as holding no noni/: {proc.stderr}")
