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
# The whole-run case scans hygiene, so it needs a now of its own: without --now it
# reads the real clock and the fixture's confirmed date goes past the 30 day stale
# threshold, embedding a daily age in a row, so the digest rots every day. Keep this
# date before the fixture's confirmed date plus 30 days.
WHOLE_RUN_NOW = "2026-11-10T00:00:00Z"
_JSON_CONTRACT: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "every check ran and nothing was found",
        ("--skip", "hygiene", "--skip", "ordering-closed", "--now", NOW),
        "8f04894a834fb3539f14c64915154c9b2aecca45536507d5a5a2cb3feccac253",
    ),
    (
        "a check was not evaluated",
        ("--skip", "hygiene", "--only", "ordering-closed", "--now", NOW),
        # Re-pinned for issue #148, which gave this run its own row of the class: the
        # summary row's ``not_evaluated`` field is unchanged and the run still exits 0.
        # Re-pinned again for #235, which named the silencer in the row and the note;
        # the field's shape, ``ok`` and ``exit`` are unchanged from the bytes above.
        "69edc027f2dc7acd16838df11aec05540fde2a8a6b8b947da0f7894129c2dab1",
    ),
    (
        "the whole run, hygiene included",
        ("--json", "--now", WHOLE_RUN_NOW),
        # Re-pinned for issue #194, which moved the absent deny-list out of the
        # rows and onto the summary's ``not_evaluated`` list: the run loses its
        # deny-list finding row and gains the note. The other two cases are
        # unchanged, both because they skip the hygiene class. Re-pinned again for
        # #235, which named the silencer in the row and in the note this run carries.
        # Measured with the fixed --now above, so these bytes do not move with the
        # wall clock.
        #
        # NOT re-pinned for #237, and that is the point of writing it down: #237
        # changed the ``fix`` value of the deny-list row, and this run's bytes did
        # not move, because the case says `--json` without `--strict` and an absent
        # deny-list outside --strict is the note on the summary row that issue #194
        # put there -- there is no deny-list finding row in this stream for the new
        # hint to sit on. The row #237 changed is pinned by value in
        # tests/test_census_hygiene_denylist_fix_hint.py; had this digest moved, the
        # run below would have said so and the bytes here would have been re-measured.
        "f133cb2e55f7335840d4fc44d18eca3f0cc128f4f43b06531f406bd4ac7bae7e",
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


def test_the_whole_run_case_owes_the_note_and_not_a_deny_list_row(tmp_path):
    """Why the whole-run digest survived #237, asserted rather than assumed.

    That case is the only pinned one that audits hygiene, and #237 changed a hygiene
    ``fix`` value without moving its bytes. The reason is in the fixture, not in a
    hole in the digest: the case passes ``--json`` without ``--strict``, and an absent
    deny-list outside ``--strict`` is the summary's ``not_evaluated`` sentence
    (issue #194) rather than a finding row, so the row whose hint moved is not in the
    stream at all. A digest that let a change to a row it *does* print pass unnoticed
    is the failure this module exists to catch, so the absence is pinned here rather
    than left as an accident of the fixture.
    """
    import json

    from census_hygiene import HYGIENE_DENYLIST_NOTE

    repo = _json_tree(tmp_path, "whole-run-note")
    rc, out, err = _run_census(repo, "--now", WHOLE_RUN_NOW, json_out=True)
    assert rc == 0, f"{rc}\n{out}{err}"
    rows = [json.loads(line) for line in out.splitlines() if line]
    subjects = [r.get("subject") for r in rows if r.get("kind") == "finding"]
    assert "deny-list" not in subjects, (
        f"a deny-list finding row would put the #237 hint into the pinned digest: "
        f"{subjects}")
    summary = [r for r in rows if r["kind"] == "summary"][0]
    assert HYGIENE_DENYLIST_NOTE in summary["not_evaluated"], summary


def test_every_contract_case_pins_its_now() -> None:
    """Every digest case names its own ``--now``.

    A case without it reads the real clock, so a time-based row can change with
    the date and the pinned bytes rot on their own. Structural check, no run.
    """
    for state, argv, _ in _JSON_CONTRACT:
        assert "--now" in argv, (
            f"the digest case {state!r} passes no --now, so its bytes depend on the "
            f"real clock: {argv}"
        )


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
