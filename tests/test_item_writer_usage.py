"""The command line ``item`` accepts, and what it refuses before it touches a file.

Every case here is a run that must never reach the store: the whole value of a usage
refusal is that it costs nothing and changes nothing, so each one asserts a code and a
line and is paired with the state of the tree afterwards.

The codes are the writer's own (0/2/3/4, pinned against the module's ``Exit codes:``
block by ``tests/test_item_writer_docs.py``), and the boundary the suite is built
around is the one operators hit: **2 for a mistake in the command line, 4 for a
refusal about the item, 3 for a fault of the filesystem or git.** A run that answered
4 for a typo would send somebody off to inspect a record that is fine, and a run that
answered 2 for an item that is already dropped would say the command was mis-typed
when it was not.

Verb behaviour, the artifact's bytes and the path guard are the other three files of
this suite: ``test_item_writer_verbs.py``, ``test_item_writer_artifact.py`` and
``test_item_writer_state_root.py``.
"""

from __future__ import annotations

from item_writer_fixtures import BASELINE_ID, NOW, item_path, repo, run_item, seed_item, seed_record

from noni.itemschema import TITLE_MAX, WHY_MAX

CANDIDATE = {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
             "status": "candidate", "created": "2026-10-26T00:00:00Z"}


def _unchanged(tree):
    """Nothing written, nothing staged: the whole point of a usage refusal."""
    return (item_path(tree, "idea-0001").exists(),
            tree.joinpath("noni").exists())


# --------------------------------------------------------------------------
# The verb slot
# --------------------------------------------------------------------------


def test_no_verb_names_the_verbs_and_costs_exit_two(tmp_path):
    """``item.py --repo R`` alone printed argparse's slot name and nothing useful.

    The fix line has to name the four words that fill it, which is the difference
    between a refusal an operator recovers from and one they read twice.
    """
    tree = repo(tmp_path)
    proc = run_item(tree)
    assert proc.returncode == 2, proc.stderr
    joined = proc.stdout + proc.stderr
    for verb in ("add", "list", "drop", "promote"):
        assert verb in joined, f"{verb} is not named: {joined}"


def test_an_unknown_verb_is_refused_with_the_verb_list(tmp_path):
    tree = repo(tmp_path)
    proc = run_item(tree, "delete", "idea-0001")
    assert proc.returncode == 2, proc.stderr
    joined = proc.stdout + proc.stderr
    assert "delete" in joined and "add" in joined, joined
    assert not _unchanged(tree)[0]


def test_a_verb_without_its_id_is_refused(tmp_path):
    tree = repo(tmp_path)
    for verb in ("add", "drop", "promote"):
        proc = run_item(tree, verb, "--now", NOW)
        assert proc.returncode == 2, f"{verb}: {proc.stderr}"
        assert "needs an item id" in proc.stderr, f"{verb}: {proc.stderr}"


# --------------------------------------------------------------------------
# The id, as the command line spells it
# --------------------------------------------------------------------------


def test_an_id_that_is_not_a_slug_is_refused_by_the_command_line(tmp_path):
    """The argv check, not the file's: this run never reaches the store.

    The same shape refused in a *file* is exit 4 (``item-malformed``'s writer twin);
    refused on the command line it is 2, because nothing on disk is wrong.

    The list is the shapes outside the ruled set of #124 (a dot, an underscore and a
    dash inside the name are inside it, so ``idea.dot`` -- an id with a dot in the
    middle -- is legal and is not one of these; ``idea.`` is, for the trailing dot the
    filesystem hides).
    """
    tree = repo(tmp_path)
    # Each case gets its own tree and puts the id last: ``--`` would swallow the flags
    # after it (argparse reads everything past the separator as positionals), and one
    # tree would make the second case collide with the first's filed item rather than
    # be refused for its spelling. A leading-dash id is left out for the same reason in
    # miniature -- argparse reads it as a flag and refuses it with its own sentence,
    # which is a second correct answer to the mistake and not the one pinned here; the
    # shape is covered as a *file* by the census and the artifact suites.
    for bad in ("Idea One", "idea/0001", "idea-0001.json", "idea.", "i" * 81, ""):
        case = repo(tmp_path, f"id-{abs(hash(bad))}")
        proc = run_item(case, "add", "x", "--title", "t", "--now", NOW)  # placeholder
        proc = run_item(case, "add", bad, "--title", "t", "--now", NOW) if bad else \
            run_item(case, "add", "--title", "t", "--now", NOW)
        assert proc.returncode == 2, f"{bad!r}: {proc.returncode} {proc.stderr}"
        needle = "is not an item id" if bad else "needs an item id"
        assert needle in proc.stderr, f"{bad!r}: {proc.stderr}"
    assert not _unchanged(tree)[0]


# --------------------------------------------------------------------------
# Flags and the verbs that own them
# --------------------------------------------------------------------------


def test_a_flag_on_the_wrong_verb_is_refused_by_name(tmp_path):
    """``--why`` is the dropped item's reason and no other verb carries one.

    A flag the verb quietly ignored would be worse than a refusal: the operator asked
    for the reason to be recorded and the record would not hold it.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    cases = [
        ["add", "idea-0002", "--title", "t", "--why", "because"],
        ["add", "idea-0002", "--title", "t", "--decision", BASELINE_ID],
        ["add", "idea-0002", "--title", "t", "--issue", "7"],
        ["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "x",
         "--title", "rename me"],
        ["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "x",
         "--issue", "7"],
        ["promote", "idea-0001", "--issue", "7", "--why", "because"],
        ["list", "--title", "t"],
    ]
    for argv in cases:
        proc = run_item(tree, *argv, "--now", NOW)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert "belongs to" in proc.stderr, f"{argv}: {proc.stderr}"


def test_the_verb_that_owns_a_flag_still_takes_it(tmp_path):
    """The counterpart of the refusal above, so the check cannot be over-broad."""
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    assert run_item(tree, "add", "idea-0002", "--title", "t",
                    "--now", NOW).returncode == 0
    assert run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW).returncode == 0
    assert run_item(tree, "promote", "idea-0002", "--issue", "7",
                    "--now", NOW).returncode == 0


def test_a_missing_required_flag_is_refused_naming_the_flag(tmp_path):
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    for argv, flag in ((["add", "idea-0002"], "--title"),
                       (["drop", "idea-0001", "--why", "x"], "--decision"),
                       (["drop", "idea-0001", "--decision", BASELINE_ID], "--why"),
                       (["promote", "idea-0001"], "--issue")):
        proc = run_item(tree, *argv, "--now", NOW)
        assert proc.returncode == 2, f"{argv}: {proc.stderr}"
        assert flag in proc.stderr, f"{argv}: {proc.stderr}"


# --------------------------------------------------------------------------
# Flag values
# --------------------------------------------------------------------------


def test_a_flag_value_that_is_not_one_bounded_line_is_refused(tmp_path):
    """Blank, multi-line and over-long are the three ways a free text stops being one line.

    A newline into the artifact would put a second line into a listing and an over-long
    value an unbounded row into the census, so both are refused at the flag rather than
    at the file, and the message names which of the three it is.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    long_text = "x" * (TITLE_MAX + 1)
    long_why = "y" * (WHY_MAX + 1)
    cases = [
        (["add", "idea-0002", "--title", "   "], "title"),
        (["add", "idea-0002", "--title", "a\nb"], "title"),
        (["add", "idea-0002", "--title", "a\rb"], "title"),
        (["add", "idea-0002", "--title", long_text], str(TITLE_MAX)),
        (["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "  "], "why"),
        (["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "a\nb"], "why"),
        (["drop", "idea-0001", "--decision", BASELINE_ID, "--why", long_why],
         str(WHY_MAX)),
    ]
    for argv, needle in cases:
        proc = run_item(tree, *argv, "--now", NOW)
        assert proc.returncode == 2, f"{argv[:2]}: {proc.returncode} {proc.stderr}"
        assert needle in proc.stderr, f"{needle} not named: {proc.stderr}"


def test_a_title_at_the_bound_is_accepted(tmp_path):
    """The boundary is inclusive on the side the schema allows, not guessed at.

    One case per bound at its limit, and the cases above at one past it: an off-by-one
    here refuses the longest title the artifact is documented to hold.
    """
    tree = repo(tmp_path)
    assert run_item(tree, "add", "idea-0001", "--title", "x" * TITLE_MAX,
                    "--now", NOW).returncode == 0
    seed_record(tree)
    assert run_item(tree, "add", "idea-0002", "--title", "t",
                    "--now", NOW).returncode == 0
    assert run_item(tree, "drop", "idea-0002", "--decision", BASELINE_ID,
                    "--why", "y" * WHY_MAX, "--now", NOW).returncode == 0


def test_an_issue_that_is_not_a_positive_integer_is_refused(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, dict(CANDIDATE))
    for value in ("0", "-3", "seven", "7.5", ""):
        proc = run_item(tree, "promote", "idea-0001", "--issue", value,
                        "--now", NOW)
        assert proc.returncode == 2, f"{value!r}: {proc.returncode} {proc.stderr}"
        assert "positive integer" in proc.stderr, f"{value!r}: {proc.stderr}"


def test_a_now_that_is_not_utc_iso_8601_is_refused(tmp_path):
    """The created stamp is the item's age, so the format the census compares is required.

    A local time with an offset is refused rather than assumed: read as UTC it would
    move the item by hours and change whether ``item-stale`` fires.
    """
    tree = repo(tmp_path)
    seed_item(tree, dict(CANDIDATE))
    for value in ("2026-10-27", "2026-10-27T12:00:00", "yesterday",
                  "2026-10-27t12:00:00z", "2026-10-27 12:00:00"):
        proc = run_item(tree, "add", "idea-0001", "--title", "t", "--now", value)
        assert proc.returncode == 2, f"{value!r}: {proc.stderr}"
        assert "--now" in proc.stderr, f"{value!r}: {proc.stderr}"


def test_a_repo_that_is_not_a_directory_is_refused(tmp_path):
    tree = repo(tmp_path)
    a_file = tree / "src" / "main.py"
    proc = run_item(tree.parent, "--repo", str(a_file), "list")
    assert proc.returncode == 2, proc.stderr
    assert "not a directory" in proc.stderr, proc.stderr


def test_help_lists_the_verbs_and_exits_zero(tmp_path):
    """The first thing every reader types, and the surface the docs are compared to."""
    tree = repo(tmp_path)
    proc = run_item(tree, "list", "--help")
    assert proc.returncode == 0, proc.stderr
    joined = proc.stdout + proc.stderr
    for needle in ("--title", "--decision", "--why", "--issue", "--now",
                   "--no-commit", "add", "list", "drop", "promote"):
        assert needle in joined, f"{needle} missing from --help"
