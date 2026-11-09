"""A ``--slug`` that already carries a date is refused before anything is written.

The defect: ``id`` is ``<date>-<slug>`` and the writer prefixes the date
unconditionally (``_writer.ledger_name``), so a slug of ``2026-11-08-topic``
became the record ``2026-10-26-2026-11-08-topic.json`` -- a doubled date nobody
asked for, which then entered a supersede chain like any other record. The rule
that stops it is shape-only: an ASCII ``^[0-9]{4}-[0-9]{2}-[0-9]{2}-`` prefix is
refused at the writer's existing usage code, whatever the calendar says about
those digits.

Two properties are worth a module of their own rather than a case in the slug
test beside them.

The first is that the rule is *shape*, not calendar. ``parse_date`` is the
package's only calendar check and it belongs to ``--date``: a slug that looks
like a date is refused for its shape, so ``2026-13-45-topic`` is refused too,
and a slug that merely contains digits or a date elsewhere is accepted exactly as
before. A refusal that routed through ``parse_date`` would accept a shape the
writer is meant to refuse and refuse a slug whose date is nobody's business.

The second is that both slug validators carry it. ``_decide_flags.build_record_flags``
is decide's first usage check and ``_writer.flag_refusals`` is the writer's
second; either one alone would leave the other entry point free to build the
doubled id. They are driven here directly as well as through ``decide``, because
the entry points are the thing that has to agree.

And because a refusal that wrote a file before refusing would have lost the
point, every refusal run asserts an untouched tree: no record at either the
doubled or the corrected path, and an empty ``git status --porcelain``.
"""

from __future__ import annotations

import re

from _harness import _git_e2
from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_DATE,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _porcelain,
    _record_path,
    _run,
)

# The bug's own shape, and the corrected slug the refusal must show.
DATED_SLUG = "2026-11-08-topic"
CORRECTED = "topic"
# The doubled id the writer would have built from DATED_SLUG on NEW_DATE.
DOUBLED_ID = f"{NEW_DATE}-{DATED_SLUG}"

# Shapes that refuse: the bug, a calendar-impossible date (the rule is shape, so
# the calendar never gets a vote), a date that carries a second date as its slug,
# and a date plus a trailing dash, whose empty remainder the character rule refuses.
REFUSED = (
    DATED_SLUG,
    "2026-13-45-topic",
    "2026-11-08-2026-11-09-topic",
    "2026-11-08-",
)
# What each refusal must show as the corrected slug: the value minus one date
# prefix, which for a doubled date is the second date -- still a prefix the next run
# refuses. ``2026-11-08-`` has no remainder, so its refusal is the character rule's
# and shows none.
CORRECTION = {
    DATED_SLUG: CORRECTED,
    "2026-13-45-topic": "topic",
    "2026-11-08-2026-11-09-topic": "2026-11-09-topic",
}
# Look-alikes the writer accepts today and must go on accepting: a date that is
# not a prefix, an unseparated run of digits, a date with unpadded parts, a
# too-long run of year digits, and a bare date, which carries no trailing dash so
# it is not the prefix of an id.
ACCEPTED = (
    "topic-2026",
    "v2026-11-08",
    "20261108-topic",
    "2026-1-8-topic",
    "12026-11-08-topic",
    "2026-11-08",
)

# The shape rule spelled here as well, to pin the package's constant to the shape
# the issue settled on rather than to itself (the pattern text itself is asserted in
# test_the_rule_is_shape_only_and_is_shared_by_both_validators, which reads it off
# the shipped file).
PREFIX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-")
# The two patterns decide.py hands both validators, spelled here so a direct call to
# either helper is driven with the same patterns the writer uses.
SLUG_PATTERN = r"[a-z0-9-]+"
ID_PATTERN = r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+"


def _fail_recorder() -> tuple[list[tuple[int, str, str]], object]:
    """A printer that records every line it was asked to print, and returns the code.

    The hint is recorded beside the headline because the corrected slug is printed in
    the hint: a refusal that named the slug and never showed the fix would be half a
    refusal.
    """
    calls: list[tuple[int, str, str]] = []

    def fail(code: int, message: str, hint: str | None = None) -> int:
        calls.append((code, message, hint or ""))
        return code

    return calls, fail


def _record_names(repo) -> list[str]:
    return sorted(p.name for p in (repo / "noni" / "decisions").glob("*.json"))


def _assert_untouched(repo) -> None:
    """Only the baseline record exists and nothing is staged or dirty."""
    assert _record_names(repo) == [f"{BASELINE_ID}.json"], _record_names(repo)
    assert _porcelain(repo, "noni/decisions") == ""


def _flags_kwargs(fail, **overrides) -> dict:
    """The keyword arguments ``build_record_flags`` reads, with the flag under test set."""
    from argparse import Namespace

    from noni import _decide_flags, ledger_schema

    args = Namespace(slug=overrides.pop("slug", "scheduler"),
                     date=overrides.pop("date", NEW_DATE),
                     question=["q1=Ship now?"],
                     option=["q1=ship it", "q1=wait"],
                     answer=["q1=ship it"],
                     single_option=False,
                     supersedes=overrides.pop("supersedes", None))
    assert not overrides, overrides

    def parse_pairs(values, flag):
        pairs = []
        for value in values:
            head, _sep, tail = value.partition("=")
            pairs.append((head, tail))
        return pairs, None

    def pair_refuse(flag, pairs, seen):
        return None if all(head in seen for head, _tail in pairs) else fail(2, f"{flag} orphan")

    def name_refuse(namespace, options_by_question):
        return None

    return {"args": args, "fail": fail, "exit_usage": 2,
            "slug_re": re.compile(SLUG_PATTERN), "id_re": re.compile(ID_PATTERN),
            "parse_pairs": parse_pairs, "pair_refuse": pair_refuse,
            "name_refuse": name_refuse,
            "build_questions": ledger_schema.build_questions,
            "unanswered_ids": ledger_schema.unanswered_ids}, _decide_flags


def test_a_slug_carrying_a_date_prefix_exits_two_and_writes_nothing(tmp_path):
    """AC1: the doubled-date run is refused at 2, names the slug, and shows the
    corrected slug. No file and no commit, in a tree that already holds a record."""
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", DATED_SLUG, "--date", NEW_DATE,
                *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    assert DATED_SLUG in combined, f"the refusal does not name the slug: {combined}"
    assert f"'{CORRECTED}'" in combined or f"{CORRECTED}" in combined, (
        f"the refusal does not show the corrected slug: {combined}")
    assert not _record_path(repo, DOUBLED_ID).exists()
    assert not _record_path(repo, f"{NEW_DATE}-{CORRECTED}").exists()
    assert _porcelain(repo, "noni/decisions") == ""


def test_every_date_prefixed_slug_is_refused_and_every_look_alike_accepted(tmp_path):
    """AC2/AC4: the four refused shapes exit 2 and the five accepted look-alikes
    still write their record.

    The pair of loops is what keeps the rule a rule: the refusals include a
    calendar-impossible date, so a check that consulted the calendar instead of
    the shape would accept it, and the accepted list includes a bare date and an
    unpadded one, so a wider regex would refuse them.
    """
    repo = _baseline_repo(tmp_path)
    for slug in REFUSED:
        proc = _run(repo, "--slug", slug, "--date", NEW_DATE,
                    *BASE, *QUESTION, *OPTIONS, *ANSWERED)
        assert proc.returncode == 2, f"slug {slug!r} accepted: {proc.returncode} {proc.stderr}"
        assert "slug" in proc.stderr, f"slug {slug!r} refused for another reason: {proc.stderr}"
    _assert_untouched(repo)

    for slug in ACCEPTED:
        proc = _run(repo, "--slug", slug, "--date", NEW_DATE,
                    *BASE, *QUESTION, *OPTIONS, *ANSWERED)
        assert proc.returncode == 0, f"slug {slug!r} refused: {proc.stderr}"
        assert _record_path(repo, f"{NEW_DATE}-{slug}").is_file(), slug
    # The plain slug behaves exactly as today.
    plain = _run(repo, "--slug", "plain", "--date", NEW_DATE,
                 *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert plain.returncode == 0, plain.stderr
    assert _record_path(repo, f"{NEW_DATE}-plain").is_file()


def test_the_refusal_is_a_slug_refusal_before_any_other_usage_rule(tmp_path):
    """The rule fires ahead of every other usage check, so the slug problem is
    what an operator hears about first.

    A date-prefixed slug combined with an impossible ``--date`` and an unanswered
    ``--supersedes`` still reports the slug, because the slug decides the filename
    and is the first statement of the assembly. The same run without the prefix
    reports the date instead, which is what shows the ordering rather than the
    message being asserted.
    """
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", DATED_SLUG, "--date", "2026-02-30",
                *BASE, *QUESTION, *OPTIONS,
                "--supersedes", BASELINE_ID)
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "slug" in proc.stderr, proc.stderr
    assert "--date" not in proc.stderr, proc.stderr
    assert _porcelain(repo, "noni/decisions") == ""

    unprefixed = _run(repo, "--slug", "topic", "--date", "2026-02-30",
                      *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert unprefixed.returncode == 2, unprefixed.stderr
    assert "--date" in unprefixed.stderr, unprefixed.stderr


def test_the_refusal_is_the_same_with_supersedes_and_with_no_commit(tmp_path):
    """AC3: neither ``--supersedes`` nor ``--no-commit`` changes the refusal.

    The supersede form is the expensive one: at baseline it wrote the doubled
    record and flipped the target's status in one commit, so this asserts the
    target's committed bytes are unchanged as well as no record. The no-commit
    form shares the validation chain but stops before git, so nothing may be
    staged or left in the working tree.
    """
    repo = _baseline_repo(tmp_path)
    target_rel = f"noni/decisions/{BASELINE_ID}.json"
    target_before = _git_e2(repo, "show", f"HEAD:{target_rel}").stdout
    before = _porcelain(repo)

    supersede = _run(repo, "--slug", DATED_SLUG, "--date", NEW_DATE,
                     *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                     "--supersedes", BASELINE_ID)
    assert supersede.returncode == 2, f"{supersede.returncode}: {supersede.stderr}"
    assert "slug" in supersede.stderr, supersede.stderr
    _assert_untouched(repo)
    assert _porcelain(repo) == before, "the supersede run staged or edited a path"
    # The committed target bytes are what they were: no status flip rode along with
    # the doubled record this run refused to write.
    assert _git_e2(repo, "show", f"HEAD:{target_rel}").stdout == target_before

    no_commit = _run(repo, "--slug", DATED_SLUG, "--date", NEW_DATE,
                     *BASE, *QUESTION, *OPTIONS, *ANSWERED, "--no-commit")
    assert no_commit.returncode == 2, f"{no_commit.returncode}: {no_commit.stderr}"
    assert "slug" in no_commit.stderr, no_commit.stderr
    _assert_untouched(repo)

    # The accepted controls, so the two refusals above are about the slug.
    plain_supersede = _run(repo, "--slug", "supersedes-baseline", "--date", NEW_DATE,
                           *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                           "--supersedes", BASELINE_ID)
    assert plain_supersede.returncode == 0, plain_supersede.stderr
    no_commit_ok = _run(repo, "--slug", "left-uncommitted", "--date", NEW_DATE,
                        *BASE, *QUESTION, *OPTIONS, *ANSWERED, "--no-commit")
    assert no_commit_ok.returncode == 0, no_commit_ok.stderr
    assert _record_path(repo, f"{NEW_DATE}-left-uncommitted").is_file()


def test_both_slug_validators_refuse_the_prefix_with_the_same_code():
    """The two entry points agree, asserted directly rather than only through ``decide``.

    ``build_record_flags`` and ``flag_refusals`` are separate calls on separate
    paths; one of them dropping the rule keeps the end-to-end run green, which is
    the drift this test exists for. Both are driven with the patterns decide.py
    hands them, and both refusals must name the slug and show the corrected one.
    """
    from noni._decide_flags import build_record_flags, refuse_name
    from noni._writer import flag_refusals
    from noni.ledger_schema import is_single_line

    for slug in REFUSED:
        calls, fail = _fail_recorder()
        kwargs, _module = _flags_kwargs(fail, slug=slug)
        assert build_record_flags(**kwargs) == 2, f"{slug}: assembly accepted it"
        assert calls and "slug" in calls[0][1], f"{slug}: assembly: {calls}"
        # The corrected slug is only shown where one exists: ``2026-11-08-`` has an
        # empty remainder, so the character rule answers that shape and shows none.
        if slug in CORRECTION:
            assert f"--slug {CORRECTION[slug]}" in " ".join(m for _c, _h, m in calls), (
                f"{slug}: the assembly does not show the corrected slug: {calls}")

        calls, fail = _fail_recorder()
        refused = flag_refusals(fail, 2, refuse_name, re.compile(SLUG_PATTERN),
                                slug, "scope", "asked-by", "Dana", None,
                                is_single_line, {"q1": ["a", "b"]}, False)
        assert refused == 2, f"{slug}: flag_refusals accepted it"
        assert calls and "slug" in calls[0][1], f"{slug}: flag_refusals: {calls}"
        if slug in CORRECTION:
            assert f"--slug {CORRECTION[slug]}" in " ".join(m for _c, _h, m in calls), (
                f"{slug}: flag_refusals does not show the corrected slug: {calls}")

    for slug in ACCEPTED + ("plain", "earned"):
        calls, fail = _fail_recorder()
        kwargs, _module = _flags_kwargs(fail, slug=slug)
        built = build_record_flags(**kwargs)
        assert not isinstance(built, int), f"{slug}: assembly refused it: {calls}"
        calls, fail = _fail_recorder()
        assert flag_refusals(fail, 2, refuse_name, re.compile(SLUG_PATTERN),
                             slug, "scope", "asked-by", "Dana", None,
                             is_single_line, {"q1": ["a", "b"]}, False) is None, (
            f"{slug}: flag_refusals refused an accepted slug")


def test_the_rule_is_shape_only_and_is_shared_by_both_validators():
    """The rule is one shape stated once, and it never consults the calendar.

    ``2026-13-45-topic`` is refused: a month 45 and a day 45 are as much a date
    prefix as a real one, since the writer would prefix them with its own date
    either way. And the shape lives in one module that both validators import, so
    the two entry points cannot drift apart -- which is checked here by reading
    the shipped source rather than by trusting two behavioural tests to agree.
    """
    from _harness import REPO

    from noni import _decide_flags

    shape = getattr(_decide_flags, "SLUG_DATE_PREFIX", None)
    assert shape is not None, "_decide_flags owns no date-prefix shape for the slug"
    assert shape.pattern == PREFIX.pattern == r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-", shape.pattern
    assert shape.match("2026-13-45-topic"), "the shape must not consult the calendar"
    assert shape.match(DATED_SLUG) and not shape.match("2026-11-08")

    writer = (REPO / "src" / "noni" / "_writer.py").read_text(encoding="utf-8")
    assert "_decide_flags" in writer, "the writer's slug rule no longer shares the shape"
    # The writer calls the shared rule rather than restating it: a copy of either
    # slug rule in the writer is how the two validators drift apart, and a dead
    # second copy is the same liability with a return above it.
    assert "refuse_slug" in writer, "the writer no longer calls the shared slug rule"
    assert "SLUG_DATE_PREFIX" not in writer, "the writer states its own date-prefix shape"
    assert "is not a slug" not in writer, "the writer states its own character-rule refusal"
    flags = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    assert flags.count('r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-"') == 1, (
        "the date-prefix shape is spelled more than once in the module that owns it")
    # The new rule must not reach for the calendar: parse_date and DATE_FLAG_RE
    # belong to --date, and the two slug rules live together in refuse_slug, which
    # is where the writer's second validator reads them from too.
    rule = flags.split("def refuse_slug(")[1].split("def refuse_name(")[0]
    assert rule, "the slug rules no longer live in one function"
    assert "parse_date" not in rule and "DATE_FLAG_RE" not in rule, (
        f"the slug rule consults the date rule: {rule}")
    assert "SLUG_DATE_PREFIX" in rule and "slug_re.fullmatch" in rule
    assert rule.count("already starts with a date") == 1, (
        "the date-prefix refusal is worded more than once in the rule that owns it")


def test_the_docs_pair_states_the_refusal_and_stays_within_its_caps():
    """The one page that owns slug refusals names it, and no capped page grew.

    ``references/decisions.md`` is the page that documents the slug rule today, so
    the refusal belongs in its ``id`` row; SKILL.md's exit-2 row and decide.py's
    docstring must stay in step with it. README and docs/QUICKSTART.md are at
    their caps and are not this rule's page, so the check is that they are
    untouched rather than that they mention it.
    """
    from _harness import REPO
    from decide_fixtures import SKILL

    reference = (REPO / "skills" / "steering-ledger" / "references" / "decisions.md")
    text = reference.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines()
            if line.startswith("| `id` |") and "YYYY-MM-DD-<slug>" in line]
    assert len(rows) == 1, rows
    row = rows[0]
    assert "YYYY-MM-DD-<slug>" in row
    assert "[a-z0-9-]+" in row
    assert "^[0-9]{4}-[0-9]{2}-[0-9]{2}-" in row, (
        f"the id row does not state the date-prefix rule: {row}")
    assert "2026-11-08-topic" in text, "the page does not name the bug's own slug"

    skill = SKILL.read_text(encoding="utf-8")
    two = [line for line in skill.splitlines() if line.startswith("| `2` |")]
    assert len(two) == 1, two
    assert "date" in two[0].lower(), f"SKILL.md's exit-2 row omits the date prefix: {two[0]}"
    assert skill.count("\n") <= 400, f"SKILL.md is {skill.count(chr(10))} lines"

    doc = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    assert "already starting with a date" in doc, (
        "decide.py's docstring does not list the date-prefix refusal")
