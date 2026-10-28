"""The two routes to one tool produce the same bytes.

The acceptance criterion is that a tool prints the same thing whether it ran
through its in-place wrapper under ``skills/<skill>/scripts/`` or through the
installed ``noni <tool>``. This module runs both, on the same arguments, and
compares stdout, stderr and exit code byte for byte — including ``--help``,
which is where a program-name label derived from ``__file__`` would show up
first.

Why the comparison is on bytes and not on "both exited 0": the whole point of
the packaging move is that the wrapper keeps working for the reader who clones
the repo, and the census's fix hints, the writers' refusals and argparse's
usage lines all carry the program name. A label that silently became
``cli.py`` or ``__main__.py`` on one route would keep every behavioural test
green and break the documentation the exit codes point at.

The paired case is driven through each tool's real entry point with real state
(a decision record, a claim row, an ordering artifact) rather than a synthetic
no-op, so the comparison covers a success path and a refusal path per tool.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from _harness import (
    CENSUS,
    CENSUS_SESSIONS_PY,
    CLAIM,
    DECIDE,
    ORDER,
    REGISTER,
    REPO,
    _commit_file,
    _git,
    _git_env_with_identity,
    _init_repo,
    run_noni,
    run_wrapper,
    subprocess_env,
)

# One baseline repo per test: a committed decision record the order writer can
# cite, so the tools have real state to act on.
BASELINE_ID = "2026-10-01-baseline"

# The identity the writers commit under. decide.py takes ``by`` from
# ``git config user.name`` and refuses exit 3 without it, so a launched writer
# needs the deterministic identity the harness uses everywhere else; a test that
# wants the missing-identity refusal passes its own env instead.
IDENTITY_ENV = {**_git_env_with_identity(),
               "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _identity_env() -> dict:
    env = subprocess_env()
    env.update(IDENTITY_ENV)
    return env


def _repo(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path / "repo")
    record = {
        "id": BASELINE_ID,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "team-lead",
        "questions": [{"id": "q1", "text": "Ship?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Operator",
        "scope": "release",
        "status": "decided",
        "supersedes": None,
    }
    _commit_file(repo, f"noni/decisions/{BASELINE_ID}.json", json.dumps(record, indent=2) + "\n")
    return repo


def _sid_of_uncommitted(stdout: str) -> str:
    """The session id in a ``--no-commit`` register line.

    The line names the file it left in the work tree
    (``register.py: <path>/<id>.md left uncommitted``); the id is that path's
    stem, which is the session id.
    """
    tail = stdout.strip().split(" -> ")[-1].rsplit(" left uncommitted", 1)[0]
    return tail.rsplit("/", 1)[-1].removesuffix(".md")


def _identity_repo(tmp_path: Path) -> Path:
    """The baseline repo with a real git identity in its own config.

    ``decide.py`` takes ``by`` from ``git config user.name`` of the tree and
    refuses exit 3 without it, so a writer run that must reach the commit needs
    the identity in the repo, not only in the child env (the harness pins the
    author/committer vars, which answer the commit but not the attribution).
    """
    repo = _repo(tmp_path)
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    return repo


def _assert_same(left: subprocess.CompletedProcess[str],
                 right: subprocess.CompletedProcess[str], label: str) -> None:
    """Both routes: same exit code, same stdout, same stderr, byte for byte.

    A traceback is itself a failure, before the comparison: a crash on both
    routes would compare equal, and the harness frames (``<frozen runpy>``, the
    dispatch module) differ between them for reasons that say nothing about the
    tool. So a crash is named as one rather than reported as a mismatch.
    """
    for name, proc in (("wrapper", left), ("console", right)):
        assert "Traceback (most recent call last)" not in proc.stderr, (
            f"{label}: the {name} route crashed\n{proc.stderr}"
        )
    assert left.returncode == right.returncode, (
        f"{label}: exit codes differ ({left.returncode} vs {right.returncode})\n"
        f"wrapper stdout: {left.stdout!r}\nconsole stdout: {right.stdout!r}\n"
        f"wrapper stderr: {left.stderr!r}\nconsole stderr: {right.stderr!r}"
    )
    assert left.stdout == right.stdout, f"{label}: stdout differs\n{left.stdout!r}\n{right.stdout!r}"
    assert left.stderr == right.stderr, f"{label}: stderr differs\n{left.stderr!r}\n{right.stderr!r}"


# --- the paired cases ----------------------------------------------------------


def test_census_wrapper_matches_noni_census(tmp_path):
    """The unified census: wrapper and `noni census` agree on a clean repo."""
    repo = _repo(tmp_path)
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z")
    _assert_same(run_wrapper(CENSUS, *args), run_noni("census", *args), "census clean")


def test_census_wrapper_matches_noni_census_json(tmp_path):
    """The NDJSON route too: the schema rows are the machine-facing contract."""
    repo = _repo(tmp_path)
    _commit_file(repo, "note.md", "plain note\n")
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json")
    _assert_same(run_wrapper(CENSUS, *args), run_noni("census", *args), "census json")


def test_census_wrapper_matches_noni_census_on_a_finding(tmp_path):
    """A failing run pairs too: the exit code and every row must match."""
    repo = _repo(tmp_path)
    bad = json.dumps({"id": "x"})
    _commit_file(repo, "noni/decisions/bad.json", bad)
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z")
    left, right = run_wrapper(CENSUS, *args), run_noni("census", *args)
    _assert_same(left, right, "census finding")
    assert left.returncode == 10, f"expected the schema code, got {left.returncode}"


def test_census_wrapper_matches_noni_census_help():
    """--help pairs: the usage line carries the program name from noni.labels."""
    left, right = run_wrapper(CENSUS, "--help"), run_noni("census", "--help")
    _assert_same(left, right, "census --help")
    assert left.stdout.startswith("usage: census.py "), left.stdout[:80]


def test_register_wrapper_matches_noni_register(tmp_path):
    """A registration writes a file and prints one line; both routes agree.

    The two routes run in two separate working copies: register.py marks the
    working copy that allocated a session, so a second registration in the same
    tree is a reuse of the first (or a refusal of it), not a second allocation —
    and this test wants to compare two allocation lines. One clone per route
    keeps the comparison byte-exact and leaves the marker semantics to
    test_register_defaults, where they are the subject.
    """
    left_repo = _identity_repo(tmp_path / "route-wrapper")
    right_repo = _identity_repo(tmp_path / "route-console")
    # The allocator picks a random 6-hex id per run, so each route registers a
    # distinct file and the comparison is on the line's label and sentence (the
    # id is the one part of the line the product cannot fix).
    left = run_wrapper(REGISTER, "--repo", str(left_repo), "--identity", "dev-a",
                       env=_identity_env())
    right = run_noni("register", "--repo", str(right_repo), "--identity", "dev-b",
                     env=_identity_env())
    assert left.returncode == 0, left.stderr
    assert right.returncode == 0, right.stderr
    left_head, left_body = left.stdout.split(": ", 1)
    right_head, right_body = right.stdout.split(": ", 1)
    assert left_head == right_head == "register.py", (left.stdout, right.stdout)
    left_verb, _, left_id = left_body.split(" -> ")[0].partition(" session ")
    right_verb, _, right_id = right_body.split(" -> ")[0].partition(" session ")
    assert left_verb == right_verb == "registered", (left.stdout, right.stdout)
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{6}", left_id), left.stdout
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{6}", right_id), right.stdout
    assert left.stderr == right.stderr == ""


def test_register_wrapper_matches_noni_register_help():
    """--help pairs: help prints on both routes and exits 0, like the other tools.

    A team trying noni runs ``noni register --help`` first, so it must be help,
    not the missing-arguments refusal.
    """
    left, right = run_wrapper(REGISTER, "--help"), run_noni("register", "--help")
    _assert_same(left, right, "register --help")
    assert left.returncode == 0, f"expected exit 0, got {left.returncode}: {left.stderr}"
    assert right.returncode == 0, f"expected exit 0, got {right.returncode}: {right.stderr}"
    assert left.stdout.startswith("usage: register.py "), left.stdout[:80]
    assert left.stderr == "", left.stderr
    for flag in ("--repo", "--identity", "--status", "--host", "--worktree", "--file"):
        assert f"{flag}" in left.stdout, f"register --help omits {flag}: {left.stdout}"


def test_claim_wrapper_matches_noni_claim(tmp_path):
    """A claim on a registered session: same row, same line, same exit."""
    repo = _identity_repo(tmp_path)
    # Register through the package, then read the id the allocator picked: the
    # --file guard only admits a path the run itself allocated, so the session is
    # named from what the product wrote rather than a fixed name. --no-commit
    # because this fixture makes the register commit itself below (a committed
    # baseline is what the two claim routes then argue over), and register.py
    # commits its own file by default.
    registered = run_wrapper(REGISTER, "--repo", str(repo), "--identity", "dev-a",
                             "--no-commit", env=_identity_env())
    assert registered.returncode == 0, registered.stderr
    session_id = _sid_of_uncommitted(registered.stdout)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "register")

    claimed = run_wrapper(CLAIM, "--repo", str(repo), "--session-id", session_id,
                          "--task", "#1", env=_identity_env())
    assert claimed.returncode == 0, claimed.stderr
    # The second claim of the same task is the refusal path, which is where the
    # label lives on stderr; both routes see the same committed row.
    for name, proc in (("wrapper", run_wrapper(CLAIM, "--repo", str(repo),
                                               "--session-id", session_id, "--task", "#1",
                                               env=_identity_env())),
                       ("console", run_noni("claim", "--repo", str(repo),
                                            "--session-id", session_id, "--task", "#1",
                                            env=_identity_env()))):
        assert proc.returncode == 2, f"{name}: {proc.returncode} {proc.stderr}"
    left = run_wrapper(CLAIM, "--repo", str(repo), "--session-id", "missing",
                       "--task", "#9", env=_identity_env())
    right = run_noni("claim", "--repo", str(repo), "--session-id", "missing",
                     "--task", "#9", env=_identity_env())
    _assert_same(left, right, "claim missing register")
    assert left.stderr.startswith("claim.py:"), left.stderr


def test_claim_wrapper_matches_noni_claim_help():
    left, right = run_wrapper(CLAIM, "--help"), run_noni("claim", "--help")
    _assert_same(left, right, "claim --help")
    assert left.stdout.startswith("usage: claim.py "), left.stdout[:80]


def test_decide_wrapper_matches_noni_decide(tmp_path):
    """A decided record: same stdout, same committed file, same exit."""
    repo = _identity_repo(tmp_path)
    answer = ("--scope", "release", "--asked-by", "team-lead",
              "--question", "q1=Ship the beta this week?", "--option", "q1=Ship it",
              "--option", "q1=Wait a week", "--answer", "q1=Wait a week")
    left = run_wrapper(DECIDE, "--repo", str(repo), "--slug", "pair-a", *answer,
                       env=_identity_env())
    right = run_noni("decide", "--repo", str(repo), "--slug", "pair-b", *answer,
                     env=_identity_env())
    assert left.returncode == 0, left.stderr
    assert right.returncode == 0, right.stderr
    assert left.stdout.replace("pair-a", "X") == right.stdout.replace("pair-b", "X"), (
        f"{left.stdout!r} vs {right.stdout!r}"
    )
    assert left.stderr == right.stderr


def test_decide_wrapper_matches_noni_decide_refusal(tmp_path):
    """The refusal route pairs byte for byte, label included."""
    repo = _repo(tmp_path)
    # A malformed slug is exit 2, printed by _fail with the writer's label.
    args = ("--repo", str(repo), "--slug", "Bad Slug", "--scope", "release",
            "--asked-by", "team-lead")
    _assert_same(run_wrapper(DECIDE, *args), run_noni("decide", *args), "decide refusal")


def test_decide_wrapper_matches_noni_decide_help():
    left, right = run_wrapper(DECIDE, "--help"), run_noni("decide", "--help")
    _assert_same(left, right, "decide --help")
    assert left.stdout.startswith("usage: decide.py "), left.stdout[:80]


def test_decide_help_pair_is_width_independent(tmp_path, monkeypatch):
    """The --help pair matches byte for byte even when the caller's environment
    asks for a different terminal width.

    argparse wraps its usage and option help to ``COLUMNS``, so on an unwrapped
    harness the two routes would emit different bytes as soon as the suite ran
    under a width neither launcher pinned (a piped CI run, an 80-column tmux
    pane): the equivalence test would then pass or fail on the machine reading
    it. The harness pins the width for every launch, so this caller-set 80
    cannot reach either tool and the pair still matches.
    """
    monkeypatch.setenv("COLUMNS", "80")
    left = run_wrapper(DECIDE, "--help", env={**subprocess_env(), "COLUMNS": "80"})
    right = run_noni("decide", "--help", env={**subprocess_env(), "COLUMNS": "80"})
    _assert_same(left, right, "decide --help at COLUMNS=80")
    assert "COLUMNS" not in left.stdout, "the width must not leak into the help text"

    # The pin is real, not an accident of the caller's env: the same bytes come
    # out with no COLUMNS in the caller at all.
    monkeypatch.delenv("COLUMNS", raising=False)
    plain_left = run_wrapper(DECIDE, "--help")
    plain_right = run_noni("decide", "--help")
    _assert_same(plain_left, plain_right, "decide --help with no caller COLUMNS")
    assert plain_left.stdout == left.stdout, (
        "the launched tools' help bytes moved with the caller's COLUMNS: the pin "
        "is not being applied"
    )


def test_order_wrapper_matches_noni_order(tmp_path):
    """The order writer's success line and the refusal line both pair."""
    repo = _repo(tmp_path)
    left = run_wrapper(ORDER, "--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                       "--now", "2026-10-02T00:00:00Z", "--no-commit")
    assert left.returncode == 0, left.stderr
    # Adding the same issue again is the refusal path; both routes see the same
    # committed-order state, so both must refuse identically.
    again_left = run_wrapper(ORDER, "--repo", str(repo), "add", "7",
                             "--decision", BASELINE_ID, "--no-commit")
    again_right = run_noni("order", "--repo", str(repo), "add", "7",
                           "--decision", BASELINE_ID, "--no-commit")
    _assert_same(again_left, again_right, "order refusal")
    assert again_left.returncode == 4, again_left.stderr
    assert again_left.stderr.startswith("order.py:"), again_left.stderr


def test_order_wrapper_matches_noni_order_help():
    left, right = run_wrapper(ORDER, "--help"), run_noni("order", "--help")
    _assert_same(left, right, "order --help")
    assert left.stdout.startswith("usage: order.py "), left.stdout[:80]


def test_census_sessions_wrapper_matches_the_package(tmp_path):
    """The sessions census has no subcommand of its own (the shim's --sessions
    dispatch owns it), so its wrapper is compared against the package module."""
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    body = ("- identity: dev-a\n- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n- claims:\n  - claim: #42\n")
    (sessions / "2026-10-01-aaaaaa.md").write_text(body, encoding="utf-8")
    (sessions / "2026-10-01-bbbbbb.md").write_text(body.replace("dev-a", "dev-b"),
                                                   encoding="utf-8")
    left = run_wrapper(CENSUS_SESSIONS_PY, str(sessions))
    right = run_noni("census-sessions-module", str(sessions))
    # The module has no console subcommand, so the console route above is not a
    # route: run the module the way the package's own entry point does.
    direct = subprocess.run(
        [sys.executable, "-c",
         "import sys; from noni import census_sessions; "
         "raise SystemExit(census_sessions.main(sys.argv[1:]))", str(sessions)],
        capture_output=True, text=True, env=subprocess_env(), timeout=120,
    )
    assert right.returncode == 2, "noni must not grow a census-sessions subcommand"
    _assert_same(left, direct, "census-sessions")
    assert left.returncode == 30, left.stdout


def test_sessions_shim_and_census_shim_agree_on_sessions(tmp_path):
    """`census.sh --sessions` and the direct shim reach the same arbiter."""
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    body = ("- identity: dev-a\n- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n- claims:\n  - claim: #42\n")
    (sessions / "2026-10-01-aaaaaa.md").write_text(body, encoding="utf-8")
    (sessions / "2026-10-01-bbbbbb.md").write_text(body.replace("dev-a", "dev-b"),
                                                   encoding="utf-8")
    direct = subprocess.run(["bash", str(REPO / "skills" / "sessions-claims" / "scripts"
                                           / "census-sessions.sh"), str(sessions)],
                            capture_output=True, text=True, env=subprocess_env(), timeout=60)
    dispatch = subprocess.run(["bash", str(REPO / "skills" / "steering-ledger" / "scripts"
                                           / "census.sh"), "--sessions", str(sessions)],
                              capture_output=True, text=True, env=subprocess_env(), timeout=60)
    _assert_same(direct, dispatch, "sessions census via both shims")
    assert direct.returncode == 30, direct.stdout


# --- the console command itself ------------------------------------------------


def test_noni_without_a_subcommand_is_a_usage_error():
    """No tool named: the command prints its own help and exits 2."""
    proc = run_noni()
    assert proc.returncode == 2, proc.stdout
    assert (proc.stdout + proc.stderr).startswith("usage: noni "), proc.stdout[:60]


def test_noni_names_exactly_the_seven_subcommands():
    """The subcommand set is the settled one: census, register, claim, close,
    release, decide, order.

    close and release are #27's session-lifecycle verbs, not placeholders: each
    names a module under ``src/noni/`` and a wrapper under the skill, and both
    are asserted dispatchable below. ``session`` remains refused — it is a noun
    for the state, not a tool, and a subcommand that vague would let a typo look
    like a real command.
    """
    proc = run_noni("--help")
    assert proc.returncode == 0
    listed = proc.stdout + proc.stderr
    for name in ("census", "register", "claim", "close", "release",
                 "decide", "order"):
        assert f"{name}  " in listed, f"noni --help omits {name}: {listed}"
    for absent in ("session",):
        assert f"{absent}  " not in listed, f"noni grew a {absent} placeholder: {listed}"


def test_noni_console_script_is_installed_in_this_environment():
    """The ``noni`` console script exists and runs the census.

    The CI wheel job asserts this against the built wheel; locally it asserts
    against the editable install, so a broken [project.scripts] target fails
    somewhere rather than only in CI.
    """
    proc = subprocess.run([sys.executable, "-m", "noni.cli", "census", "--list"],
                          capture_output=True, text=True, env=subprocess_env(), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "ledger-record" in proc.stdout.splitlines()
