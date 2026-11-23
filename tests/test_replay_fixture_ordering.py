"""The replay fixture's generator writes its identity into its own repository only.

``tests/fixtures/replay-repo/generate.sh`` pins an identity with three
``git config`` lines. That is exactly the shape that leaked the fixture identity
into this repository's shared ``.git/config`` (issue #220): ``git config`` on a
directory that is not a repository does not fail, it walks up and writes into the
nearest enclosing one, so a generator whose ``cd`` into its own tree came *before*
its ``git init`` ran its config lines with the cwd still at the caller's output
directory -- a scratch tree that, in the period the leak happened, sat under a
checkout.

What the guard in ``tests/harness_git.py`` cannot reach is this file: it is shell,
launched as a script, and the leak it caused was into a tree the Python harness
never touched. So the ordering is what is asserted here, plus the outcome it is
there to protect.

The record content itself (the four ``noni/decisions/*.json`` files, their dates
and ids) is ``tests/test_replay.py``'s business and is deliberately not restated
here: this module asks only where the config lines run, and whether the generator
still produces a repository whose config holds its own identity.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "replay-repo"
GENERATE = FIXTURES / "generate.sh"

# The identity the generator pins, and the key each line sets. Both are read back
# from the generated repository's own config: the assertion is on where the lines
# landed, and a generator that wrote none of them would fail the replay suite -- so
# the pair together says "its own config, and no other".
_GENERATED_IDENTITY = (("user.name", "Replay Fixture"),
                      ("user.email", "replay@fixture.invalid"))


def _generate(output_dir: Path) -> Path:
    """Run the committed generator into ``output_dir``, returning the repo it wrote."""
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["bash", str(GENERATE), str(output_dir)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"generate.sh failed ({proc.returncode})\nstdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}")
    repo = output_dir / "replay-repo"
    assert repo.is_dir(), f"the generator wrote no repository at {repo}"
    return repo


def _config_lines() -> list[str]:
    """The generator's own lines, so the ordering claim is read off the file."""
    return GENERATE.read_text(encoding="utf-8").splitlines()


def _first_line_matching(fragment: str) -> int:
    """The 1-based number of the first *command* line holding ``fragment``.

    A fragment is written with a leading ``^`` because a command is what is being
    located: the generator's prose comments quote ``git config`` too, and a locator
    that matched a comment would report an ordering between a sentence and a command.
    Matching the start of the line is also what makes the answer unambiguous when
    several commands carry the same words.

    Missing rather than ``-1``: an assertion that the init precedes the config lines
    has to be able to say that one of them is simply gone, or a generator that
    dropped its ``git init`` would pass by having nothing to compare against.
    """
    assert fragment.startswith("^"), f"a locator fragment must name a command line: {fragment!r}"
    body = fragment[1:]
    for index, line in enumerate(_config_lines(), start=1):
        if line.startswith(body):
            return index
    raise AssertionError(f"generate.sh has no command line starting with {body!r}: "
                         f"{GENERATE}")


def test_generate_inits_its_repository_before_any_config_line():
    """``git init`` names the repository, and every config line comes after it.

    The ordering is the whole fix (PM ruling 1): before it, the file read ``cd
    "$REPO"`` then ``git init -q``, and the config lines ran while the cwd was the
    caller's ``$OUT`` -- a plain directory that git answers for by walking up. The
    init now names the repository itself, so the config lines have a repository to
    write into whatever the cwd is.
    """
    init = _first_line_matching("^git init")
    first_config = min(_first_line_matching(f"^git config {key} ")
                       for key, _ in _GENERATED_IDENTITY)
    assert init < first_config, (
        f"a git config line runs at line {first_config}, before the git init at "
        f"line {init}: it would write the nearest enclosing repository")
    assert '"$REPO"' in _config_lines()[init - 1], (
        "the init must name the repository it creates rather than rely on the cwd, "
        f"or the ordering above proves nothing: {_config_lines()[init - 1]!r}")


def test_generate_lets_nothing_but_its_own_cd_run_before_the_config_lines():
    """Between the init and the identity lines, only the generator's own ``cd``.

    The rule the leak taught is that a ``git config`` writes into whatever repository
    encloses the *current directory* when the target is not a repository. The init
    now names its own repository, so the ordering above holds whatever the cwd; the
    ``cd "$REPO"`` is what makes the config lines land in the fixture's own tree and
    not the caller's. Anything else in between -- a second ``cd``, a ``cd`` to a
    placeholder, a command of its own -- would move the writes somewhere the
    generator does not own, which is the hazard again in a form nobody intended. The
    blank lines, the comments, and the ceiling export that bounds the walk are the
    other things allowed there.
    """
    init = _first_line_matching("^git init")
    first_config = min(_first_line_matching(f"^git config {key} ")
                       for key, _ in _GENERATED_IDENTITY)
    between = [line.strip() for line in _config_lines()[init:first_config - 1]]
    for line in between:
        assert not line or line.startswith("#") or \
            line.startswith("export GIT_CEILING_DIRECTORIES") or \
            line == 'cd "$REPO"', (
            f"an unexpected command runs between the git init (line {init}) and the "
            f"config lines (line {first_config}): {line!r}")
    assert 'cd "$REPO"' in between, (
        "the generator never cds into the repository it made, so its identity lines "
        "would be written wherever the caller's cwd points")


def test_generated_repo_holds_its_identity_and_the_enclosing_repo_does_not(tmp_path):
    """The outcome the ordering protects, measured on a planted enclosing repo.

    The generator is run into a plain directory inside a real repository, and both
    halves are asserted: the generated repository's own config carries the identity
    the generator pins, and the enclosing repository's config is byte-identical
    afterwards. That second half is the bug, expressed as an assertion -- it is the
    check that would have reddened before the ordering was fixed, and it fails again
    if someone moves the ``cd`` back in front of the ``git init``.
    """
    enclosing = tmp_path / "enclosing"
    enclosing.mkdir()
    for argv in (["init", "-q", "-b", "main"],
                 ["config", "user.name", "Witness"],
                 ["config", "user.email", "witness@example.invalid"]):
        subprocess.run(["git", "-C", str(enclosing), *argv], check=True,
                       capture_output=True, text=True, timeout=60)
    witness = enclosing / ".git" / "config"
    before = witness.read_bytes()

    out_dir = enclosing / "scratch" / "replay-out"
    repo = _generate(out_dir)

    for key, value in _GENERATED_IDENTITY:
        shown = subprocess.run(["git", "-C", str(repo), "config", "--local", key],
                               capture_output=True, text=True, timeout=60)
        assert shown.returncode == 0, f"{key} not set in the generated repo: {shown.stderr}"
        assert shown.stdout.strip() == value, f"{key}: {shown.stdout.strip()!r}"

    assert witness.read_bytes() == before, (
        f"the generator wrote the enclosing repository's config: {witness}\n"
        f"{witness.read_text(encoding='utf-8', errors='replace')}")


def test_generated_repo_is_a_repository_of_its_own_top_level(tmp_path):
    """The generated tree passes the harness's own containment check.

    The generator is the one config writer the Python guard cannot wrap, so this is
    where the two halves meet: the tree it produces must be one the harness would
    accept as its own repository, which is the precondition every runner asserts and
    the reason a fixture the harness cannot check still has to be a repository.
    """
    from harness_git import assert_own_repo_top

    repo = _generate(tmp_path / "out")
    assert assert_own_repo_top(repo) == repo.resolve()


def test_generator_is_a_parsing_script_and_the_locator_says_so(tmp_path):
    """The file is a script with the shebang the size gate reads it by, and the
    line locator fails rather than silently reporting an ordering that is not there.

    A generator that lost its shebang would still run under ``bash <path>`` and be
    counted as data rather than source, so the size test would stop measuring it
    while it stayed load-bearing for the replay suite. The locator's refusal is the
    other half: an ordering assertion whose subject has been deleted must fail, not
    compare against a line that does not exist.
    """
    assert GENERATE.is_file(), f"missing generator: {GENERATE}"
    assert _config_lines()[0].startswith("#!"), (
        "generate.sh has no shebang, so it is exempt from the source-file size gate")
    checked = subprocess.run(["bash", "-n", str(GENERATE)],
                             capture_output=True, text=True, timeout=60)
    assert checked.returncode == 0, f"generate.sh does not parse: {checked.stderr}"
    with pytest.raises(AssertionError, match="no command line starting with"):
        _first_line_matching('^git config "user.nickname"')
