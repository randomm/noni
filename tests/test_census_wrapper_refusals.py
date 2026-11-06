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

import pytest
from census_probe_doubles import _RecordedCensusCall
from census_wrapper import EXIT_USAGE, run_ledger

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


# --- an option the census does not define --------------------------------------

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
