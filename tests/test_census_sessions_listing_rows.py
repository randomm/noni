"""The rows a faulted register listing earns: bounded, verdicted, never silent.

The row budget is what the fault's own sentence leaves, the ledger row keeps its
verdict beside a long fault, and a fault with no words at all still says which class
refused.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json

import census_ledger  # noqa: E402
from _harness import _commit_file, _fault_the_sessions_listing, _init_repo
from census_fixtures import (
    _ndjson_rows,
    _sessions_fault_row,
    _sessions_fixture,
    _valid_record,
    census_module,
)
from census_run import _run_census


class TestSessionsListingFault:
    """A ``noni/sessions/`` that cannot be listed is a fault, not a clean register.

    ``Path.glob`` swallows the ``OSError`` readdir raises and yields nothing, so
    while the register was listed with ``glob`` a directory the run could not
    read reported the same verdict as a project that had never opened a session.
    The register is listed with ``iterdir`` now, and these are the rows that
    fault earns — the sessions-side twin of ``TestLedgerStateVocabulary``'s
    ledger-listing tests, kept to the same contract and the same fault-injection
    seam for the same reason (a chmod fixture is vacuous on a root-equivalent
    runner, and patching ``glob`` would fault nothing).
    """

    def test_the_row_budget_is_what_its_own_sentence_leaves(
        self, tmp_path
    ):
        """The fault gets the room the sentence does not use, and nothing more.

        The bound is arithmetic on the sentence actually built, not a number a
        caller guesses and hands in: measure the message with the fault left
        empty, subtract that from the 300 the row keeps, and the fault text is
        bound to what is left over. A caller that later lengthens its own clause
        pays for it out of the fault's budget automatically, so the row cannot
        drift past its bound by a group editing its prose.

        The test reads the budget off the finished row rather than off a
        constant: with a 5000-character fault the row must sit at the bound, must
        still end with the group's own ``unknown`` clause, and must have spent its
        slack on the fault's padding -- which is the same fact as "the budget is
        the sentence's leftover", seen from the outside. The path is the short
        root-relative one, because the slack is measured against the whole
        sentence: a caller that hands in a long path is charged for it too (see
        :meth:`test_the_row_keeps_its_verdict_whatever_the_fault_and_path_said`).
        """
        skeleton_head = "could not be listed ("
        row_bound = census_ledger.ROW_BOUND
        for filler in ("u", "e"):
            row = _sessions_fault_row("noni/sessions", filler * 5000)
            message = row["message"]
            assert len(message) <= row_bound, f"{len(message)} chars: {message[:80]}"
            assert message.endswith("cannot be answered"), (
                f"the verdict clause is the last thing the row should lose: "
                f"{message[-120:]!r}"
            )
            # The leftover went to the fault: only the clip's own ellipsis stays
            # out of it. So the row sits at its bound, and a budget any smaller
            # would have cut the fault short of what the sentence could pay for.
            assert len(message) >= row_bound - 3, message[-60:]
            assert len(message) <= row_bound, message[-60:]
            start = message.index(skeleton_head) + len(skeleton_head)
            assert message[start] == filler, (
                f"the fault is not what filled the row's slack: {message[start - 20:start + 20]!r}"
            )

    def test_the_ledger_row_keeps_its_verdict_on_a_long_fault(self, tmp_path, monkeypatch):
        """The same budget rule, at the other caller of the shared builder.

        The ledger group's sentence is not the sessions group's sentence, so a
        budget that was right for one is not a budget the other may claim: the
        row is built by the same function and must arrive at the same place -- at
        the bound, ending in its own verdict clause -- from a fault of the same
        length. Reached through ``census.main`` with a faulted readdir, because
        the ledger caller is the one the group's own filter drives.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "decisions",
                                    text="u" * 5000)
        _rc, out, err = _run_census(repo, "--only", "ledger-edited", json_out=True,
                                    skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1, f"expected the one fault row: {rows}"
        message = rows[0]["message"]
        assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
        assert message.endswith("cannot be answered"), (
            f"the ledger's own verdict clause lost to its bound: {message[-120:]!r}"
        )
        assert "noni/decisions" in message, message

    def test_the_row_keeps_its_verdict_whatever_the_fault_and_path_said(
        self, tmp_path
    ):
        """The row's own finding survives the bound, however hostile its inputs.

        The sentence is the row's diagnosis and the fault dropped into it is
        foreign text, so the fault is bound to what the sentence leaves over:
        ``clipped`` must cut the tail of a 3000-character ``strerror``, never the
        clause that says what could not be answered. Three input categories the
        bound used to eat that clause for, at the row's full 300 characters: an
        ordinary root-relative path, a relative path the caller walked far out of
        the tree, and an absolute one it cannot root at all. No test calls the
        shared builder by hand: the row is reached through the group's own entry
        point (``_append_sessions_listing_fault``, or ``census.main`` for the
        ledger twin below), so a claim about the row is a claim about what the
        product renders and not about how a test wires the helpers together.

        The row is bounded against the sentence it actually builds, so the two
        halves of the rule pull against each other and both are asserted here:
        the fault's padding is what the clip cuts (the census's own words survive
        at both ends of the row), and a path that is not root-relative never
        reaches the row at its raw length -- the unrootable forms are reduced to
        their last segment by ``ledger_name`` before the sentence is built.
        """
        for path, fault in (
            ("noni/sessions", "u" * 3000),
            ("build/home/someone/.aws/" + "a" * 240 + "/sessions", "u" * 3000),
            ("/abs/home/elsewhere/sessions", "y" * 3000),
        ):
            row = _sessions_fault_row(path, fault)
            message = row["message"]
            assert len(message) <= census_ledger.ROW_BOUND, f"{len(message)} chars"
            # The census's own words, at both ends of the sentence, whatever the
            # caller handed in for the path and whatever the fault said.
            assert message.startswith("cannot-tell: the sessions register "), message[:60]
            assert message.endswith("cannot be answered"), (
                f"the row lost the verdict clause to its own bound: "
                f"{message[-120:]!r}"
            )
            assert "exists but could not be listed (" in message, message[:140]
            # One identifier, three fields, and it is never the raw path the
            # caller spelled -- the root-relative form is kept, everything else
            # is reduced to its last segment.
            name = census_ledger.ledger_name(path)
            assert row["subject"] == row["artifact"] == name, row
            assert f"({name}) exists" in message, message[:140]
            if not path.startswith("noni/"):
                assert path not in message, f"raw path leaked: {message[:140]}"

    def test_a_fault_with_no_words_at_all_still_says_which_class_refused(
        self, tmp_path, monkeypatch
    ):
        """A blank ``strerror`` is answered with the class name, not silence.

        A driver can hand back an errno with no text at all. The row is a
        cannot-tell about one directory, and its point is that a read was
        attempted and refused; a fault field that came back empty would leave
        that clause to print nothing but its own parentheses, and the gate and
        the reporter would be reading a field whose emptiness means two things.
        """
        # A repo whose register is the directory the guard below refuses, so the
        # fault is reached through census.main and not only through the listing
        # function: the gate is the other reader of the fault field, and an empty
        # one would leave the group unrun -- the silent clean this ticket exists
        # to close.
        repo = _sessions_fixture(tmp_path)
        register = repo / "noni" / "sessions"
        census = census_module()
        real_iterdir = census.Path.iterdir

        def blank_boom(self):
            # An errno with no text at all: the shape a driver hands back when it
            # refuses a readdir without saying why. Whitespace-only strerror is
            # the case, because the scrubber collapses it to nothing.
            if self == register:
                raise OSError(5, "   ")
            return real_iterdir(self)

        monkeypatch.setattr(census.Path, "iterdir", blank_boom)
        probe = census._sessions_listing(register)
        assert probe.names is None and probe.fault, (
            f"a faulted read never carries an empty fault field: {probe!r}"
        )

        # A run whose filter named no session class at all: the gate is the only
        # thing standing between this fault and a clean exit 0.
        rc, out, err = _run_census(repo, "--only", "ledger-record",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1, (
            f"a blank-strerror fault must still open the group and earn its row: "
            f"{rows}"
        )
        assert "OSError" in rows[0]["message"], (
            f"a fault that carried no words must still name the class: "
            f"{rows[0]['message']!r}"
        )
        assert "could not be listed" in rows[0]["message"], rows[0]
        assert rc == 0, f"the fault row is a warn, got {rc}\nstderr: {err}"
