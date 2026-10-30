"""order.py's usage and exit table, checked against the code.

Extracted from the order writer suite: the docstring contract and the argument
surface the writer actually accepts."""

from order_fixtures import (
    BASELINE_ID,
    NOW,
    _entry,
    _issues,
    _order,
    _order_path,
    _repo,
    _seed,
)


def test_an_unknown_subcommand_exits_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "shuffle", "7", "--now", NOW)
    assert proc.returncode == 2
    assert "add, move, remove or confirm" in proc.stderr
    assert not _order_path(repo).exists()


def test_a_non_positive_issue_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for token in ("0", "-3", "seven", "1.5", ""):
        proc = _order(repo, "add", token, "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 2, f"{token!r}: {proc.returncode} {proc.stderr}"
        assert "positive integer" in proc.stderr or "expected one argument" in proc.stderr


def test_a_non_ascii_digit_issue_number_exits_two(tmp_path):
    """``str.isdigit`` is True for characters ``int`` will not accept.

    A superscript two is a "digit" to ``isdigit`` and a ``ValueError`` to ``int``,
    so the issue token used to reach ``int(token)`` past the digit check and the
    writer died with a traceback instead of a usage refusal. The token is refused
    before the artifact is opened, and nothing is written.
    """
    repo = _repo(tmp_path)
    for token in ("\u00b2", "\u0667"):
        proc = _order(repo, "add", token, "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 2, f"{token!r}: {proc.returncode} {proc.stderr}"
        assert "positive integer" in proc.stderr, f"{token!r}: {proc.stderr}"
        assert "Traceback" not in proc.stderr, f"{token!r}: {proc.stderr}"
        assert not _order_path(repo).exists(), f"{token!r} wrote the artifact"


def test_a_non_ascii_digit_position_exits_two(tmp_path):
    """``--at`` and ``--to`` obey the token rule an issue number obeys.

    A position is read with the same ``int`` call, so a superscript digit reached
    it past any gate that stopped at ``isdigit`` and the writer raised instead of
    refusing. The two flags are refused with the position's own wording, on the
    order they were handed, and nothing is written.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    for token in ("\u00b2", "\u0667"):
        add = _order(repo, "add", "7", "--at", token, "--decision", BASELINE_ID,
                     "--now", NOW)
        assert add.returncode == 2, f"--at {token!r}: {add.returncode} {add.stderr}"
        assert "--at" in add.stderr and "position" in add.stderr, add.stderr
        assert "Traceback" not in add.stderr, add.stderr
        move = _order(repo, "move", "1", "--to", token, "--now", NOW)
        assert move.returncode == 2, f"--to {token!r}: {move.returncode} {move.stderr}"
        assert "--to" in move.stderr and "position" in move.stderr, move.stderr
        assert "Traceback" not in move.stderr, move.stderr
        assert _issues(repo) == [1, 2], f"{token!r} changed the order"


def test_a_missing_issue_number_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for verb in ("add", "move", "remove"):
        proc = _order(repo, verb, "--now", NOW) if verb != "move" else _order(
            repo, verb, "--to", "1", "--now", NOW)
        assert proc.returncode == 2, f"{verb}: {proc.returncode} {proc.stderr}"
        assert "needs an issue number" in proc.stderr or "expected one argument" in proc.stderr


def test_a_position_outside_the_order_exits_two(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    for flag, value in (("--to", "0"), ("--to", "3"), ("--to", "top")):
        proc = _order(repo, "move", "1", flag, value, "--now", NOW)
        assert proc.returncode == 2, f"{flag} {value}: {proc.returncode}"
        assert _issues(repo) == [1, 2]


def test_a_flag_passed_to_the_wrong_verb_exits_two(tmp_path):
    """A flag that means nothing for the verb it came with is a usage error, not
    a hint the run quietly ignores: each of the three mis-placements is named."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    cases = [
        ("move", "1", "--to", "1", "--at", "1", "--now", NOW),
        ("remove", "1", "--to", "1", "--now", NOW),
        ("confirm", "--at", "1", "--now", NOW),
        ("confirm", "1", "--decision", BASELINE_ID, "--now", NOW),
    ]
    for argv in cases:
        proc = _order(repo, *argv)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert "belongs to" in proc.stderr, f"{argv}: {proc.stderr}"


def test_a_now_that_is_not_a_utc_timestamp_exits_two(tmp_path):
    repo = _repo(tmp_path)
    for bad in ("yesterday", "2026-13-45T00:00:00Z", "2026-10-27T12:00:00"):
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", bad)
        assert proc.returncode == 2, f"{bad!r}: {proc.returncode}"
        assert "--now" in proc.stderr
    assert not _order_path(repo).exists()


def test_an_argparse_failure_exits_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "--not-a-flag")
    assert proc.returncode == 2
    proc = _order(repo)  # --repo is required
    assert proc.returncode == 2


def test_a_repo_that_is_not_a_directory_is_a_fault(tmp_path):
    """A --repo naming no directory is refused before the artifact is read or the
    decision looked up, and nothing is created under the path.

    The refusal is the state-root refusal every other writer makes (exit 2, the
    code a wrong path is: an argument the caller passed, not a fault of the tree
    and not a refusal of the order), and it fires ahead of the citation check so
    the message names the path rather than a record the caller may have spelled
    correctly all along. Nothing is written either way: the run created no tree
    it refused to write into.
    """
    proc = _order(tmp_path / "no-such-repo", "add", "7", "--decision", BASELINE_ID,
                  "--now", NOW)
    assert proc.returncode == 2, proc.returncode
    assert "--repo" in proc.stderr, proc.stderr
    assert "is not a directory" in proc.stderr, proc.stderr
    assert not (tmp_path / "no-such-repo").exists(), "the writer created a tree it refused"""
