"""The three routes to one tool produce the same bytes.

The acceptance criterion is that a tool prints the same thing whether it ran
through its in-place wrapper under ``skills/<skill>/scripts/``, through the
installed ``noni <tool>``, or through ``python -m noni``. This module runs them on
the same arguments and compares stdout, stderr and exit code byte for byte --
including ``--help``, which is where a program-name label derived from ``__file__``
would show up first.

Why the comparison is on bytes and not on "both exited 0": the whole point of the
packaging move is that the wrapper keeps working for the reader who clones the repo,
and the census's fix hints, the writers' refusals and argparse's usage lines all
carry the program name. A label that silently became ``cli.py`` or ``__main__.py``
on one route would keep every behavioural test green and break the documentation the
exit codes point at.

The paired case is driven through each tool's real entry point with real state (a
decision record, a claim row, an ordering artifact) rather than a synthetic no-op,
so the comparison covers a success path and a refusal path per tool.

The fixtures and the byte-comparison are shared with
``tests/test_console_equivalence.py``, which covers the console command itself and
the module route's parity with it; both live in
``tests/console_route_support.py`` so neither file holds a private copy of the one
contract.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from _harness import (
    CENSUS,
    CENSUS_SESSIONS_PY,
    CLAIM,
    DECIDE,
    INTENT,
    ORDER,
    REGISTER,
    REPO,
    _commit_file,
    _git,
    run_module,
    run_noni,
    run_wrapper,
    subprocess_env,
)
from console_route_support import (
    BASELINE_ID,
    INTENT_DRAFT,
    assert_same,
    baseline_repo,
    identity_env,
    identity_repo,
    sid_of_uncommitted,
)

# --- the paired cases ----------------------------------------------------------


def test_census_wrapper_matches_noni_census(tmp_path):
    """The unified census: wrapper and `noni census` agree on a clean repo."""
    repo = baseline_repo(tmp_path)
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z")
    assert_same(run_wrapper(CENSUS, *args), run_noni("census", *args), "census clean")


def test_census_wrapper_matches_noni_census_json(tmp_path):
    """The NDJSON route too: the schema rows are the machine-facing contract."""
    repo = baseline_repo(tmp_path)
    _commit_file(repo, "note.md", "plain note\n")
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json")
    assert_same(run_wrapper(CENSUS, *args), run_noni("census", *args), "census json")


def test_census_wrapper_matches_noni_census_on_a_finding(tmp_path):
    """A failing run pairs too: the exit code and every row must match."""
    repo = baseline_repo(tmp_path)
    bad = json.dumps({"id": "x"})
    _commit_file(repo, "noni/decisions/bad.json", bad)
    args = ("--repo", str(repo), "--now", "2026-10-02T00:00:00Z")
    left, right = run_wrapper(CENSUS, *args), run_noni("census", *args)
    assert_same(left, right, "census finding")
    assert left.returncode == 10, f"expected the schema code, got {left.returncode}"


def test_census_wrapper_matches_noni_census_help():
    """--help pairs: the usage line carries the program name from noni.labels."""
    left, right = run_wrapper(CENSUS, "--help"), run_noni("census", "--help")
    assert_same(left, right, "census --help")
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
    left_repo = identity_repo(tmp_path / "route-wrapper")
    right_repo = identity_repo(tmp_path / "route-console")
    # The allocator picks a random 6-hex id per run, so each route registers a
    # distinct file and the comparison is on the line's label and sentence (the
    # id is the one part of the line the product cannot fix).
    left = run_wrapper(REGISTER, "--repo", str(left_repo), "--identity", "dev-a",
                       env=identity_env())
    right = run_noni("register", "--repo", str(right_repo), "--identity", "dev-b",
                     env=identity_env())
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
    assert_same(left, right, "register --help")
    assert left.returncode == 0, f"expected exit 0, got {left.returncode}: {left.stderr}"
    assert right.returncode == 0, f"expected exit 0, got {right.returncode}: {right.stderr}"
    assert left.stdout.startswith("usage: register.py "), left.stdout[:80]
    assert left.stderr == "", left.stderr
    for flag in ("--repo", "--identity", "--status", "--host", "--worktree", "--file"):
        assert f"{flag}" in left.stdout, f"register --help omits {flag}: {left.stdout}"


def test_claim_wrapper_matches_noni_claim(tmp_path):
    """A claim on a registered session: same row, same line, same exit."""
    repo = identity_repo(tmp_path)
    # Register through the package, then read the id the allocator picked: the
    # --file guard only admits a path the run itself allocated, so the session is
    # named from what the product wrote rather than a fixed name. --no-commit
    # because this fixture makes the register commit itself below (a committed
    # baseline is what the two claim routes then argue over), and register.py
    # commits its own file by default.
    registered = run_wrapper(REGISTER, "--repo", str(repo), "--identity", "dev-a",
                             "--no-commit", env=identity_env())
    assert registered.returncode == 0, registered.stderr
    session_id = sid_of_uncommitted(registered.stdout)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "register")

    claimed = run_wrapper(CLAIM, "--repo", str(repo), "--session-id", session_id,
                          "--task", "#1", env=identity_env())
    assert claimed.returncode == 0, claimed.stderr
    # The second claim of the same task is the refusal path, which is where the
    # label lives on stderr; both routes see the same committed row.
    for name, proc in (("wrapper", run_wrapper(CLAIM, "--repo", str(repo),
                                               "--session-id", session_id, "--task", "#1",
                                               env=identity_env())),
                       ("console", run_noni("claim", "--repo", str(repo),
                                            "--session-id", session_id, "--task", "#1",
                                            env=identity_env()))):
        assert proc.returncode == 2, f"{name}: {proc.returncode} {proc.stderr}"
    left = run_wrapper(CLAIM, "--repo", str(repo), "--session-id", "missing",
                       "--task", "#9", env=identity_env())
    right = run_noni("claim", "--repo", str(repo), "--session-id", "missing",
                     "--task", "#9", env=identity_env())
    assert_same(left, right, "claim missing register")
    assert left.stderr.startswith("claim.py:"), left.stderr


def test_claim_wrapper_matches_noni_claim_help():
    left, right = run_wrapper(CLAIM, "--help"), run_noni("claim", "--help")
    assert_same(left, right, "claim --help")
    assert left.stdout.startswith("usage: claim.py "), left.stdout[:80]


def test_decide_wrapper_matches_noni_decide(tmp_path):
    """A decided record: same stdout, same committed file, same exit."""
    repo = identity_repo(tmp_path)
    answer = ("--scope", "release", "--asked-by", "team-lead",
              "--question", "q1=Ship the beta this week?", "--option", "q1=Ship it",
              "--option", "q1=Wait a week", "--answer", "q1=Wait a week")
    left = run_wrapper(DECIDE, "--repo", str(repo), "--slug", "pair-a", *answer,
                       env=identity_env())
    right = run_noni("decide", "--repo", str(repo), "--slug", "pair-b", *answer,
                     env=identity_env())
    assert left.returncode == 0, left.stderr
    assert right.returncode == 0, right.stderr
    assert left.stdout.replace("pair-a", "X") == right.stdout.replace("pair-b", "X"), (
        f"{left.stdout!r} vs {right.stdout!r}"
    )
    assert left.stderr == right.stderr


def test_decide_wrapper_matches_noni_decide_refusal(tmp_path):
    """The refusal route pairs byte for byte, label included."""
    repo = baseline_repo(tmp_path)
    # A malformed slug is exit 2, printed by _fail with the writer's label.
    args = ("--repo", str(repo), "--slug", "Bad Slug", "--scope", "release",
            "--asked-by", "team-lead")
    assert_same(run_wrapper(DECIDE, *args), run_noni("decide", *args), "decide refusal")


def test_decide_wrapper_matches_noni_decide_help():
    left, right = run_wrapper(DECIDE, "--help"), run_noni("decide", "--help")
    assert_same(left, right, "decide --help")
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
    assert_same(left, right, "decide --help at COLUMNS=80")
    assert "COLUMNS" not in left.stdout, "the width must not leak into the help text"

    # The pin is real, not an accident of the caller's env: the same bytes come
    # out with no COLUMNS in the caller at all.
    monkeypatch.delenv("COLUMNS", raising=False)
    plain_left = run_wrapper(DECIDE, "--help")
    plain_right = run_noni("decide", "--help")
    assert_same(plain_left, plain_right, "decide --help with no caller COLUMNS")
    assert plain_left.stdout == left.stdout, (
        "the launched tools' help bytes moved with the caller's COLUMNS: the pin "
        "is not being applied"
    )


def test_order_wrapper_matches_noni_order(tmp_path):
    """The order writer's success line and the refusal line both pair."""
    repo = baseline_repo(tmp_path)
    left = run_wrapper(ORDER, "--repo", str(repo), "add", "7", "--decision", BASELINE_ID,
                       "--now", "2026-10-02T00:00:00Z", "--no-commit")
    assert left.returncode == 0, left.stderr
    # Adding the same issue again is the refusal path; both routes see the same
    # committed-order state, so both must refuse identically.
    again_left = run_wrapper(ORDER, "--repo", str(repo), "add", "7",
                             "--decision", BASELINE_ID, "--no-commit")
    again_right = run_noni("order", "--repo", str(repo), "add", "7",
                           "--decision", BASELINE_ID, "--no-commit")
    assert_same(again_left, again_right, "order refusal")
    assert again_left.returncode == 4, again_left.stderr
    assert again_left.stderr.startswith("order.py:"), again_left.stderr


def test_order_wrapper_matches_noni_order_help():
    left, right = run_wrapper(ORDER, "--help"), run_noni("order", "--help")
    assert_same(left, right, "order --help")
    assert left.stdout.startswith("usage: order.py "), left.stdout[:80]
    # The module route is the one a reader on the quickstart's PYTHONPATH form has,
    # so its help bytes are the same bytes too (issue #98).
    assert_same(left, run_module("order", "--help"), "order --help via -m noni")


def test_order_missing_verb_agrees_on_all_three_routes(tmp_path):
    """The refusal that names the verbs is byte-identical on every route.

    The line lives in the parser, so all three routes reach it, and a divergence
    here (one route still printing argparse's bare refusal, another printing the
    writer's ``_fail`` shape) is exactly what this module exists to catch. The
    usage print of a missing subcommand is one of the three paths the 3.14 crash
    reached, so exit 2 and no traceback are asserted for each route as well.
    """
    repo = baseline_repo(tmp_path)
    routes = {
        "wrapper": run_wrapper(ORDER, "--repo", str(repo)),
        "console": run_noni("order", "--repo", str(repo)),
        "module": run_module("order", "--repo", str(repo)),
    }
    named = [name for name, proc in routes.items()
             if "choose from: add, move, remove or confirm" in proc.stderr]
    assert named == ["wrapper", "console", "module"], {
        name: proc.stderr for name, proc in routes.items()}
    left = routes["wrapper"]
    assert left.returncode == 2, left.returncode
    for name, proc in routes.items():
        assert_same(left, proc, f"order missing verb via {name}")
        assert "Traceback" not in proc.stderr, f"{name}: {proc.stderr}"


def test_intent_wrapper_matches_noni_intent(tmp_path):
    """The intent writer's success line and its refusal line both pair."""
    repo = baseline_repo(tmp_path)
    draft = tmp_path / "draft.md"
    draft.write_text(INTENT_DRAFT, encoding="utf-8")
    left = run_wrapper(INTENT, "--repo", str(repo), "set", "--from", str(draft),
                       "--decision", BASELINE_ID, "--now", "2026-10-02T00:00:00Z",
                       "--no-commit")
    assert left.returncode == 0, left.stderr
    # A draft that is not an intent file is the refusal path: the shape check runs
    # before anything is written, so both routes see the same bytes and refuse.
    draft.write_text("# Intent\n## Purpose\nOnly one section.\n", encoding="utf-8")
    again_left = run_wrapper(INTENT, "--repo", str(repo), "set", "--from", str(draft),
                             "--decision", BASELINE_ID)
    again_right = run_noni("intent", "--repo", str(repo), "set", "--from", str(draft),
                           "--decision", BASELINE_ID)
    assert_same(again_left, again_right, "intent refusal")
    assert again_left.returncode == 4, again_left.stderr
    assert again_left.stderr.startswith("intent.py:"), again_left.stderr


def test_intent_wrapper_matches_noni_intent_help():
    left, right = run_wrapper(INTENT, "--help"), run_noni("intent", "--help")
    assert_same(left, right, "intent --help")
    assert left.stdout.startswith("usage: intent.py "), left.stdout[:80]
    assert_same(left, run_module("intent", "--help"), "intent --help via -m noni")


def test_intent_missing_verb_agrees_on_all_three_routes(tmp_path):
    """The missing-verb refusal names ``set`` on every route, byte for byte.

    The pilot's second complaint: the run without the verb printed argparse's
    bare "required: subcommand" and never reached the fix line that names it
    (issue #98). All three routes print the same three lines -- usage, refusal,
    the verbs -- and exit 2 without a traceback.
    """
    repo = baseline_repo(tmp_path)
    routes = {
        "wrapper": run_wrapper(INTENT, "--repo", str(repo)),
        "console": run_noni("intent", "--repo", str(repo)),
        "module": run_module("intent", "--repo", str(repo)),
    }
    named = [name for name, proc in routes.items() if "choose from: set" in proc.stderr]
    assert named == ["wrapper", "console", "module"], {
        name: proc.stderr for name, proc in routes.items()}
    left = routes["wrapper"]
    assert left.returncode == 2, left.returncode
    for name, proc in routes.items():
        assert_same(left, proc, f"intent missing verb via {name}")
        assert "Traceback" not in proc.stderr, f"{name}: {proc.stderr}"


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
    assert_same(left, direct, "census-sessions")
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
    assert_same(direct, dispatch, "sessions census via both shims")
    assert direct.returncode == 30, direct.stdout
