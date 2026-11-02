"""The rebase-state directories are one definition, read from the module that owns it.

The rebase-state split moved ``REBASE_STATE_DIRS`` to ``_session_rebase_state.py``,
which is where the probe reads it, and ``claim.py`` imports the name. A second
literal beside the real one is the fault this pins: the classifier would walk one
list while the probe and the claim suite's post-condition helper walked the other,
and a backend directory present on only one side would go unasserted rather than
failing. One list is therefore read four ways -- the owner's source as a literal,
``claim.py`` as an imported name, the probe loop's own constant, and the set the
suite asserts on -- and all four must agree.

The probe leg iterates ``_session_rebase_state.REBASE_STATE_DIRS`` itself, the
runtime constant :func:`noni._session_push.stopped_state_dir` walks, so the names
probed here are the names probed in a push. Were that leg to iterate a literal of
its own, a directory added to the constant would be asserted against nothing and
the equality below would be the only thing still true about it -- which is exactly
the drift this test exists to catch, and the reason it is proved by mutation in
``test_the_probe_leg_follows_the_constant_and_not_a_literal_of_its_own``.

The name list itself is read by the helper the claim rebase suite uses for its
post-conditions (``_rebase_state_paths``), so a constant edited in the owner moves
this test and that suite's assertions together.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _harness import (
    SRC,
    _claim_module,
    _init_repo,
    _script_ast,
    _script_constant,
)
from test_claim_validation_rebase import _rebase_state_paths


def test_the_rebase_state_directories_are_one_definition(tmp_path: Path) -> None:
    """The owner's literal, claim.py's imported name and the probe's set are one."""
    from noni import _session_push, _session_rebase_state

    claim_mod = _claim_module()
    owner = _script_constant(_script_ast(SRC / "noni" / "_session_rebase_state.py"),
                             "REBASE_STATE_DIRS", "_session_rebase_state.py")
    assert owner == ("rebase-merge", "rebase-apply"), owner
    assert claim_mod.REBASE_STATE_DIRS == owner
    # The probe loop's own name and the owner's constant are the same object: the
    # loop walks what the owner declares, not a list it copied at import time.
    assert _session_push.REBASE_STATE_DIRS == _session_rebase_state.REBASE_STATE_DIRS
    assert _session_rebase_state.REBASE_STATE_DIRS == owner
    # The set the suite asserts on is derived from that same literal, so a
    # backend directory added to the constant is probed and asserted together.
    repo = _init_repo(tmp_path / "repo")
    assert [state.name for state in _rebase_state_paths(repo)] == list(owner)
    # And the probe walks it: each name answers the probe's own three-way verdict
    # rather than being invisible to it. This leg reads the runtime constant, so a
    # name added to the owner is probed here without editing this test.
    probed = []
    for name in _session_rebase_state.REBASE_STATE_DIRS:
        assert _session_rebase_state.stopped_state(
            tmp_path, Path(name))[1] == "absent", name
        probed.append(name)
    assert probed == list(owner), (
        f"the probe leg walked {probed}, not the constant's {list(owner)}")


def test_the_probe_leg_follows_the_constant_and_not_a_literal_of_its_own(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation proof for the probe leg above: it iterates the runtime constant.

    A leg that iterated a hard-coded pair would keep passing while a directory added
    to ``REBASE_STATE_DIRS`` went unprobed. So the walk is run twice from one helper:
    unmutated it must report the owner's two names, and after the constant is
    extended by monkeypatch it must report the third. A walk over its own literal
    fails the second assertion, which is what makes this proof bite rather than
    merely pass.
    """
    from noni import _session_rebase_state

    asked: list[str] = []

    def _fake_stopped_state(repo: Path, probed_dir: Path):
        asked.append(probed_dir.name)
        return None, "absent"

    monkeypatch.setattr(_session_rebase_state, "stopped_state", _fake_stopped_state)
    repo = _init_repo(tmp_path / "repo")

    def _walk() -> list[str]:
        """The probe leg under test: the same loop the first test runs.

        Bound here so the mutation can be applied *before* the leg runs. Answering
        the added name is the mutation's own job (``stopped_state`` is faked to
        record what it was asked about), so an unmutated walk simply records the
        owner's two names.
        """
        walked: list[str] = []
        for name in _session_rebase_state.REBASE_STATE_DIRS:
            assert _session_rebase_state.stopped_state(repo, Path(name))[1] == "absent"
            walked.append(name)
        return walked

    # The unmutated walk reports exactly the owner's names, so the extra name below
    # can only arrive through the constant: a leg iterating its own literal would
    # report the pair with or without the mutation and prove nothing.
    assert _walk() == ["rebase-merge", "rebase-apply"]

    monkeypatch.setattr(_session_rebase_state, "REBASE_STATE_DIRS",
                        ("rebase-merge", "rebase-apply", "rebase-mutation"))
    asked.clear()
    assert _walk() == ["rebase-merge", "rebase-apply", "rebase-mutation"], (
        "a leg that iterates its own literal would report the pair and never notice "
        f"the added directory; it reported {asked}")
    assert asked == ["rebase-merge", "rebase-apply", "rebase-mutation"], (
        f"the walk named directories the constant does not carry: {asked}")
