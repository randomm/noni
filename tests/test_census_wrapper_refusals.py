"""What the ledger wrapper refuses before it calls the census, and what it passes on.

``skills/steering-ledger/scripts/census.sh`` execs the in-place ``census.py``
beside it, which calls ``census_wrapper.run_ledger``. That function is the
wrapper's whole mind: two shape checks and one call
(``src/noni/census_wrapper.py``, ``run``). Everything else — every flag, its
meaning, and its refusal — belongs to the unified census, which the wrapper hands
the remaining arguments to untouched.

The two checks are what the census cannot make, because the census audits the
tree ``--repo`` names and an unnamed directory, a second directory, or a path
that is a plain file or a dangling link is invisible to a run over the tree that
contains it. A census that reads nothing has no verdict to give, and whoever
scripted the run reads its exit 0 as a clean ledger.

Each case drives ``run_ledger`` directly — the product function both shipped
scripts reach — and asserts the two things every refusal owes: the census's usage
code, and an empty stdout. Which half of the pair refused is told by whose words
appear: the census's ``unrecognized arguments`` for an option it does not define,
the wrapper's own line (``at most``, the ``is not a directory`` / ``does not
exist`` pair) for a command line of the wrong shape.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
from census_probe_doubles import _RecordedCensusCall, _RecordedSessionsCall
from census_wrapper import EXIT_USAGE, LEDGER_CHECKS, SESSION_CHECKS, run_ledger, run_sessions

# The classes either wrapper runs by itself, so a caller's own `--only <class>` is
# recognised as one by :func:`_forwarded` whichever wrapper it was typed at.
_GROUP_CLASSES = LEDGER_CHECKS | SESSION_CHECKS

# Each entry point, with the noun its usage line uses, the function a caller
# reaches it through, and the census double that reads its command line: one
# table, so the cases below drive both wrappers and cannot quietly cover only the
# ledger one.
_WRAPPERS = ((run_ledger, "decisions", _RecordedCensusCall),
             (run_sessions, "sessions", _RecordedSessionsCall))

# An option no census defines. The census's own refusal is what answers it, which
# is the point of the case: the wrapper interprets nothing itself.
UNKNOWN_OPTION = "--no-such-census-flag"


def _refused(argv: list[str]) -> tuple[int, str, str]:
    """One ``run_ledger`` call with both streams captured: (code, stdout, stderr).

    The census's refusal path exits through argparse rather than returning, so
    the call is guarded the way a caller at a shell is guarded: what the test
    reads is the code and the text either way.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = run_ledger(argv)
    except SystemExit as exc:  # argparse's own exit, which is the refusal
        rc = exc.code
    return rc, out.getvalue(), err.getvalue()


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


# --- an option value is not a second directory --------------------------------

# Each entry point, with the noun its usage line uses and the function a caller
# reaches it through: one table, so the cases below drive both wrappers and cannot
# quietly cover only the ledger one.
_WRAPPERS = ((run_ledger, "decisions", _RecordedCensusCall),
             (run_sessions, "sessions", _RecordedSessionsCall))


def _forwarded(options: list[str]) -> list[str]:
    """``options`` as the recording double keeps them: a leading run of the
    wrapper's own group ``--only <class>`` pairs removed, then every remaining
    option/value pair of the caller's kept as two tokens.

    ``_RecordedCensusCall`` reads the command line the way argparse does: it drops
    the group's ``--only <class>`` pairs from the front of the tail it keeps, so a
    caller's own `--only X` that survives that strip is folded to one token there
    while `--skip X`, `--now <stamp>` and the rest are kept as the caller typed
    them. Rebuilding the expected tail from that rule, rather than reusing the
    input verbatim, keeps the assertion about the bytes the wrapper forwarded.
    """
    tail = list(options)
    while tail[:1] == ["--only"] and len(tail) > 1 and tail[1] in _GROUP_CLASSES:
        tail = tail[2:]
    return tail


def _register(tmp_path: Path, noun: str) -> str:
    """One state directory either wrapper will accept, laid out for either entry point."""
    directory = tmp_path / "state" / "noni" / noun
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def _run_with(run, argv: list[str]) -> tuple[int, str, str]:
    """``run(argv)`` for either entry point, with both streams captured.

    The twin of :func:`_refused` that takes the entry point as an argument, so one
    parametrised table can drive the ledger and sessions wrappers alike.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = run(argv)
    except SystemExit as exc:  # argparse's own exit, which is the refusal
        rc = exc.code
    return rc, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("run,noun,double", _WRAPPERS,
                         ids=("ledger", "sessions"))
@pytest.mark.parametrize("options", (
    ["--only", "ledger-record"],
    ["--skip", "hygiene"],
    ["--only", "session-double", "--skip", "probe"],
    ["--now", "2026-01-01T00:00:00+00:00"],
    ["--stale-after", "14d"],
))
def test_a_value_taking_option_takes_one_token_not_two(tmp_path, run, noun, double,
                                                       options, monkeypatch):
    """`--only X`, `--skip X`, `--now X` and every other separate-value option the
    census defines pass through over one directory: exit 0, no refusal, and the
    option forwarded to the census as typed.

    The wrapper counts positional tokens to enforce its one-directory rule, and a
    value-taking option's value is a bare token the census never parses as an
    argument. Counting it answered the options the docs promise ("`--only` /
    `--skip` filters work here exactly as they do on `noni census`") with the
    wrapper's own usage refusal: exit 2 naming a directory nobody typed.
    """
    directory = _register(tmp_path, noun)
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    rc, out, err = _run_with(run, [directory, *options])
    assert rc == 0, f"{options}: the option was refused: rc={rc}\n{err}"
    assert out == "" and err == "", f"printed alongside the census: {out}{err}"
    assert recorded.calls == [(directory, _forwarded(options))], (
        f"the census was handed something else: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS,
                         ids=("ledger", "sessions"))
def test_the_equals_form_of_a_value_taking_option_swallows_no_token(
        tmp_path, run, noun, double, monkeypatch):
    """`--only=X` is one token and consumes nothing after it, so the directory that
    stands beside it is still the single positional and the run is not refused.

    The `--opt=value` form carries its own value, so the counter must not treat it
    as a flag whose next token is a value; a counter that did would answer the
    caller's one directory with "no directory given".
    """
    directory = _register(tmp_path, noun)
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    rc, out, err = _run_with(run, [directory, "--only=ledger-record"])
    assert rc == 0, f"the equals form was refused: rc={rc}\n{err}"
    assert out == "" and err == "", f"printed alongside the census: {out}{err}"
    assert recorded.calls == [(directory, ["--only=ledger-record"])], (
        f"the census was handed something else: {recorded.calls}")


@pytest.mark.parametrize("run,noun,double", _WRAPPERS,
                         ids=("ledger", "sessions"))
def test_a_real_second_directory_is_still_refused_alongside_options(
        tmp_path, run, noun, double):
    """The fix must not widen the rule: two directories, however the options are
    interleaved, are still exit 2 naming both of them.

    Without this case a counter that swallowed everything after every `--` token
    would pass the pass-through tests by refusing nothing at all.
    """
    first = _register(tmp_path, noun)
    second = tmp_path / "other" / "noni" / noun
    second.mkdir(parents=True)
    for argv in ([first, str(second)],
                 ["--only", "probe", first, str(second)],
                 [first, "--now", "2026-01-01T00:00:00+00:00", str(second)]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: censused one of two and printed rows: {out}"
        assert "at most" in err, f"{argv}: not the wrapper's own refusal: {err}"
        for path in (first, str(second)):
            assert path in err, f"{argv}: must name {path}: {err}"


@pytest.mark.parametrize("run,noun,double", _WRAPPERS, ids=("ledger", "sessions"))
def test_the_retired_cross_group_option_is_refused_naming_itself(
        tmp_path, run, noun, double, monkeypatch):
    """The retired dispatch (`census.sh --sessions DIR`) is refused, naming the option.

    The census still defines both register flags, so a bare pass-through would
    answer the old form with a census of the *other* register -- the silent
    wrong-group census issue #99 was written against. The wrapper refuses it
    before the directory checks, so the caller is told about the option they
    typed rather than about a path they did not name, and the census is never
    called.
    """
    recorded = double()
    monkeypatch.setattr("census_wrapper.main", recorded)
    other = "--sessions" if noun == "decisions" else "--ledger"
    register = _register(tmp_path, "sessions" if other == "--sessions" else "decisions")
    for argv in ([other, register], [register, other], ["--json", other, register]):
        rc, out, err = _run_with(run, argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: a refused run printed a report: {out}"
        assert other in err, f"{argv}: the refusal must name the option: {err}"
        assert f"no {noun} directory given" not in err, (
            f"{argv}: refused for the wrong reason: {err}")
    assert recorded.calls == [], (
        f"the census ran for a retired dispatch: {recorded.calls}")


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


@pytest.mark.parametrize("slot", ("before", "after", "among"))
def test_an_unknown_option_is_the_census_usage_refusal_naming_the_option(paths, slot):
    """Every position an unknown flag can be typed in ends at exit 2, with the
    flag named and no report.

    The wrapper forwards options it does not recognise, so this is the census's
    refusal reaching the caller through the wrapper. A wrapper that quietly
    dropped an unrecognised option would run a census nobody asked for and return
    its exit code, and the script that called it would read a verdict on the
    ledger it named.
    """
    ledger, flag = str(paths["good"]), UNKNOWN_OPTION
    argv = {"before": [flag, ledger], "after": [ledger, flag],
            "among": ["--json", flag, ledger]}[slot]
    rc, out, err = _refused(argv)
    assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
    assert out == "", f"{argv}: a refused run printed a report: {out}"
    assert flag in err, f"{argv}: the refusal must name the option: {err}"
    assert "unrecognized" in err, (
        f"{argv}: the census must be the one that refused: {err}"
    )


# --- more than one positional ---------------------------------------------------

@pytest.mark.parametrize("slot", ("both", "json-before", "json-between"))
def test_more_than_one_positional_is_refused_naming_both(paths, slot):
    """Two directories named is exit 2 naming both of them, with no rows.

    One run censuses one ledger. This is the wrapper's own refusal — it counts
    positionals, not arguments, so the flags interleaved above must not change
    the verdict — and the second path is the one the caller mistyped, so naming
    it is what makes the refusal actionable.
    """
    good, extra = str(paths["good"]), str(paths["extra"])
    argv = {"both": [good, extra], "json-before": ["--json", good, extra],
            "json-between": [good, "--json", extra]}[slot]
    rc, out, err = _refused(argv)
    assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
    assert out == "", f"{argv}: censused one of two and printed rows: {out}"
    assert "at most" in err, f"{argv}: not the wrapper's own refusal: {err}"
    for path in (good, extra):
        assert path in err, f"{argv}: must name {path}: {err}"


# --- a ledger path that is not a directory -------------------------------------

@pytest.mark.parametrize("kind,reason", (
    ("as_file", "is not a directory"),
    ("dangling", "does not exist"),
))
def test_a_ledger_path_that_is_not_a_directory_is_refused_never_followed(
    paths, kind, reason
):
    """A ledger path that is a plain file, or a link to nothing, never reaches the census.

    Both states the census would otherwise answer with a dismissible warn: over a
    tree whose ``noni/decisions`` is a file its probe answers "not a directory",
    and over one whose entry is a dangling link it answers a state of its own —
    either way exit 0 without ``--strict``, the clean verdict nobody meant. The
    wrapper's ``is_dir`` gate stops the run, and the reason it prints keeps the
    two states apart for the caller. The link is never read through: the census
    reports a symlink it can see, and a run that resolved this one would have
    censused a directory the caller never named.
    """
    path = paths[kind]
    for argv in ([str(path)], ["--json", str(path)]):
        rc, out, err = _refused(argv)
        assert rc == EXIT_USAGE, f"{argv}: rc={rc}\n{err}"
        assert out == "", f"{argv}: rows for a path it could not census: {out}"
        assert str(path) in err, f"{argv}: must name the path it refused: {err}"
        assert reason in err, (
            f"{argv}: the reason must keep a file apart from a dangling link "
            f"(expected {reason!r}): {err}"
        )


# --- the pass-through that makes the refusals mean something -------------------

def test_a_ledger_directory_and_its_options_reach_the_census_untouched(
    tmp_path, monkeypatch
):
    """The shape checks let a real ledger through, and the options arrive as given.

    The other half of every case above: without it a wrapper that refused
    everything would pass them all. ``run`` is two checks and one call, so the
    call is captured: the directory reaches the census spelled as the caller
    spelled it and the options the caller named arrive untouched, which is the
    promise that lets ``--json`` and ``--strict`` stay the census's flags with the
    census's refusals. The group's own ``--only`` flags are the wrapper's doing and
    are checked as a prefix, not as the caller's arguments.
    """
    ledger = tmp_path / "state" / "noni" / "decisions"
    ledger.mkdir(parents=True)
    recorded = _RecordedCensusCall()
    monkeypatch.setattr("census_wrapper.main", recorded)
    rc, out, err = _refused([str(ledger), "--json", "--strict"])
    assert rc == 0, f"the run was refused: rc={rc}\n{err}"
    assert out == "" and err == "", f"the wrapper printed alongside the census: {out}{err}"
    assert recorded.calls == [(str(ledger), ["--json", "--strict"])], (
        f"the census was handed something else: {recorded.calls}")
