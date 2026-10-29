"""The check contract has exactly one source.

``CHECKS`` owns the ids, codes and severities; the help text, the ``--list`` output
and the rendered rows are renderings of it, never extra copies.

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
