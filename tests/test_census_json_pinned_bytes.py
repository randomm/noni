"""``--json`` is a machine contract and this wording fix may not move a byte of it.

Issue #117 changed only the human branch of the census report. The NDJSON branch
is what CI steps and adapters parse, so its bytes are the contract the change is
not allowed to touch -- including the ``ok`` / ``exit`` fields that carry the
verdict there in place of the human word, and the ``not_evaluated`` field that
already said what the human report now says out loud.

Two layers guard it here. The cheap one is a table of digests, pinned against
``origin/main``'s renderer: any change to what a run writes to stdout in
``--json`` mode trips it, including a change that kept the rows valid JSON. The
expensive one is the same runs' key sets and verdict fields read as data, which
says *what* differed when the digest says *that* it did.

The digests were produced by running the same fixture trees through both renderers
-- origin/main's ``src/`` first, this branch's after -- and both sides agreed on
every case. A legitimate future change to the NDJSON shape updates them
deliberately, together with the field-level assertions below; the point of pinning
bytes is that such a change is a decision, not a side effect of a rewording.

Split from the human-report tests for the size limit, and paired with them: one
module says what the human branch now says, this one says the machine branch did
not change.
"""

from __future__ import annotations

import hashlib

from census_run import _run_census
from ordering_fixtures import _entry, _repo, _seed

# One row per state a run can be in, each pinned to the exact SHA-256 of its
# ``--json`` stdout as measured on origin/main, before this issue's change. The
# argv of each case is fixed here rather than assembled by the caller, so the
# bytes a digest names are always the bytes of the run this table describes.
NOW = "2026-10-02T00:00:00Z"
_JSON_CONTRACT: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "every check ran and nothing was found",
        ("--skip", "hygiene", "--skip", "ordering-closed", "--now", NOW),
        "8f04894a834fb3539f14c64915154c9b2aecca45536507d5a5a2cb3feccac253",
    ),
    (
        "a check was not evaluated",
        ("--skip", "hygiene", "--only", "ordering-closed", "--now", NOW),
        "68b86e0615cb6bf4ad404d49d7e68ec1c4716c19c75b69ffacee753ffe9ca602",
    ),
    (
        "the whole run, hygiene included",
        ("--json",),
        "8281b57008dac9fea6bb095acbde3c42525cf00b9d6b358b631ea899b237644f",
    ),
)


def _json_tree(tmp_path, name: str):
    """One fixture tree, seeded with a live ordered entry over a committed record.

    Same shape for every digest case: the digest pins bytes, so what it describes
    is one tree rendered several ways, not several trees.
    """
    repo = _repo(tmp_path / name, records=True)
    _seed(repo, _entry(7))
    _commit_readme(repo)
    return repo


def _commit_readme(repo) -> None:
    """A tracked file, so the hygiene class has something to scan and the tree is committed."""
    from _harness import _git

    (repo / "README.md").write_text("reader\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "-c", "user.name=Casey", "-c", "user.email=casey@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "readme")


def test_json_bytes_are_the_pinned_contract(tmp_path) -> None:
    """Same trees, same argv, byte-identical NDJSON to before the wording change.

    A digest rather than a transcription: the point of AC3 is that nothing in the
    machine branch moved, and comparing a hash says that without re-writing the
    rows here in a second form a reader would have to diff by eye.
    """
    for state, argv, expected in _JSON_CONTRACT:
        repo = _json_tree(tmp_path, state.replace(" ", "-"))
        rc, out, err = _run_census(repo, *[a for a in argv if a != "--json"], json_out=True)
        digest = hashlib.sha256(out.encode("utf-8")).hexdigest()
        assert digest == expected, (
            f"the --json bytes of a run in state {state!r} changed: {digest} != "
            f"{expected}\n{out!r}\n{err}"
        )
        assert rc == 0, f"a warn-bearing run exits 0, got {rc}:\n{out}\n{err}"


def test_json_verdict_fields_survive_the_human_wording(tmp_path) -> None:
    """The fields the machine half reads, read as data: what the digests mean.

    The warn-bearing tree is the one the human report had been calling ``clean``,
    so it is the run whose machine verdict matters: ``ok`` true with ``exit`` 0
    and no human word anywhere on the stream. If a digest above breaks, this test
    says which field moved.
    """
    import json

    repo = _json_tree(tmp_path, "verdict-fields")
    rc, out, err = _run_census(repo, "--skip", "hygiene", "--json")
    assert rc == 0, f"{rc}\n{out}\n{err}"
    rows = [json.loads(line) for line in out.splitlines() if line]
    summaries = [r for r in rows if r["kind"] == "summary"]
    assert len(summaries) == 1, rows
    summary = summaries[0]
    assert set(summary) <= {"schema", "kind", "ok", "exit", "counts", "not_evaluated"}, summary
    assert summary["ok"] is True and summary["exit"] == 0, summary
    # The human words of this issue belong to the human branch alone. ``clean`` is
    # not asserted absent: a hygiene row's message says "not a hygiene-clean
    # guarantee", and that sentence is the row's business, not the verdict's.
    for word in ("warning(s)", "no findings", "all checks passed", "did not run"):
        assert word not in out, f"the human word {word!r} reached --json: {out}"
