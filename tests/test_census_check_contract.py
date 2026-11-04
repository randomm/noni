"""The check contract has exactly one source.

``CHECKS`` owns the ids, codes and severities; the help text, the ``--list`` output,
the rendered rows and the quickstart's CI section are renderings of it, never extra
copies.

The first class settles the surfaces the census itself renders. The second settles
the prose a team pastes into a build: the fail and warn sets printed by the
"Run the census in CI" section must be exactly ``CHECKS`` split by default severity,
so a class added to the table without a row on the page -- or a code the page
invented -- fails here naming both sides. The launches that earn those two
documented verdicts (exit 0 on a clean tree, the double-claim code on a planted
one) are ``tests/test_quickstart_ci.py``'s; this module settles only that what the
page says and what the table says are the same set, along with the section's
``--strict`` promise.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

class TestCheckContractIsDerived:
    """The check ids, codes and severities have exactly one source (CHECKS);
    the surfaces a caller reads are renderings of it, not extra copies."""

    def test_list_matches_the_table(self):
        import io
        from contextlib import redirect_stdout

        import census

        buf = io.StringIO()
        with redirect_stdout(buf):
            assert census.main(["--list"]) == 0
        assert set(buf.getvalue().split()) == set(census.CHECKS), (
            "--list and CHECKS have drifted apart"
        )

    def test_strict_help_lists_the_warn_classes(self):
        import census

        parser = census._build_parser()
        strict = next(a for a in parser._actions if a.dest == "strict")
        for name, (_code, sev, _fix) in census.CHECKS.items():
            if sev == "warn":
                assert name in strict.help, f"--strict help omits warn class {name}: {strict.help}"
        # No fail class leaks into the list a reader uses to decide what
        # --strict changes. Match the id as a whole word, not as a substring:
        # "session-double" is contained in "session-double-…" style ids and
        # would pass an `in` test for the wrong reason.
        listed = set(re.findall(r"[a-z][a-z-]+", strict.help))
        for name, (_code, sev, _fix) in census.CHECKS.items():
            if sev == "fail":
                assert name not in listed, f"--strict help names a fail class {name}: {strict.help}"

    def test_skill_md_options_table_strict_row_matches_the_help_string(self):
        """The --strict contract is written in CHECKS and rendered in three
        places; the two prose renderings must list the same classes."""
        import census

        parser = census._build_parser()
        help_ids = {m for m in re.findall(r"[a-z][a-z-]+",
                                         next(a for a in parser._actions
                                             if a.dest == "strict").help)
                    if m in census.CHECKS}
        text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `--strict`"))
        table_ids = set(re.findall(r"`([a-z][a-z-]+)`", row)) - {"--strict"}
        assert help_ids == table_ids, (
            f"--strict help and the SKILL.md options row disagree: {help_ids ^ table_ids}"
        )

    def test_skill_md_documents_the_same_table(self):
        """SKILL.md's exit-code block is the operator-facing contract; a class
        added to CHECKS without documenting it here fails."""
        import census

        text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\s*(\d{2})\s+([a-z-]+)", text, re.MULTILINE))
        by_code = {(str(c), n) for n, (c, _s, _f) in census.CHECKS.items()}
        assert by_code <= documented, (
            f"SKILL.md is missing exit-code lines for: {sorted(by_code - documented)}"
        )
        for name, (_code, _sev, _fix) in census.CHECKS.items():
            assert f"`{name}`" in text, f"SKILL.md does not document check {name}"


class TestQuickstartCISetsAgreeWithTheTable:
    """The CI section's two documented sets are the table, not a second list.

    The sets are read out of the page's own bullets by
    :func:`test_quickstart_ci.documented_fail_codes` /
    ``documented_warn_codes`` -- the one page parser, shared with the launches --
    so what is compared is the text a reader copies, and this module keeps no copy
    of it.
    """

    def test_the_documented_fail_set_is_the_table_fail_severity(self):
        import census
        from test_quickstart_ci import documented_fail_codes

        fail = documented_fail_codes()
        expected = {code for code, sev, _fix in census.CHECKS.values() if sev == "fail"}
        assert fail == expected, (
            f"the page's fail set {sorted(fail)} is not the census's fail classes "
            f"{sorted(expected)} (src/noni/census_report.py CHECKS)")

    def test_the_documented_warn_set_is_the_table_warn_severity(self):
        import census
        from test_quickstart_ci import documented_warn_codes

        warn = documented_warn_codes()
        expected = {code for code, sev, _fix in census.CHECKS.values() if sev == "warn"}
        assert warn == expected, (
            f"the page's warn set {sorted(warn)} is not the census's warn classes "
            f"{sorted(expected)} (src/noni/census_report.py CHECKS)")

    def test_the_two_documented_sets_are_disjoint_and_jointly_complete(self):
        """A code on neither side leaves a build to guess; on both sides it is
        documented as failing and not failing at once."""
        import census
        from test_quickstart_ci import documented_fail_codes, documented_warn_codes

        fail, warn = documented_fail_codes(), documented_warn_codes()
        assert not (fail & warn), f"a code is documented on both sides: {fail & warn}"
        assert fail | warn == set(census.CLASS_CODE.values()), (
            f"the page documents {sorted(fail | warn)} of the census's "
            f"{sorted(set(census.CLASS_CODE.values()))} codes")

    def test_the_section_keeps_the_run_un_strict_and_names_the_opt_in(self):
        """The documented step runs without ``--strict``, and ``--strict`` is the
        opt-in a team adds once the deny-list holds a usable entry.

        Read off the page the reader copies, and checked against the product too:
        every warn class the page lists must be one ``--strict`` promotes, so the
        sentence cannot describe a mode the census does not have.
        """
        import census
        from test_quickstart_ci import ci_commands, ci_section

        section = ci_section()
        assert "--strict" in section, "the CI section no longer mentions --strict"
        assert "without `--strict`" in section, (
            "the CI section no longer says the documented step runs without --strict")
        assert "at its own code" in section, (
            "the section no longer says a warn class fails at its own code under "
            "--strict")
        assert "usable entry" in section, (
            "the section offers --strict without naming its precondition")
        for argv in ci_commands():
            assert "--strict" not in argv, f"a documented CI step runs --strict: {argv}"
        for name, (_code, default, _fix) in census.CHECKS.items():
            if default == "warn":
                assert name in _strict_help(), (
                    f"--strict no longer promotes {name}, so the page's sentence "
                    "about warn classes failing at their own code is stale")


def _strict_help() -> str:
    """The --strict help string, which lists the classes the flag promotes."""
    import census

    action = next(a for a in census._build_parser()._actions if a.dest == "strict")
    return action.help
