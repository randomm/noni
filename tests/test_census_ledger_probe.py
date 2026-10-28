"""Unit tests for the ledger probe, its one listing helper, and its one row.

``census_ledger`` owns three things the census depends on for its honesty about
the ledger: the listing helper that names the ledger's ``*.json`` records, the
probe that classifies the ledger directory once and carries the names it read,
and the one row a listing that faulted earns. All are tested here directly,
against a patched ``Path.iterdir``, rather than only through ``census.main`` --
the end-to-end tests in ``test_census_unified.py`` and
``test_census_exit_codes.py`` prove the rows; these prove the read.

The seam is ``Path.iterdir`` throughout. ``Path.glob`` is never the seam: the
helpers call ``iterdir`` precisely because ``glob`` swallows the ``OSError`` a
readdir raises and yields nothing, so a fault injected at ``glob`` would reach
the probe as an ordinary recordless directory and the arm under test would
never run.
"""

from __future__ import annotations

import json
from pathlib import Path

import census_ledger  # noqa: E402
import pytest
from _harness import (  # noqa: E402
    _commit_file,
    _fault_the_ledger_listing,
    _harness_source,
    _init_repo,
)

CENSUS = Path(__file__).resolve().parent.parent / "skills" / "census" / "scripts" / "census.py"


def _kind_dir_ok(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """A classifier that answers "regular" for everything, so these tests turn
    on the listing alone and not on a stat the census's own classifier does."""
    return "regular", None


def _kind_absent(path: Path, kind: str = "file") -> tuple[str, str | None]:
    return "absent", None


def _kind_symlink(path: Path, kind: str = "file") -> tuple[str, str | None]:
    return "symlink", "path is a symlink; the census does not read through links"


def _kind_parent_nonregular(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """``noni/`` is not a directory, the ledger entry itself answers normally."""
    if kind == "dir" and path.name != "decisions":
        return "nonregular", "path is not a directory"
    return "regular", None


def _fault_iterdir(monkeypatch, target: Path, text: str = "readdir denied"):
    """Fault the listing of ``target`` only; every other listing stays honest."""
    real_iterdir = Path.iterdir

    def boom(self):
        if self == target:
            raise OSError(text)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)


# --- the identifier -------------------------------------------------------------


@pytest.mark.parametrize("rel,expected", (
    # The ordinary case: a path the census could root keeps its root-relative form.
    ("noni/decisions", "noni/decisions"),
    ("noni/sessions", "noni/sessions"),
    # A tilde that names a directory, not a home directory, is not a host path.
    ("noni/a~b", "noni/a~b"),
    # Every shape that could carry a host location is reduced to its last segment.
    ("~deploy/a/b c", "b c"),
    ("~/x/y", "y"),
    ("../host-dir/decisions", "decisions"),
    ("../../home/someone/decisions", "decisions"),
    ("/abs/host-dir/decisions", "decisions"),
    # A segment no repository directory is ever named with: a fragment the caller
    # walked, not a name the census wrote, so the row keeps its last segment and
    # no run of someone else's characters reaches the fields a caller joins on.
    ("build/home/someone/.aws/" + "a" * 240 + "/sessions", "sessions"),
    # The cap is on the segment, not the path: a shallow tree with ordinary names
    # stays root-relative however many segments it holds.
    ("x/" + "b" * 79, "x/" + "b" * 79),
    ("a/b/c/d/e", "a/b/c/d/e"),
    # Nothing left to name: the generic word, never an empty field.
    ("", "ledger"),
    ("/", "ledger"),
))
def test_ledger_name_keeps_a_root_relative_path_and_shrinks_the_rest(rel, expected):
    """The identifier rule, stated once: root-relative stays, anything else is one segment.

    The row's ``subject``/``artifact`` are joined on, so they cannot go through the
    scrubber, and they are rendered too, so they cannot carry a host path either.
    The reduction is what settles that: only a path the census could root (two
    segments below the repo root, no empty segment, no ``..``, no leading ``~``)
    is a path the census wrote, and every path it could not root is one the caller
    spelled, of which the last segment is all the row may print.
    """
    assert census_ledger.ledger_name(rel) == expected


def test_ledger_name_answers_for_every_path_shape_it_may_be_handed():
    """The rule is total: no input earns an empty or crashed identifier.

    ``ledger_name`` runs on whatever ``_rel_to_root`` handed back, including the
    forms no test lists -- a doubled separator, a dot segment, a bare filename --
    and the row's identifier fields are required, so every one of them must come
    back as a name the report can print and a caller can join on.
    """
    for rel in ("~deploy/a/b c", "~/x/y", "../host-dir/decisions",
                "../../home/someone/decisions", "/abs/host-dir/decisions", "/", "",
                "noni/decisions", "noni/a~b", "a//b", "a/./b", "decisions", "//", "~",
                "/home/someone/decisions"):
        name = census_ledger.ledger_name(rel)
        assert name, f"{rel!r} answered an empty identifier"
        assert "\\" not in name and "\n" not in name, f"{rel!r} -> {name!r}"
        if name != rel:  # a root-relative path is kept whole, everything else shrunk
            assert not name.startswith("/") and not name.startswith("~"), \
                f"{rel!r} -> {name!r}: an identifier may not be a location"
            assert ".." not in name.split("/"), f"{rel!r} -> {name!r} escapes the tree"


def test_ledger_name_never_shrinks_a_root_relative_path():
    """The other direction of the rule: the census's own path keeps its name.

    Shrinking too much is as expensive as shrinking too little -- a row whose
    identifier reads ``decisions`` instead of ``noni/decisions`` tells the
    operator nothing they can act on, and a report that joins on the field joins
    on the root-relative path. These are the paths ``_rel_to_root`` actually hands
    back for an in-tree ledger and register.
    """
    for rel in ("noni/decisions", "noni/sessions", "noni/a~b", "noni/decisions/sub"):
        assert census_ledger.ledger_name(rel) == rel


# --- the listing helper ---------------------------------------------------------


def test_listing_helper_returns_record_names_from_iterdir(tmp_path, monkeypatch):
    """The helper lists the ledger's ``*.json`` names and only those.

    The record pass of ``census.py`` and the ordering readers both go through
    this one call, so "which files count as ledger records" has one answer:
    ``*.json`` names, non-JSON entries and directories excluded, in a stable
    order. The test asserts the names and not the ``Path`` objects, because the
    callers key their rows on names.
    """
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    for name in ("2026-10-02-b.json", "2026-10-01-a.json", "notes.md", "sub"):
        (ledger / name).mkdir() if name == "sub" else (ledger / name).write_text("{}")
    seen: list[str] = []

    real_iterdir = Path.iterdir

    def spy(self):
        seen.append(str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", spy)
    names = census_ledger.listing_helper(ledger)
    assert sorted(names) == ["2026-10-01-a.json", "2026-10-02-b.json"], names
    assert ledger in [Path(s) for s in seen], (
        "the helper must reach the directory through iterdir, not glob"
    )


def test_listing_helper_raises_on_a_readdir_fault(tmp_path, monkeypatch):
    """The helper does not swallow the fault: it raises, and the caller decides.

    ``Path.glob`` returns an empty iterator when readdir raises, which is how a
    directory the run could not read comes to look like a project that has
    never steered anything. The helper's contract is the opposite: the OSError
    propagates so the probe can carry its text and the census can report the
    fault instead of an answer."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger, "input/output error")

    raised = None
    try:
        census_ledger.listing_helper(ledger)
    except OSError as e:
        raised = e
    assert raised is not None, "a readdir fault must propagate, not yield nothing"
    assert "input/output error" in str(raised)
    # glob is not the seam: had the helper called it, this call would have
    # returned [] and raised nothing.
    assert list(ledger.glob("*.json")) != [], "the fixture itself is listable by glob"


# --- the probe ------------------------------------------------------------------


def test_probe_records_listing_fault_text_on_the_probe(tmp_path, monkeypatch):
    """The probe catches the helper's OSError and carries its text verbatim.

    ``listing_fault`` is the one field allowed to hold a fault that is not a
    state of the tree, so the text must survive the probe intact for the row to
    quote it."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger, "readdir denied")

    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    # The fault's words with its class in front of them: the text a row renders,
    # built by ``census_text.fault_text`` from the structured fields so the
    # filename is never in it (see ``test_fault_text_never_carries_the_filename``
    # in tests/test_census_text_scrub.py for the rule itself).
    assert probe.listing_fault == "OSError: readdir denied", probe
    assert probe.state == "empty", probe


def test_probe_reports_a_fault_whose_oserror_carries_a_path(tmp_path, monkeypatch):
    """The probe never raises over a fault that carries a path, and never carries it.

    ``OSError`` appends the path it failed on to ``str(e)`` and keeps it in
    ``e.filename``, so the probe's field is the place to take it out: the row is
    built from the exception's class and its ``strerror``, which are the half that
    says what failed. Dropping the whole fault would cost the operator the only
    thing that identifies it, and raising would turn the row about an unreadable
    ledger into a traceback. Nothing downstream has to scrub what was never
    carried here (the scrubber stays a net for other foreign text).
    """
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    host = tmp_path / "host-dir" / "decisions"

    real_iterdir = Path.iterdir

    def boom(self):
        if self == ledger:
            raise OSError(5, "Input/output error", str(host))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.listing_fault is not None, probe
    assert "Input/output error" in probe.listing_fault, probe
    # The whole path, and no part of it: the row names the ledger itself, so the
    # filename the read failed on is a host location and nothing else.
    assert str(host) not in probe.listing_fault, probe.listing_fault
    assert "host-dir" not in probe.listing_fault, probe.listing_fault


def test_probe_answers_ok_for_a_ledger_with_a_record(tmp_path):
    """A real directory holding one ``*.json`` record is "ok", no fault, no
    problem: the only state under which the record pass reports anything."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert (probe.state, probe.problem, probe.listing_fault) == ("ok", None, None), probe


def test_probe_answers_empty_for_a_recordless_directory(tmp_path):
    """A directory that lists fine and holds no record is the "empty" warn, with
    no fault text attached -- the read answered, and what it answered was
    "nothing here"."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "notes.md").write_text("not a record")
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert (probe.state, probe.problem, probe.listing_fault) == ("empty", None, None), probe


def test_probe_answers_absent_when_there_is_no_noni(tmp_path):
    """No parent at all is "absent", a state of the tree rather than a fault."""
    ledger = tmp_path / "noni" / "decisions"
    probe = census_ledger.probe_ledger(ledger, _kind_absent)
    assert (probe.state, probe.problem, probe.listing_fault) == ("absent", None, None), probe


def test_probe_reports_symlink_and_never_follows_it(tmp_path, monkeypatch):
    """A symlinked ledger is "symlink" with no listing attempted.

    A link whose target holds a record must still answer "symlink": if the
    probe followed the link it would find a record, answer "ok" and the census
    would report nothing about a path it read through."""
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "2026-10-01-a.json").write_text("{}")
    ledger = tmp_path / "noni" / "decisions"
    ledger.parent.mkdir(parents=True)
    ledger.symlink_to(real)
    probe = census_ledger.probe_ledger(ledger, _kind_symlink)
    assert probe.state == "symlink", probe
    assert probe.listing_fault is None, probe


def test_probe_keeps_the_parent_problem_for_a_nonregular_noni(tmp_path):
    """``noni/`` not being a directory is reported with the OSError text that
    said so, under the closest documented state word."""
    ledger = tmp_path / "noni" / "decisions"
    probe = census_ledger.probe_ledger(ledger, _kind_parent_nonregular)
    assert probe.state == "not a directory", probe
    assert probe.problem == "path is not a directory", probe


def test_probe_reads_the_ledger_through_the_helper_not_glob(tmp_path, monkeypatch):
    """The probe's one read is the helper's ``iterdir``.

    Patching ``Path.glob`` to raise must not produce a fault: if the probe were
    still listing with ``glob`` it would report the ledger as unreadable here
    while its own seam answered fine, and the reverse patch (``iterdir``
    raising) is what the fault tests above use. Together they pin which call the
    probe actually makes."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")

    def boom_glob(self, pattern):
        raise AssertionError("the probe must not list the ledger with glob")

    monkeypatch.setattr(Path, "glob", boom_glob)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.state == "ok", probe
    assert probe.listing_fault is None, probe


def test_probe_fault_on_a_real_repository_ledger(tmp_path, monkeypatch):
    """The fault arm against a tree built by the harness's own git fixture.

    The repository is real (so the path shapes are the ones a census run sees)
    and only the ledger's readdir faults, which is the state no file permission
    can plant for a root-equivalent runner."""
    repo = _init_repo(tmp_path / "repo")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.listing_fault == "OSError: readdir denied", probe
    assert probe.state == "empty", (
        "an unlistable ledger keeps the state word so the git-backed deletion "
        "question is still put when git can answer it"
    )


# --- the fault rows, end to end -------------------------------------------------
#
# The rows the fault produces, driven through census.main: the machine-local
# path rule, the one-probe rule, and the filter that must not buy back a clean
# verdict. The unit tests above prove the read; these prove what the run says
# about it.


def _valid_record(rec_id="2026-10-01-alpha", status="decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }


def _rows(repo: Path, *args: str) -> list[dict]:
    """The finding rows of an in-process --json run."""
    import io
    import json
    from contextlib import redirect_stderr, redirect_stdout

    import census

    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json", *args]
    with redirect_stdout(out), redirect_stderr(err):
        census.main(argv)
    rows = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    return [r for r in rows if r.get("kind") == "finding"]


def _code(repo: Path, *args: str) -> int:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import census

    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        return census.main(argv)


def test_unreadable_ledger_outside_the_repo_leaks_no_absolute_path(tmp_path, monkeypatch):
    """An out-of-tree ``--ledger`` whose listing faults must not print a host path.

    The ledger override is the one case where the ledger lives outside the
    audited tree, so ``_rel_to_root`` cannot root it and hands back the string it
    was given -- the machine-local absolute path, verbatim. The row that reports
    the fault therefore has to scrub and bound that text the way the ordering
    group's equivalent row does (``census_ordering`` composes its listing-fault
    sentence with the fault text passed through ``bounded``), and the OSError
    text itself is foreign content that goes through the same rule.

    The fault message is planted with a host path inside it, so the assertion is
    about the scrubbing and not about which string the fixture happened to use.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    outside = tmp_path / "ledger-home" / "decisions"
    outside.mkdir(parents=True)
    (outside / "2026-10-01-a.json").write_text(json.dumps(_valid_record(), indent=2),
                                               encoding="utf-8")

    real_iterdir = census.Path.iterdir
    needle = str(outside)

    def boom(self):
        if self == outside:
            raise OSError(f"readdir denied for {needle}")
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    found = _rows(repo, "--skip", "hygiene", "--ledger", str(outside))
    assert [r["check"] for r in found] == ["ledger-edited"], found
    row = found[0]
    for field in ("subject", "artifact", "message"):
        assert needle not in row[field], f"absolute path leaked in {field}: {row[field]!r}"
        assert not any(part.startswith(f"{tmp_path}/") for part in row[field].split()), (
            f"machine-local path leaked in {field}: {row[field]!r}"
        )
    # The operator still learns what failed and where: the fault's own words
    # survive the scrub, and the row still names the ledger it could not read.
    assert "readdir" in row["message"] and "denied" in row["message"], row["message"]
    assert "decisions" in row["subject"] and "decisions" in row["artifact"], row
    assert _code(repo, "--skip", "hygiene", "--ledger", str(outside)) == 0
    assert _code(repo, "--skip", "hygiene", "--strict", "--ledger", str(outside)) == 12


def test_an_unreadable_ledger_empty_row_bounds_the_probe_problem(tmp_path, monkeypatch):
    """``probe.problem`` is OSError text and reaches the ledger-empty row through
    the census's bound-and-scrub, not raw.

    The probe's problem text is foreign text from this tree, so a long strerror
    or one carrying a host path would otherwise land in the row unbounded and
    unscrubbed. Unlike the listing-fault row, this one composes its own
    root-relative path, so only the probe's text is scrubbed -- the state word
    the row exists to carry stays intact.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir()
    leak = str(tmp_path / "secret-host-dir")

    real_is_dir = census.Path.is_dir

    def boom_is_dir(self):
        if self == ledger:
            raise OSError("i/o fault " + "u" * 400 + " at " + leak)
        return real_is_dir(self)

    monkeypatch.setattr(census.Path, "is_dir", boom_is_dir)
    empty = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-empty"]
    assert len(empty) == 1, empty
    msg = empty[0]["message"]
    assert "probe error" in msg, msg
    assert leak not in msg, f"machine-local path in the row: {msg}"
    assert "u" * 400 not in msg, f"unbounded fault text in the row: {msg}"
    # The bound is the one ``_bounded`` applies to foreign text (300 chars); the
    # sentence the census composed around it is its own wording and keeps its own
    # path fragments, so only the probe's text is measured here.
    probe_text = msg.split("(probe error: ", 1)[1]
    assert len(probe_text) <= 301, f"foreign text past the bound: {len(probe_text)}"
    assert "not a directory" in msg, f"state word kept: {msg}"


def test_the_listing_fault_row_is_clipped_as_a_whole(tmp_path, monkeypatch):
    """The fault row keeps the bound every other row of the report keeps.

    ``append_listing_fault`` composes its sentence around two pieces of foreign
    text and clipped neither: the finished row was as long as the errno text
    inside it, and a ``strerror`` of a few thousand characters (a kernel that
    names the mount it failed on, a fuse daemon that answers at length) was a
    row of a few thousand characters in a report whose every other row is bound.
    The bound wraps the whole message, so the sentence this run wrote is at most
    the bound whoever wrote the fault's words.

    In-process: the fault is inside the interpreter, where no file permission
    can plant it.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    ledger = repo / "noni" / "decisions"

    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == ledger:
            raise OSError("input/output error: " + "u" * 5000)
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    rows = _rows(repo, "--skip", "hygiene")
    assert [r["check"] for r in rows] == ["ledger-edited"], rows
    message = rows[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "input/output error" in message, message
    assert "u" * 5000 not in message, message


def _host_shaped_faults() -> list[tuple[OSError, tuple[str, ...]]]:
    """The faults whose filename the scrubber has kept losing, and their parts.

    Built at runtime, never literals: a tracked file carrying one of these paths
    would trip the census's own hygiene class. Each is the shape a real fault on
    a real host takes -- a service account's home, a directory whose name holds a
    space and characters outside the ASCII alphabet -- and each is a shape the
    path arms of ``census_text._stripped`` cannot be relied on to catch, which is
    why the row is built without the filename instead of scrubbed after it.
    """
    return [
        (OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/"),
         ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir")),
        (OSError(13, "Permission denied", "~deploy"), ("deploy",)),
    ]


@pytest.mark.parametrize("case", range(2))
def test_the_listing_fault_row_carries_no_part_of_the_filename(tmp_path, monkeypatch, case):
    """The ledger group's row for an unlistable ledger names the fault, never the path.

    Two faults, both of which the scrubber has historically lost: a filename with
    a non-ASCII component and a space in it, and the bare home of a service
    account. Neither may reach any field of the row, and the row still has to say
    what failed and which ledger it could not read -- so the assertions pull in
    both directions and a rule that dropped the fault's words to keep its
    silence would fail here too.

    The fault is planted in the interpreter, at the probe's own listing.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    ledger = repo / "noni" / "decisions"
    fault, parts = _host_shaped_faults()[case]

    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == ledger:
            raise fault
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    rows = _rows(repo, "--skip", "hygiene")
    assert [r["check"] for r in rows] == ["ledger-edited"], rows
    row = rows[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
        assert "/home/someone" not in row[field], row[field]
    # What the row is for: the fault's own words, and the ledger it could not read.
    assert "Permission denied" in row["message"], row["message"]
    assert "PermissionError" in row["message"], row["message"]
    assert row["subject"] == row["artifact"] == "noni/decisions", row


@pytest.mark.parametrize("case", range(2))
def test_the_ledger_empty_probe_error_carries_no_part_of_the_filename(
        tmp_path, monkeypatch, case):
    """The other row that quotes an ``OSError``: ``probe.problem`` in ``ledger-empty``.

    The fault here comes from a stat rather than a readdir, which is a different
    producer (``_file_kind``) and a different row (``ledger-empty``, composed with
    a state word and the census's own path). Same rule: the row is built from the
    exception's class and its ``strerror``, so no part of the filename reaches it
    and nothing downstream has to recognise the path to remove it.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir()
    fault, parts = _host_shaped_faults()[case]

    real_is_dir = census.Path.is_dir

    def boom_is_dir(self):
        if self == ledger:
            raise fault
        return real_is_dir(self)

    monkeypatch.setattr(census.Path, "is_dir", boom_is_dir)
    empty = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-empty"]
    assert len(empty) == 1, empty
    row = empty[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
    assert "probe error" in row["message"], row["message"]
    assert "Permission denied" in row["message"], row["message"]
    assert "not a directory" in row["message"], row["message"]


def _iterdir_counter(monkeypatch, ledger: Path):
    """Patch ``Path.iterdir`` once, counting the listings of ``ledger`` it sees.

    Returns ``(state, plant)``: ``state["n"]`` is the count, and ``plant(k)``
    makes the (k + 1)-th listing of ``ledger`` raise. The single patch is the
    point — a fixture that patches twice over its own previous patch chains two
    counters, the outer one never reaches its guard, and the test silently stops
    faulting anything. One patch, one counter, and the fault position is a
    parameter a test resets between the runs it compares.

    The patch goes on ``census.Path``, the name the census and its ledger module
    share (see ``_fault_the_ledger_listing`` in ``tests/_harness.py``), so it is
    visible to every reader of the ledger and to no other interpreter.
    """
    import census

    real_iterdir = Path.iterdir
    target = Path(ledger)
    state = {"n": 0, "fault_after": 10 ** 9}

    def boom(self):
        if self == target:
            state["n"] += 1
            if state["n"] > state["fault_after"]:
                raise OSError("readdir faulted after the probe")
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)

    def plant(fault_after: int) -> dict:
        state["n"] = 0
        state["fault_after"] = fault_after
        return state

    return state, plant


def test_the_run_lists_the_ledger_once(tmp_path, monkeypatch):
    """One readdir of the ledger per run, whoever downstream wants its names.

    The probe is the run's only listing: the record pass and the ordering readers
    read the ``names`` it carries instead of walking the directory again. The
    fault is planted after the first successful readdir, which is the shape no
    single-fault test can reach: the probe's read answered, and the tree has
    turned hostile only by the time the record pass asks the same question. A
    run that re-listed died there with an ``OSError`` traceback out of
    ``census.main``; a run that reads the probe's names says the same thing the
    unfaulted run says and exits like it.

    The seam is ``Path.iterdir`` with a counter, so the assertion is about the
    count and not about which helper happened to be called: the census's own
    git calls, the session register and the artifact reads all list other paths,
    and only a guard that lets the first readdir of the ledger through reaches
    the arm under test. The patch is installed once, by ``_iterdir_counter``,
    and the fault position reset between runs: a fixture that patched twice over
    its own previous patch would chain the counters and fault nothing.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                 json.dumps(_valid_record(rec_id="2026-10-02-beta"), indent=2))
    ledger = repo / "noni" / "decisions"
    state, plant = _iterdir_counter(monkeypatch, ledger)

    # The run with every listing honest is the control: the same tree, the same
    # verdict the faulted run must reproduce.
    plant(10 ** 9)
    rows = _rows(repo, "--skip", "hygiene")
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, f"a run that read the ledger once stays clean: {code} {rows}"
    assert rows == [], f"the unfaulted run reports nothing: {rows}"

    # The counter is the mechanism: pin that this run listed the ledger once.
    plant(10 ** 9)
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, (code, state)
    assert state["n"] == 1, f"the ledger was listed {state['n']} times, expected one"

    # And the second readdir faulting is what used to kill the run.
    plant(1)
    rows = _rows(repo, "--skip", "hygiene")
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, f"the run must complete, not raise: {code} {rows}"
    assert rows == [], f"the faulted run reports the same rows as the clean one: {rows}"


def test_a_run_that_cannot_relist_the_ledger_still_checks_every_citation(
    tmp_path, monkeypatch
):
    """One listing must not cost the run its checks.

    The run faults its second readdir of the ledger while an entry cites a
    record the ledger does not hold. A run that answered "no records" from the
    fault would report the citation as matching no file, which is the dishonesty
    the ordering group's fault row exists to prevent; a run that reads the
    probe's names makes the same finding it makes without the fault. Both rows
    are pinned by class and subject, so an implementation that dropped either
    half fails here."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    order = {
        "schema": "noni.order/1",
        "entries": [{"issue": 7, "decision": "2026-10-01-alpha",
                     "confirmed": "2026-10-26T00:00:00Z"},
                    {"issue": 8, "decision": "2026-10-09-ghost",
                     "confirmed": "2026-10-26T00:00:00Z"}],
    }
    _commit_file(repo, "noni/direction/order.json", json.dumps(order, indent=2))
    state, plant = _iterdir_counter(monkeypatch, repo / "noni" / "decisions")
    plant(1)
    rows = _rows(repo, "--skip", "hygiene")
    assert state["n"] == 1, f"the ledger was listed {state['n']} times, expected one"
    assert sorted(r["check"] for r in rows) == ["ordering-malformed"], rows
    assert [r["subject"] for r in rows] == ["#8"], rows
    assert "2026-10-09-ghost" in rows[0]["message"], rows[0]
    assert _code(repo, "--skip", "hygiene") == 15


def test_the_run_probes_the_ledger_once(tmp_path, monkeypatch):
    """One classification per run: ``main`` asks the probe once and reuses it.

    The listing is the expensive read of the ledger group, and a second probe is
    a second chance to disagree with the first (the tree can change between two
    reads). ``main`` builds the one ``LedgerProbe``, decides the group from its
    ``listing_fault``, and hands that same probe to ``_check_ledger``. The
    counter proves the group ran and the count proves it read once.

    The seam is ``census._ledger_probe``, the name the census owns and the one
    its tests patch. The source pins at the end state the same rule on the
    wiring, so restoring a second-probe path fails there as well as here.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))

    calls: list[str] = []
    real_probe = census._ledger_probe

    def counting_probe(ledger):
        calls.append(str(ledger))
        return real_probe(ledger)

    monkeypatch.setattr(census, "_ledger_probe", counting_probe)
    assert _code(repo, "--skip", "hygiene") == 0
    assert len(calls) == 1, f"the ledger probed {len(calls)} times: {calls}"

    # The faulted run probes once too: the filter decision and the row both use
    # the one probe, so a fault must not cost a second read.
    calls.clear()
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")
    assert _code(repo, "--skip", "hygiene") == 0
    assert len(calls) == 1, f"a faulted listing probed {len(calls)} times: {calls}"

    source = _harness_source(CENSUS)
    assert "ledger_probe = _ledger_probe(ledger)" in source
    assert "ledger_probe.listing_fault" in source
    assert "_check_ledger(ledger, git, root, findings, args.strict, ledger_probe)" in source
    assert "_ledger.listing_fault(" not in source, \
        "a second probe path is back: main must read the fault off its one probe"


def test_a_filter_that_named_no_ledger_class_at_all_still_reports_the_fault(
    tmp_path, monkeypatch
):
    """The filter bypass, with a filter that names a class of no ledger group.

    ``--only hygiene`` names neither ``ledger-edited`` nor ``ledger-empty``, so
    without the probe-driven group run this run would report nothing about the
    ledger at all: the group runs because the probe could not read its input, and
    the row survives because it is whole-artifact. Both halves are needed to stop
    a caller buying back the clean verdict with a filter that never mentioned the
    ledger.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    rows = _rows(repo, "--only", "hygiene")
    # hygiene is the class the filter named, and it always reports (an isolated
    # fixture repo has no active deny-list). The row under test is the ledger one.
    ledger_rows = [r for r in rows if r["check"] != "hygiene"]
    assert [r["check"] for r in ledger_rows] == ["ledger-edited"], (
        f"a run that could not list the ledger must say so under a filter that "
        f"named only hygiene: {rows}"
    )
    assert "readdir" in ledger_rows[0]["message"], ledger_rows[0]
    assert _code(repo, "--only", "hygiene") == 0
    # --strict promotes both the fault row (ledger-edited -> 12) and the
    # always-reporting hygiene warn (-> 50); either code is a promoted warn.
    assert _code(repo, "--only", "hygiene", "--strict") in (12, 50)
