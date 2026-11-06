"""What the two shell census wrappers accept, what they refuse, and what they hand on.

``skills/steering-ledger/scripts/census.sh`` execs the in-place ``census.py``
beside it, which calls ``census_wrapper.run_ledger``; the sessions skill's pair
reaches ``run_sessions`` the same way. Those two functions are the wrappers'
whole mind: one allowlist of options, two shape checks over the directory, and
one call (``src/noni/census_wrapper.py``, ``run``). Everything the wrappers do
not list is refused before the census is reached -- which is the whole design,
and the reason the cases below are a table rather than a conversation about
what a token means.

The allowlist is ``--json``, ``--strict`` and ``--now`` (in its ``--now VALUE``
and ``--now=VALUE`` forms) beside the one directory, plus ``--help``/``-h`` as
the whole command line. Each refused token is refused because it is not on that
list, so the set of refused tokens is fixed by the list and not by how well the
wrapper recognises it: an option the census gains next year, a prefix of a flag
that exists, a bare ``--`` and a single-dash token are all refused on the one
rule, and none of them reaches the census. A pass-through that forwarded what
it could not classify is the false clean this design replaced -- a takeover of
``--ledger`` by the caller read the tree it named and exited 0 where the plain
run failed.

Each case drives an entry point directly and asserts the three things every
refusal owes: the census's usage code, an empty stdout, and a census that was
never called (the doubles in ``census_probe_doubles`` record the argv they were
handed, so a census that ran is visible even when it printed nothing). The
pass-through half of the contract is the other side of that: the allowed forms
arrive at the census spelled as the caller spelled them.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from census_probe_doubles import _RecordedCensusCall, _RecordedSessionsCall
from census_wrapper import _VALUE_FLAG, EXIT_USAGE, run_ledger, run_sessions

# The broken-record fixtures of the two registers, each with the code its class wins
# the run by: an unparseable ledger record is `ledger-record` (10) and a wrongly
# named register file is `session-malformed` (32).
_SESSIONS_BROKEN_NAME = "not-an-allocated-session.md"
_BROKEN_RECORD = {"decisions": ("2026-10-02-broken.json", "{ not json\n", 10),
                  "sessions": (_SESSIONS_BROKEN_NAME, "- identity: x\n", 32)}

# Each entry point, with the noun its usage line uses, the function a caller
# reaches it through, and the census double that reads its command line: one
# table, so the cases below drive both wrappers and cannot quietly cover only the
# ledger one.
_WRAPPERS = ((run_ledger, "decisions", _RecordedCensusCall),
             (run_sessions, "sessions", _RecordedSessionsCall))

# The same table without the double, for the cases that run the real census.
_WRAPPERS_REAL = ((run, noun) for run, noun, _double in _WRAPPERS)

# The options a wrapper takes, in each form the docs promise, paired with what
# the recording double keeps of them: the caller's own tokens, in the order
# typed, after the wrapper's own group ``--only`` pairs (which belong to the
# check contract and are pinned in test_census_check_contract.py).
# Each form is (the caller's own tokens, what the recording double keeps of
# them). The directory is supplied by the case -- it is not one of the caller's
# options -- so the `[]` row below is a bare `<dir>` run, and `<dir>` inside a
# row stands for the directory typed between the flags around it.
_ALLOWED_FORMS = (
    # Each row is (the tokens the caller types after the directory, what the
    # recording double keeps of them). The directory itself is supplied by the
    # case, so no row names it twice: the point is the options, in whatever order
    # the caller interleaved them, reaching the census as typed.
    ([], []),
    (["--json"], ["--json"]),
    (["--strict"], ["--strict"]),
    (["--now", "2026-01-01T00:00:00+00:00"], ["--now", "2026-01-01T00:00:00+00:00"]),
    (["--now=2026-01-01T00:00:00+00:00"], ["--now=2026-01-01T00:00:00+00:00"]),
    (["--json", "--strict", "--now", "2026-01-01T00:00:00+00:00"],
     ["--json", "--strict", "--now", "2026-01-01T00:00:00+00:00"]),
    (["--strict", "--json"], ["--strict", "--json"]),
)

# Representative tokens outside the allowlist, each chosen for a way the old
# hand-written argument walk could get one wrong rather than for volume: the `=`
# form of a state-path flag and of an unknown one, a prefix of each, a filter
# with and without its value, a single-dash token, the end-of-options marker,
# and `--help` typed beside a directory rather than as the whole line. A token
# is refused because it is not on the list, so these are samples of one rule,
# not a list the wrapper consults.
_REFUSED_TOKENS = (
    "--ledger=/tmp/elsewhere", "--led=/tmp/elsewhere", "--sess=/tmp/elsewhere",
    "--repo=/tmp/elsewhere", "--re=/tmp/elsewhere",
    "--ledger", "--sessions", "--repo", "--led", "--sess", "--re",
    "--only", "--only=ledger-record", "--skip", "--skip=hygiene",
    "-h", "-x", "-", "--", "--nope", "--nope=1", "--help",
)

# ``--now`` is on the allowlist, so it is not refused for being unlisted -- but it
# is an option that takes a value, and a ``--now`` with no value after it is refused
# all the same (see the case below): it has nothing to hand on. The last two rows
# are the same fault one token further along: the token after ``--now`` is another
# option, so there is no stamp there either, and taking it as one is what let the
# line reach the census's parser instead of being refused here.
_TRAILING_NOW = (["DIR", "--now"], ["--now"],
                 ["DIR", "--json", "--now", "--strict"],
                 ["DIR", "--json", "--now", "--nope"],
                 ["DIR", "--now", "--strict"], ["DIR", "--now", "--nope"])


def _run_with(run, argv: list[str]) -> tuple[int, str, str]:
    """``run(argv)`` for either entry point, with both streams captured.

    The refusal path prints and returns; a census that refuses on its own prints
    and exits through argparse, so the call is guarded the way a caller at a
    shell is guarded and the test reads the code and the text either way.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = run(argv)
    except SystemExit as exc:  # argparse's own exit, which is the refusal
        rc = exc.code
    return rc, out.getvalue(), err.getvalue()


def _register(tmp_path: Path, noun: str) -> str:
    """One state directory either wrapper will accept, laid out for either entry point."""
    directory = tmp_path / "state" / "noni" / noun
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


@pytest.fixture
def paths(tmp_path):
    """A ledger the census could census, plus the shapes it must refuse.

    The real directory is what makes a refusal mean something: with no directory
    a run could have read, exit 2 and no rows would also be the shape of a census
    that found nothing to report.
    """
    good = tmp_path / "state" / "noni" / "decisions"
    good.mkdir(parents=True)
    as_file = tmp_path / "state" / "noni" / "decisions-as-a-file"
    as_file.write_text("i am a file, not a ledger directory\n", encoding="utf-8")
    dangling = tmp_path / "state" / "noni" / "decisions-link"
    dangling.symlink_to(tmp_path / "state" / "elsewhere" / "decisions")
    assert dangling.is_symlink() and not dangling.exists(), (
        "the fixture is not a dangling link, so the case proves nothing")
    extra = tmp_path / "other" / "noni" / "decisions"
    extra.mkdir(parents=True)
    return {"good": good, "as_file": as_file, "dangling": dangling, "extra": extra}


# --- the allowlist passes through ----------------------------------------------

@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
@pytest.mark.parametrize("options,expected", _ALLOWED_FORMS,
                         ids=("none", "json", "strict", "now", "now-equals",
                              "all", "reversed"))
def test_an_allowed_option_reaches_the_census_as_typed(tmp_path, run, noun, double,
                                                      options, expected, monkeypatch):
    """Every allowed form runs the census, and the census is handed those bytes.

    The positive half of the allowlist, without which every refusal below would
    also be the shape of a wrapper that refused everything. The caller's tokens
    arrive in the order they were typed and unchanged: ``--now`` keeps both of
    its forms and ``--json`` / ``--strict`` stay the census's flags with the
    census's verdicts. An option typed after the directory is still an option and
    not a second directory: the walk classifies tokens, not positions, so the
    flags a caller interleaved around the one directory reach the census in the
    order they typed them.
    """
    directory = _register(tmp_path, noun)
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    argv = [directory, *options]
    rc, out, err = _run_with(run, argv)
    assert rc == 0, f"{argv}: the allowed form was refused: rc={rc}\n{err}"
    assert out == "" and err == "", f"printed alongside the census: {out}{err}"
    assert recorded.calls == [(directory, expected)], (
        f"the census was handed something else: {recorded.calls}")


@pytest.mark.parametrize("run", (run_ledger, run_sessions),
                         ids=("ledger", "sessions"))
@pytest.mark.parametrize("token", ("--help", "-h"))
def test_the_help_token_alone_prints_the_wrapper_help_and_censuses_nothing(
        run, token, capsys):
    """``census.sh --help`` is the wrapper's own text, at the clean code.

    Help is not a census option, so it is allowed only as the whole command
    line; the case beside a directory is in the refused table below.
    """
    rc = run([token])
    out = capsys.readouterr().out
    assert rc == 0, f"{token} alone: rc={rc}"
    assert "census" in out.lower() and out.strip() != "", f"{token}: no help: {out!r}"


# --- everything else is refused, and the census never runs ---------------------

@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
@pytest.mark.parametrize("token", _REFUSED_TOKENS)
def test_a_token_off_the_allowlist_is_refused_and_the_census_never_runs(
        tmp_path, run, noun, double, token, monkeypatch):
    """One unlisted token, in each position a caller can type it, is exit 2.

    The refusal is one line naming the token as typed and pointing at the tool
    that does take it, stdout is empty, and the double records no call: a
    wrapper that forwarded what it could not classify ran a census the caller
    never asked for and returned that run's exit code, which is how a ``--ledger``
    takeover once printed a clean 0 for a ledger that fails at 10.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    directory = _register(tmp_path, noun)
    for argv in ([directory, token], [token, directory],
                 [directory, "--json", token],
                 [directory, token, "/tmp/elsewhere"]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: a refused run printed a report: {out}"
        assert token in err, f"{argv}: the refusal must name the token: {err}"
        assert "noni census" in err, (
            f"{argv}: the refusal must say where the option lives: {err}")
    assert recorded.calls == [], (
        f"the census ran for a refused token: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
@pytest.mark.parametrize("argv", _TRAILING_NOW,
                         ids=("dir-then-now", "now-alone", "json-now-strict",
                              "json-now-nope", "now-then-strict", "now-then-nope"))
def test_a_trailing_now_with_no_value_is_refused_and_the_census_never_runs(
        tmp_path, run, noun, double, argv, monkeypatch):
    """``census.sh DIR --now`` is exit 2 naming ``--now``, not an IndexError.

    ``--now`` is on the allowlist, so nothing refused it before: the option walk
    stepped past the end of the line and the option filter indexed a token that
    was never typed, so the caller got a traceback at the code a real census
    failure answers at -- indistinguishable to a script from the census refusing a
    malformed stamp. The refusal is the wrapper's own usage line, the census is
    never reached, and the code is the usage code rather than 1.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    directory = _register(tmp_path, noun)
    typed = [directory if token == "DIR" else token for token in argv]
    rc, out, err = _run_with(run, typed)
    assert rc == EXIT_USAGE, f"{typed}: rc={rc} (a traceback exits 1)\n{err}"
    assert out == "", f"{typed}: a refused run printed a report: {out}"
    assert _VALUE_FLAG in err, f"{typed}: the refusal must name --now: {err}"
    assert "needs a value" in err, f"{typed}: the reason: {err}"
    assert "Traceback" not in err, f"{typed}: a traceback leaked to the caller: {err}"
    # A line that reached argparse would have been refused there too, but with the
    # census's whole flag list in the message: proof the wrapper answered it and
    # not the census.
    assert "--ledger" not in err, f"{typed}: the census's parser answered: {err}"
    assert recorded.calls == [], (
        f"the census ran with no timestamp to pin: {recorded.calls}")


@pytest.mark.parametrize("run,noun", _WRAPPERS_REAL, ids=("ledger", "sessions"))
def test_a_failing_tree_with_an_unlisted_option_exits_two_never_zero(
        tmp_path, run, noun):
    """The real census, no double: a failing tree plus a refused flag is 2, not its own code.

    This is the bug class the allowlist exists to close, told end to end. The
    tree fails on its own (``test_a_directory_with_a_broken_record...`` pins
    that code), so a run that ignored an unlisted token would answer 10 or 32 --
    and a wrapper that answered 0 for a filtered or redirected variant is the
    false clean a scripted caller acts on. Exit 2 with the census's report absent
    is the only answer that cannot be read as a verdict.
    """
    name, body, code = _BROKEN_RECORD[noun]
    directory = Path(_register(tmp_path, noun))
    (directory / name).write_text(body, encoding="utf-8")
    rc_alone, out_alone, _err = _run_with(run, [str(directory)])
    assert rc_alone == code, f"the fixture does not fail on its own: {rc_alone}"
    for token in ("--only", "probe", "--led=/tmp/elsewhere", "--help"):
        rc, out, err = _run_with(run, [str(directory), token])
        assert rc == EXIT_USAGE, f"{token}: rc={rc}, expected 2 (the tree fails at {code})"
        assert out == "", f"{token}: a refused run printed a report: {out}"


# --- the directory checks the allowlist does not replace ------------------------

@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_a_second_directory_is_refused_naming_both(tmp_path, run, noun, double,
                                                   monkeypatch):
    """Two directories, however the allowed options are interleaved, are exit 2 naming both.

    One run censuses one register. The option walk cannot answer this one, so it
    stays a directory check: the allowed options are consumed with their values
    and every bare token left over is a directory the caller named.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    first = _register(tmp_path, noun)
    second = tmp_path / "other" / "noni" / noun
    second.mkdir(parents=True)
    for argv in ([first, str(second)],
                 ["--json", first, str(second)],
                 [first, "--now", "2026-01-01T00:00:00+00:00", str(second)]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: censused one of two and printed rows: {out}"
        assert "at most" in err, f"{argv}: not the wrapper's own refusal: {err}"
        for path in (first, str(second)):
            assert path in err, f"{argv}: must name {path}: {err}"
    assert recorded.calls == [], f"the census ran on two directories: {recorded.calls}"


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_an_empty_string_is_no_directory_and_never_censuses_the_cwd(
        tmp_path, run, noun, double, monkeypatch):
    """`census.sh ""` is exit 2, not a census of whatever `noni/<noun>` sat beside.

    ``Path("")`` is the cwd and `is_dir` answers yes, so an empty argument would
    sail past the shape checks and census the tree the caller was standing in --
    the exact stateless default the one-argument rule exists to refuse. The
    census is not called, the refusal is the wrapper's, and the reason is the
    no-directory one rather than a path that does not exist.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    monkeypatch.chdir(tmp_path)
    rc, out, err = _run_with(run, ["", "--json"])
    assert rc == EXIT_USAGE, f"an empty path was accepted: rc={rc}\n{err}"
    assert out == "", f"a census of the cwd printed rows: {out}"
    assert f"no {noun} directory given" in err, (
        f"{err!r}: an empty path must take the no-directory refusal")
    assert recorded.calls == [], (
        f"the census ran over the cwd: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_a_positional_that_is_a_symlink_is_refused_never_read_through(
        tmp_path, run, noun, double, monkeypatch):
    """A directory handed to the wrapper as a link is exit 2, and the census never runs.

    ``is_dir`` follows links, so a link to a real register was accepted, and it
    was accepted with a split command line: ``--repo`` is built from the resolved
    path while the state flag keeps the link's own spelling, so the rows named a
    tree the caller never typed. The census does not read through links anywhere
    else (a record that is one is reported, never opened), so the wrapper refuses
    the one path where it could.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    real = tmp_path / "elsewhere" / "noni" / noun
    real.mkdir(parents=True)
    link = tmp_path / "state" / "noni" / f"{noun}-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real)
    for argv in ([str(link)], ["--json", str(link)]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: a refused run printed a report: {out}"
        assert str(link) in err, f"{argv}: must name the link it refused: {err}"
        assert "is a symlink" in err and "does not read through links" in err, (
            f"{argv}: not the symlink refusal: {err}")
    assert recorded.calls == [], (
        f"the census read through a link: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_a_symlinked_parent_component_is_refused_never_read_through(
        tmp_path, run, noun, double, monkeypatch):
    """A register reached through a symlinked *parent* is exit 2, census never run.

    The leaf check (``is_symlink``) sees only the last component, so ``link/decisions``
    with ``link`` a symlink to a real tree passed every gate: the run censused a
    directory the caller named only through a link, with ``--repo`` built from the
    resolved path and the state flag keeping the link's own spelling -- the split
    rows the leaf refusal exists to stop, one level up. The comparison is
    ``resolve()`` against ``abspath()``: the two agree only when no component of
    the path is a link, which is the rule the wrapper holds everywhere else.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    real = tmp_path / "real" / "noni" / noun
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    through = link / "noni" / noun
    assert through.is_dir() and not through.is_symlink(), (
        "the fixture is not a symlinked-parent path, so the case proves nothing")
    for argv in ([str(through)], ["--json", str(through)]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: a refused run printed a report: {out}"
        assert str(through) in err, f"{argv}: must name the path it refused: {err}"
        assert "is a symlink" in err and "does not read through links" in err, (
            f"{argv}: not the symlink refusal: {err}")
    assert recorded.calls == [], (
        f"the census read through a symlinked parent: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_a_trailing_dot_dot_through_a_symlink_is_refused_never_read_through(
        tmp_path, run, noun, double, monkeypatch):
    """``census.sh link/..`` is exit 2, census never run, and no "all checks passed".

    The parent check compares ``resolve()`` against ``abspath()``, and a ``..`` that
    walks back out of a link makes the two agree: the OS reads ``link/..`` as the
    link's parent, ``Path("link/..").is_symlink()`` is False, and ``resolve()``
    returns that parent's own absolute path. So the wrapper censused the directory
    *beside* the link, as if the caller had named it, and a clean tree there exits 0
    with "all checks passed" -- a verdict for a tree nobody named. The components
    the caller spelled are walked instead of the collapsed path, and a ``..`` is
    refused outright because it is the hop that hid the link.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    real = tmp_path / "real" / "noni" / noun
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    back = link / ".."
    assert back.is_dir() and not back.is_symlink(), (
        "the fixture is not a '..'-out-of-a-link path, so the case proves nothing")
    assert Path(os.path.abspath(str(back))) == tmp_path, (
        "the fixture does not name the link's parent, so the case proves nothing")
    for argv in ([str(back)], ["--json", str(back)]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: a refused run printed a report: {out}"
        assert "all checks passed" not in out, f"{argv}: a clean verdict for a tree " \
                                               f"nobody named: {out}"
        assert str(back) in err, f"{argv}: must name the path it refused: {err}"
        assert "symlink" in err, f"{argv}: the reason must name the link: {err}"
    assert recorded.calls == [], (
        f"the census censused the tree beside a link: {recorded.calls}")


def test_a_ledger_path_that_is_a_plain_file_is_refused_never_followed(paths):
    """A ledger path that is a plain file never reaches the census.

    Over a tree whose ``noni/decisions`` is a file the census's own probe answers
    "not a directory" and exits 0 without ``--strict``: the clean verdict nobody
    meant. The wrapper's ``is_dir`` gate stops the run and names the path.
    """
    for argv in ([str(paths["as_file"])], ["--json", str(paths["as_file"])]):
        rc, out, err = _run_with(run_ledger, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: rows for a path it could not census: {out}"
        assert str(paths["as_file"]) in err, f"{argv}: must name the path: {err}"
        assert "is not a directory" in err, f"{argv}: the reason: {err}"
