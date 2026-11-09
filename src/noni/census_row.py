"""The census's row factory and its path/time text helpers, split from the census.

The census owns the check contract, the probes and the group wiring; this module owns
the four small functions every group calls through it: the one place a finding row's
shape is written, the two spellings of a path against the audited tree, and the two
parses of the ``--now`` / stamp text. They stay reachable as members of the census
(``census._row`` and friends), re-exported as the one object rather than a copy, so
the tests that pin a row or patch a helper keep naming the module they already import
and the row shape keeps a single owner.

Nothing here classifies a path or reads a repository: the classifier stays with the
census, and these four turn values they were handed into a row or a string.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .census_render import _promote, _severity
from .census_report import CLASS_CODE, WHOLE_ARTIFACT_KEY


def _parse_iso(ts: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_now(value: str | None) -> tuple[datetime | None, str | None]:
    if value is None:
        return datetime.now(timezone.utc), None
    parsed = _parse_iso(value)
    if parsed is None:
        return None, f"error: --now {value!r} is not a valid ISO-8601 timestamp"
    return parsed, None


def _rel_to(top: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def _rel_to_root(root: Path, path: Path) -> str:
    """``path`` spelled from ``root``, or verbatim when it does not live under it.

    ``resolve`` is the one step that cannot be trusted: it follows the chain a
    symlinked artefact stands at, and ``pathlib`` turns an ``ELOOP`` into
    ``RuntimeError``, which is no kind of answer about a path. A row's artifact is
    its root-relative identifier and nothing more, so the unresolvable path is
    reported as it was given rather than ending the run.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)
    except RuntimeError:
        return str(path)


def _row(check: str, strict: bool, subject: str, artifact: str, message: str,
         root: Path, relative_artifact: bool = True, severity: str | None = None,
         whole_artifact: bool = False) -> dict:
    """Build one finding row: the only place a row's shape is written.

    ``code``/``fix`` come from CHECKS and ``severity`` from `_severity`, so a
    new row field (or a change to how those three are derived) is one edit
    here rather than five reporter-by-reporter copies. ``artifact`` is rooted
    into the audited tree by default; a reporter that names an artefact
    outside it passes ``relative_artifact=False`` and supplies its own id.

    ``severity`` overrides the class default for a single row. It exists for
    the probe-honesty case only — a row that reports *this run could not read
    its input* rather than a protocol violation, which is a warn regardless of
    its class. The override goes through `_promote`, so ``--strict`` still
    escalates it and that rule keeps its one owner. A reporter that passes
    ``severity`` must pass the run's ``strict``, not a literal.

    ``whole_artifact`` marks a row as about the file a group was asked to read
    rather than one entry inside it: the marker is ``WHOLE_ARTIFACT_KEY``,
    underscore-keyed so it is stripped at render, and the run's row filter never
    drops such a row (see the module docstring and ``census_run.keep``).
    """
    severity = _promote(severity, strict) if severity else _severity(check, strict)
    return {
        "check": check,
        "code": CLASS_CODE[check],
        "severity": severity,
        "subject": subject,
        "artifact": _rel_to_root(root, Path(artifact)) if relative_artifact else artifact,
        "message": message,
        WHOLE_ARTIFACT_KEY: whole_artifact,
    }
