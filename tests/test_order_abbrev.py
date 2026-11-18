"""No abbreviation of a flag reaches the whole-order restamp the ``--all`` gate guards.

``--all`` exists so that flattening every ``confirmed`` time is something the operator
types out. Argparse's default prefix matching does not honour that: on a parser built
with ``allow_abbrev`` left on, ``confirm --al`` resolves to ``--all`` and the run exits 0
having committed ``direction: confirm all``. Two characters are not an explicit
``--all``, and a gate that a two-character prefix walks through is not a gate.

The brief's parser (:mod:`noni.brief`) already passes ``allow_abbrev=False``; the order
writer's is built by ``order_plan.build_parser``, so the switch belongs there, in the one
place the parser is built. What this module pins:

- a launched ``order confirm --al`` on an order with entries exits 2, writes no byte,
  makes no commit and restamps nothing -- the same outcome the bare ``confirm`` refuses
  to, and reached the same way, from argv alone;
- ``--a`` is refused too (it stands for no single flag, so argparse is the one that says
  no);
- the single-dash lookalikes ``-all``, ``-a`` and ``-all 1`` are refused as well.
  ``allow_abbrev=False`` governs ``--`` prefixes only, so these forms are not covered by
  the switch above and have to be answered for themselves;
- every flag of the writer is still accepted in full, so what died is the abbreviation
  and not the flag.
"""

from __future__ import annotations

import subprocess

from _harness import subprocess_env
from order_fixtures import (
    BASELINE_ID,
    NOW,
    _entry,
    _order,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
)

from noni import order_plan

ALL = order_plan.ALL_FLAG


def _head(repo) -> str:
    """HEAD's commit id, read from git rather than through the code under test."""
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, env=subprocess_env(),
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _seeded(tmp_path, name: str):
    """A tree holding three entries at three distinct confirmed stamps.

    Unequal on purpose: a run that flattened the queue changed all three, so a fixture
    whose entries already agreed with the run's stamp would let the destructive run take
    the writer's no-change shortcut and commit nothing.
    """
    repo = _repo(tmp_path, name)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-02T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-03T00:00:00Z"))
    return repo


STAMPS = ["2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z", "2026-10-03T00:00:00Z"]


def test_a_prefix_of_the_whole_order_flag_does_not_restamp(tmp_path):
    """``confirm --al`` is not ``confirm --all``: exit 2, no byte written, no commit.

    The three slots that matter are the file's bytes, HEAD and the working tree: the
    abbreviating run this test was written against changed all three, which is the whole
    of the incident the ticket was filed from.
    """
    repo = _seeded(tmp_path, "abbrev")
    before = _order_path(repo).read_bytes()
    head_before = _head(repo)
    porcelain_before = _porcelain(repo)

    proc = _order(repo, "confirm", "--al", "--now", NOW)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert _order_path(repo).read_bytes() == before, "an abbreviated flag rewrote the order"
    assert _head(repo) == head_before, "an abbreviated flag committed"
    assert _porcelain(repo) == porcelain_before, (
        f"an abbreviated flag left the tree dirty: {_porcelain(repo)!r}")
    assert [entry["confirmed"] for entry in _read(repo)["entries"]] == STAMPS
    assert "committed" not in proc.stdout, proc.stdout


def test_a_prefix_that_stands_for_two_flags_is_refused_by_argparse(tmp_path):
    """``--a`` is a prefix of three flags, so nothing is quietly chosen.

    argparse's own answer is enough here -- exit 2 and no write -- but the run must not
    reach the plan either, so the artifact's bytes are asserted rather than inferred.
    """
    repo = _seeded(tmp_path, "ambiguous")
    before = _order_path(repo).read_bytes()
    head_before = _head(repo)

    proc = _order(repo, "confirm", "--a", "--now", NOW)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert _order_path(repo).read_bytes() == before
    assert _head(repo) == head_before
    assert _porcelain(repo) == "", _porcelain(repo)
    assert [entry["confirmed"] for entry in _read(repo)["entries"]] == STAMPS


def test_a_single_dash_spelling_of_the_whole_order_flag_does_not_restamp(tmp_path):
    """``-all``, ``-a`` and ``-all 1`` reach the whole-order write no more than ``--al``.

    ``allow_abbrev=False`` switches off prefix matching for long ``--`` options; it says
    nothing about a single dash, which argparse reads as a cluster of short options. This
    writer has none, so each form below is a token it cannot place. What is asserted is
    the outcome rather than the sentence: exit 2, the artifact's bytes, HEAD, and a clean
    tree, with the stamps still the three unequal ones the fixture was seeded at. The
    ``1`` case is the one that would restamp an entry if the token were ever taken as the
    subject, and it is refused too.
    """
    for argv in (("confirm", "-all"), ("confirm", "-a"), ("confirm", "-all", "1")):
        name = "dash" + argv[1].lstrip("-") + ("-subject" if len(argv) > 2 else "")
        repo = _seeded(tmp_path, name)
        before = _order_path(repo).read_bytes()
        head_before = _head(repo)

        proc = _order(repo, *argv, "--now", NOW)

        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stdout}{proc.stderr}"
        assert _order_path(repo).read_bytes() == before, f"{argv} rewrote the order"
        assert _head(repo) == head_before, f"{argv} committed"
        assert _porcelain(repo) == "", f"{argv} left the tree dirty: {_porcelain(repo)!r}"
        assert [entry["confirmed"] for entry in _read(repo)["entries"]] == STAMPS


def test_every_flag_is_still_accepted_in_full(tmp_path):
    """The switch costs no flag: each one still works spelled out.

    The cheap way to make an abbreviation refuse is to drop the flag, which would break
    the writer for every caller; this is the half that says only the shortening died.
    """
    repo = _seeded(tmp_path, "full-flags")
    proc = _order(repo, "add", "9", "--decision", BASELINE_ID, "--at", "1",
                  "--why", "the operator wants it first", "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    proc = _order(repo, "move", "9", "--to", "2", "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    proc = _order(repo, "confirm", "9", "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    proc = _order(repo, "confirm", ALL, "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    proc = _order(repo, "remove", "9", "--now", NOW, "--no-commit")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert [entry["issue"] for entry in _read(repo)["entries"]] == [1, 2, 3]
