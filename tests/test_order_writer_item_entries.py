"""A pre-removal order is refused by the writer and reported by the arbiter.

The item store was removed, so ``order.py`` no longer reads an ``item`` entry or a
``noni.order/2`` marker as an order. What happens to one is the whole content of this
suite: the artifact is left untouched, the run is refused with the repair named, and the
census reports the same file rather than passing it.

Every verb is tried against both pre-removal shapes, because every verb rebuilds the
whole list from what it read: a verb that accepted such a file would delete the operator's
entry rather than refuse the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from order_fixtures import _order, _order_path
from order_fixtures import _repo as _writer_repo
from ordering_fixtures import _order as _commit_artifact
from ordering_fixtures import _repo as _census_repo
from ordering_fixtures import _run
from ordering_shapes import NOW

from noni.orderschema import MIGRATION_HINT

# The verbs, each in the form that would change the artifact if the read accepted it.
VERBS = (
    ("add", "9", "--decision", "2026-10-01-baseline"),
    ("move", "7", "--to", "1"),
    ("remove", "7"),
    ("confirm",),
)

# The two shapes the removal left behind: the document that still states the retired
# version, and the entry that still carries the retired key.
PRE_REMOVAL = {
    "the retired schema version":
        '{"schema": "noni.order/2", "entries": ['
        '{"issue": 7, "decision": "2026-10-01-baseline",'
        ' "confirmed": "2026-10-26T00:00:00Z"}]}',
    "the retired item key":
        '{"schema": "noni.order/1", "entries": ['
        '{"item": "idea-0001", "decision": "2026-10-01-baseline",'
        ' "confirmed": "2026-10-26T00:00:00Z"}]}',
}


def _writer_tree(tmp_path, label: str, index: int) -> Path:
    """A writer's tree with the pre-removal artifact ``label`` committed at its path."""
    repo = _writer_repo(tmp_path, f"writer-{label}-{index}")
    _commit_artifact(repo, PRE_REMOVAL[label])
    return repo


def _arbiter_tree(tmp_path, label: str, index: int) -> Path:
    """A census tree holding the pre-removal artifact ``label`` and its ledger."""
    repo = _census_repo(tmp_path, f"arbiter-{label}-{index}")
    _commit_artifact(repo, PRE_REMOVAL[label])
    return repo


def test_every_verb_refuses_a_pre_removal_order_and_writes_nothing(tmp_path):
    for label in PRE_REMOVAL:
        for index, verb in enumerate(VERBS):
            repo = _writer_tree(tmp_path, label, index)
            path = _order_path(repo)
            before = path.read_bytes()
            proc = _order(repo, *verb, "--now", NOW)
            assert proc.returncode == 4, (label, verb, proc.stdout, proc.stderr)
            assert path.read_bytes() == before, (label, verb)


def test_the_refusal_names_the_repair(tmp_path):
    for label in PRE_REMOVAL:
        repo = _writer_tree(tmp_path, label, 90)
        proc = _order(repo, "confirm", "--now", NOW)
        text = proc.stdout + proc.stderr
        assert MIGRATION_HINT in text, (label, text)


def test_the_census_reports_a_pre_removal_order_as_malformed(tmp_path):
    for label in PRE_REMOVAL:
        repo = _arbiter_tree(tmp_path, label, 90)
        code, rows, _out, _err = _run(repo)
        findings = [row for row in rows if row.get("check") == "ordering-malformed"]
        assert code == 15, (label, code, rows)
        assert findings, (label, rows)
        assert any(MIGRATION_HINT in json.dumps(row) for row in findings), (label, rows)


def test_a_pre_removal_order_is_not_restamped_down_to_the_current_version(tmp_path):
    """The refusal does not leave a file that reads as a valid order to someone else.

    A reader that dropped the offending entry rather than refusing the file would leave
    an artifact whose stated version no longer matches its entries: nothing in the
    product may rewrite a pre-removal file into a ``/1`` document, because the entry it
    removed was the operator's.
    """
    repo = _writer_tree(tmp_path, "the retired schema version", 91)
    _order(repo, "add", "9", "--decision", "2026-10-01-baseline", "--now", NOW)
    assert json.loads(_order_path(repo).read_text())["schema"] == "noni.order/2"
