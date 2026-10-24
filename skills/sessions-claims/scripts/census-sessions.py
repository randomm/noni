"""The sessions census core.

Reads the session register files under noni/sessions/ and runs the double-claim
arbiter check. Read-only: never writes, never mutates a session file. Output
goes to stdout only (no writes under noni/census/).

The census is the deterministic arbiter for the claim protocol. Two active
claims on the same task from different identities are a double-claim: git
delays the second claimant, it does not lock them out, so the census is the
check that catches it at read time. A claim committed without a register file
is flagged (distinct code) but the session's work is not blocked — the census
is report-only.

Exit codes (lowest wins when several fire, 30 < 31 < 32):
    0   clean — every session file valid, no double-claims
    3   a required tool is missing (checked by the bash wrapper)
    30  double-claim: two active claims on the same task from different identities
    31  a claim row was committed without a register file (work not blocked)
    32  a session file is malformed (missing required field, or a claim row
        with no task reference)

Each non-zero exit prints NDJSON rows on stdout naming the offending task or
file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_FIELDS = ("identity", "host/worktree", "started", "status", "claims")

EXIT_CLEAN = 0
EXIT_TOOLING = 3
EXIT_DOUBLE_CLAIM = 30
EXIT_NO_REGISTER = 31
EXIT_MALFORMED = 32

# Statuses that mark a session as no longer active. A claim from a session in
# one of these states does not count toward the double-claim check.
_INACTIVE_STATUSES = {"closed", "done", "superseded", "ended"}


def _parse_session_file(path: Path) -> dict:
    """Parse a register file into {fields, claims, malformed}.

    A file is malformed when a required field line is missing or a claim row
    has no task reference. An empty claims list is NOT malformed: a session
    with no claims is clean.
    """
    fields: dict[str, str] = {}
    claims: list[str] = []
    malformed: list[str] = []

    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return {"fields": {}, "claims": [], "malformed": ["unreadable file"]}

    for raw in body.splitlines():
        line = raw.strip()
        if not line or not line.startswith("- "):
            continue
        rest = line[2:]
        key, sep, value = rest.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key in REQUIRED_FIELDS:
            fields[key] = value
        elif key == "claim":
            if not value:
                malformed.append("claim row with no task reference")
            else:
                claims.append(value)

    for field in REQUIRED_FIELDS:
        if field not in fields:
            malformed.append(f"missing field: {field}")

    return {"fields": fields, "claims": claims, "malformed": malformed}


def _is_active(status: str) -> bool:
    """A session is active unless its status is a known terminal state."""
    return status.strip().lower() not in _INACTIVE_STATUSES


def run_census(sessions_dir: Path) -> tuple[int, list[dict]]:
    """Run the sessions census. Returns (exit_code, ndjson_rows).

    The exit code follows the priority 30 < 31 < 32 (lowest wins). A missing
    sessions directory is not a violation: no sessions registered is a clean
    state, so it returns (0, []).
    """
    if not sessions_dir.is_dir():
        return EXIT_CLEAN, []

    rows: list[dict] = []

    # Pass 1: parse every *.md file. A file with a claim row but no register
    # (no identity field) is a claim-without-register (31). A file missing
    # some other required field, or with a malformed claim row, is 32.
    files = sorted(p for p in sessions_dir.glob("*.md") if p.is_file())
    claim_pairs: list[tuple[str, str, str]] = []  # (task, identity, session-name)
    saw_claim_without_register = False

    for path in files:
        parsed = _parse_session_file(path)
        problems = parsed["malformed"]
        if problems:
            missing_identity = any("missing field: identity" in p for p in problems)
            has_claims = bool(parsed["claims"])
            if missing_identity and has_claims:
                # A claim row in a file with no register: 31, not 32.
                saw_claim_without_register = True
                rows.append(
                    {
                        "type": "claim-without-register",
                        "file": str(path),
                        "problems": problems,
                    }
                )
            else:
                rows.append(
                    {"type": "malformed", "file": str(path), "problems": problems}
                )
            continue
        fields = parsed["fields"]
        identity = fields.get("identity", "")
        if _is_active(fields.get("status", "")):
            for task in parsed["claims"]:
                claim_pairs.append((task, identity, path.name))

    # Pass 2: double-claim detection (30). Two active claims on the same task
    # from different identities. The same identity in multiple sessions for
    # the same task is reported separately, not as a double-claim.
    task_map: dict[str, dict[str, list[str]]] = {}
    for task, identity, session in claim_pairs:
        task_map.setdefault(task, {}).setdefault(identity, []).append(session)

    for task in sorted(task_map):
        by_identity = task_map[task]
        if len(by_identity) > 1:
            details = [
                {"identity": ident, "sessions": sessions}
                for ident, sessions in sorted(by_identity.items())
            ]
            rows.append({"type": "double-claim", "task": task, "sessions": details})
        else:
            ident = next(iter(by_identity))
            if len(by_identity[ident]) > 1:
                rows.append(
                    {
                        "type": "same-identity-multi-session",
                        "task": task,
                        "identity": ident,
                        "sessions": by_identity[ident],
                    }
                )

    # Priority: lowest code wins (30 < 31 < 32).
    if any(r["type"] == "double-claim" for r in rows):
        status = EXIT_DOUBLE_CLAIM
    elif saw_claim_without_register:
        status = EXIT_NO_REGISTER
    elif any(r["type"] == "malformed" for r in rows):
        status = EXIT_MALFORMED
    else:
        status = EXIT_CLEAN

    return status, rows


def _skipped_labels(status: int) -> list[str]:
    """Which higher-priority checks were not evaluated for this exit code."""
    if status == EXIT_DOUBLE_CLAIM:
        return ["claim-without-register", "malformed"]
    if status == EXIT_NO_REGISTER:
        return ["malformed"]
    return []


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sessions_dir = Path(argv[0]) if argv else Path("noni/sessions")
    status, rows = run_census(sessions_dir)

    for row in rows:
        print(json.dumps(row, ensure_ascii=False))

    if status != EXIT_CLEAN:
        skipped = _skipped_labels(status)
        if skipped:
            print(
                f"census-sessions: exit {status}; checks not evaluated: "
                f"{', '.join(skipped)} (priority 30 < 31 < 32)",
                file=sys.stderr,
            )
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
