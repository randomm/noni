"""The rebase-state directories are one definition, read from the module that owns it.

The rebase-state split moved ``REBASE_STATE_DIRS`` to ``_session_rebase_state.py``,
which is where the probe reads it, and ``claim.py`` imports the name. A second
literal beside the real one is the fault this pins: the classifier would walk one
list while the probe and the claim suite's post-condition helper walked the other,
and a backend directory present on only one side would go unasserted rather than
failing. One list is therefore read three ways -- the owner's source as a literal,
``claim.py`` as an imported name, and the probe as the set it actually examines --
and all three must agree.

The name list itself is read by the helper the claim rebase suite uses for its
post-conditions (``_rebase_state_paths``), so a constant edited in the owner moves
this test and that suite's assertions together.
"""

from __future__ import annotations

from pathlib import Path

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
    from noni import _session_rebase_state

    claim_mod = _claim_module()
    owner = _script_constant(_script_ast(SRC / "noni" / "_session_rebase_state.py"),
                             "REBASE_STATE_DIRS", "_session_rebase_state.py")
    assert owner == ("rebase-merge", "rebase-apply"), owner
    assert claim_mod.REBASE_STATE_DIRS == owner
    # The set the suite asserts on is derived from that same literal, so a
    # backend directory added to the constant is probed and asserted together.
    repo = _init_repo(tmp_path / "repo")
    assert [state.name for state in _rebase_state_paths(repo)] == list(owner)
    # And the probe walks it: each name answers the probe's own three-way verdict
    # rather than being invisible to it.
    for name in owner:
        assert _session_rebase_state.stopped_state(
            tmp_path, Path(name))[1] == "absent", name
