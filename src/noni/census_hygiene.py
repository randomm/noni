"""The census's hygiene group: the public-repo tracked-file scan, run in-process.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the checker it imports and the one class it
reports. Both are ordinary package imports (``noni.public_safety``): neither is
loaded by path any more, because inside an installed wheel there is no sibling
file to load and no directory a lookalike could be found on.

The scan is an import, never a subprocess, and the module it imports is
verified before it runs: ``public_safety`` is a committed, editable file of the
tree being audited when that tree carries its own copy, so the check here is
that the census ran the checker it intends to report about — the package module
captured at import time and identified by its own ``__name__`` and type — not
some other object (see ``skills/census/SKILL.md``, "census exit 50 is not the
public_safety gate").
"""

from __future__ import annotations

import collections.abc
import contextlib
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable, Protocol

from . import public_safety as _PACKAGE_PUBLIC_SAFETY
from .census_text import fault_text

# The artifact a not-run hygiene row names, in the census's own hygiene artifact
# namespace. It is a fixed package-relative literal rather than a path computed
# from a file's location: the census never prints a machine-local absolute path,
# and the same bytes must come out of the in-place wrapper and of `noni census`
# from the wheel. See skills/census/SKILL.md, "The hygiene artifact namespace".
HYGIENE_SCAN_ARTIFACT = "noni/public_safety.py"


class PublicSafetyModule(Protocol):
    """The slice of ``noni.public_safety`` the census depends on.

    The scanner is reached through a lookup rather than a static import, so this
    is the only checked description of the contract between the arbiter and the
    checker it runs: a signature drift on public_safety's side is a type error
    against this Protocol rather than an AttributeError at census time.
    ``_denylist_active`` is a private helper of that module; the census calls it
    because public_safety is a gate file whose surface this release may not
    widen, and `_trusted_public_safety` requires it at runtime precisely so the
    coupling is detected as a not-run row rather than an AttributeError.
    """

    def scrub_tracked_files(self, repo: Path) -> tuple[list[str], str | None, Any]: ...

    def _denylist_active(self, denylist: Any) -> bool: ...


# A census-owned registry key, never the shared "public_safety" name: the
# census is a read-only arbiter and must not replace a host application's
# module (or a second census instance's) while it runs its scan.
CENSUS_PS_MODULE_KEY = "noni_census_public_safety"

# The git environment every census git call runs under. The census reads a
# repository someone else may have prepared, with its own privileges, so the
# host's git config must not be able to redirect those read-only calls:
# core.hooksPath and protocol.ext.allow are the two that turn a read into
# arbitrary execution, and an alternate object directory or a rewritten
# objects dir points the reads somewhere else entirely. GIT_CONFIG_GLOBAL /
# GIT_CONFIG_SYSTEM are pinned to the null device rather than merely removed,
# so a system config baked into the image cannot leak back in either.
#
# GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE and friends are deliberately NOT
# touched: clearing them would break the census's honest answer for a git
# worktree, where the tree's .git file is a pointer and the ambient (or
# per-invocation) git environment is what makes `git -C <worktree>` resolve at
# all — and worktree-based callers are exactly who runs the census. A hostile
# GIT_DIR can only make the census read a *different* repository, which every
# class then reports about that tree; it cannot execute anything.
GIT_ENV_NEUTRAL = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _load_public_safety() -> PublicSafetyModule | None:
    """Import ``noni.public_safety`` for the in-process hygiene scan.

    Returns None when the module cannot be imported (a package installed
    without it) or is not the module this census's own package owns: the caller
    then reports that the scan did not run instead of reporting clean.

    The module is taken from the census's own ``sys.modules`` slot when that
    entry already *is* the package's checker — the seams tests monkeypatch
    (``_default_denylist_file``, ``DENYLIST_ENV_VAR``) live on that one object,
    and a fresh import could hand back a different one. Anything else under
    that key is not this census's checker, so the package module is returned
    instead (see :func:`_trusted_public_safety` for what makes it the checker).
    """
    existing = sys.modules.get(CENSUS_PS_MODULE_KEY)
    if _trusted_public_safety(existing):
        return existing
    if not _trusted_public_safety(_PACKAGE_PUBLIC_SAFETY):
        # The scan could not be loaded: the caller reports the scan as not run
        # (never a clean).
        return None
    sys.modules[CENSUS_PS_MODULE_KEY] = _PACKAGE_PUBLIC_SAFETY
    return _PACKAGE_PUBLIC_SAFETY


def _trusted_public_safety(module: object) -> bool:
    """True when ``module`` is the package's own checker and carries the members
    :func:`check_hygiene` calls.

    Trust is module **identity against the package import captured once at
    import time** — the object ``from . import public_safety`` bound, under the
    name it declares for itself (``noni.public_safety``, and it must be a real
    ``types.ModuleType``). The bare ``"public_safety"`` ``sys.modules`` alias is
    deliberately *not* consulted: it is a convenience name the test harness
    registers for tests written against the old flat ``scripts/`` layout, and an
    entry under a name that short is a substitution route, not an anchor. An
    object that merely carries the same attributes (or that an earlier tree put
    under the census's own key) is neither executed nor trusted.

    The name "trusted" is scoped honestly: public_safety is a committed, editable
    file of the very tree being audited when that tree ships its own copy, so
    this is a *consistency* check (the census ran the checker it intends to
    report about, not a stale or foreign module), not a defence against a
    repository that rewrites its own gate. The gate that cannot be satisfied by
    editing the audited tree is `scripts/public_safety.py` run from a clean
    operator checkout before publishing — see skills/census/SKILL.md, "census
    exit 50 is not the public_safety gate".
    """
    if module is not _PACKAGE_PUBLIC_SAFETY:
        return False
    if not isinstance(module, types.ModuleType) or module.__name__ != "noni.public_safety":
        return False
    return all(callable(getattr(module, name, None))
               for name in ("scrub_tracked_files", "_denylist_active", "load_denylist"))


def _hygiene_labels(public_safety) -> set[str]:
    """The label set public_safety can emit, from its own pattern tables.

    Read from the live module rather than duplicated here: the census must not
    hard-code vocabulary that public_safety owns. All of its pattern tables are
    scanned (built-in, fixture home-path, and any other ``*_PATTERNS`` it
    exposes) plus the deny-list label, because the deny-list label is not in
    BUILTIN_PATTERNS — scrub_tracked_files appends it per entry. Tables are
    iterables of ``(pattern, label)`` tuples (the contract public_safety
    declares next to their annotations); anything else contributes no label.
    The census never crashes on a table it cannot walk: the whole walk is
    defensive, so a table whose iteration protocol raises contributes nothing
    and the caller falls back to verbatim rows instead of a traceback that
    would discard every finding this run already collected.

    Compute this once per scan and pass the set to `_split_violation`: it is
    invariant for the whole run, and walking ``vars()`` per violation row buys
    nothing.
    """
    labels: set[str] = {"deny-list entry"}
    try:
        # One guard for the whole walk: the tables are public_safety's data and
        # no shape of them may take the census down.
        items = list(vars(public_safety).items())
    except Exception:
        return labels
    for attr, value in items:
        if not attr.endswith("_PATTERNS"):
            continue
        try:
            if not isinstance(value, collections.abc.Iterable):
                continue
            entries = list(value)
        except Exception:
            # A truthy non-iterable, or a table whose __iter__ / __len__ /
            # __bool__ raises: it contributes no labels.
            continue
        for entry in entries:
            try:
                _pattern, label = entry
            except (TypeError, ValueError):
                continue
            if isinstance(label, str):
                labels.add(label)
    return labels


def _split_violation(violation: str, labels: set[str]) -> tuple[str, int, str] | None:
    """Split a public_safety violation "<path>:<line>: <label>" into parts.

    Returns (path, line, label) or None when the string is not of that shape.

    Splitting cannot be done by counting colons: a tracked path may contain
    one ("x:y/p.txt" is a legal POSIX filename), so splitting at the first
    colon truncates the path and garbles the message — which also breaks the
    documented (artifact, check, subject) sort grouping, because artifact
    becomes the path prefix before the colon. The label is a fixed string from
    public_safety's own tables and contains no colon, so the tail is matched
    against the known label set exactly and everything before ":<line>: " is
    the path.
    """
    if not labels:
        return None
    for label in labels:
        suffix = f": {label}"
        if not violation.endswith(suffix):
            continue
        head = violation[: -len(suffix)]
        path, sep, line_no = head.rpartition(":")
        if sep and path and line_no.isdigit():
            return path, int(line_no), label
        # The suffix matched but the head is not "<path>:<digits>". This label
        # is not the split; a later one in the set may match the same tail with
        # a head that does parse, so keep looking instead of giving up.
        continue
    return None


def check_hygiene(top: Path | None, strict: bool, findings: list[dict], *,
                  row: Callable[..., dict], bounded: Callable[[str], str]) -> None:
    """The public-repo hygiene class (warn 50): the tracked-file scan, run
    in-process (an import, never a subprocess) over the census's own git tree.

    Scope follows the git tree the census already reads (``top``), never the
    ``--ledger``/``--sessions`` overrides: the hygiene rule is about tracked
    files of a repository, which is what the other git-backed checks use too.

    The class always reports, a clean tree included: when the deny-list class
    is not active (absent, corrupt, or present with no entries) exactly one
    warn row says so, so a run that never checked operator names or external
    project names is never mistaken for a hygiene-clean one. Built-in
    violations (machine-local home paths, secret shapes, active deny-list
    entries) get one row each.

    A scan that cannot run (no git tree, or public_safety raising on a failing
    or hung ``git ls-files``) is probe honesty: one warn row naming the scan
    as not run, never a clean.

    The two families of row are told apart by ``subject``, not by prose:
    ``hygiene scan`` = the scan itself, ``deny-list`` = the deny-list half of
    the scan, anything else = ``path:line`` of a violating tracked file (whose
    artifact is that file, root-relative, while the first two name the checker
    in the package-relative hygiene namespace — see SKILL.md, "The hygiene
    artifact namespace"). The deny-list read follows public_safety's own
    precedence, so this class reports the same verdict the operator's own
    ``scripts/public_safety.py`` gate gives.
    """
    def add(subject: str, artifact: str, message: str) -> None:
        # The artifact is already the string the row must carry: either the
        # violating file's path as public_safety reported it (already
        # tree-relative) or the checker's id in the hygiene artifact namespace.
        # It is never a path to be re-rooted into --repo.
        findings.append(row("hygiene", strict, subject, artifact, message, Path(),
                            relative_artifact=False))

    scan_artifact = HYGIENE_SCAN_ARTIFACT

    if top is None:
        add(
            "hygiene scan",
            scan_artifact,
            "hygiene scan did not run: --repo is not a git repository, so no tracked-file "
            "scan was possible — this run is not a hygiene-clean guarantee",
        )
        return

    public_safety = _load_public_safety()
    if public_safety is None:
        # The package was installed without its checker: name the module that
        # was asked for, never a resolved filesystem path (the census never
        # prints a machine-local absolute path).
        add(
            "hygiene scan",
            scan_artifact,
            "hygiene scan did not run: public_safety is not importable from the "
            "noni package — this run is not a hygiene-clean guarantee",
        )
        return

    # The deny-list is operator config, not tree content: the env-named file is
    # the authoritative route, and a deny-list sitting inside the audited tree
    # is not trusted to supply the vocabulary the publishing gate checks.
    # Without it the class reports itself inactive below rather than pretending
    # the operator-name half ran.
    #
    # The scan's own stderr is silenced for the census (see
    # :class:`_QuietScanStderr`): the deny-list state it announces is the row
    # appended below, and a --json run's stderr is to carry this run's own usage
    # and tool faults and nothing else.
    with _pinned_hygiene_env(), _QuietScanStderr():
        try:
            violations, _source, denylist = public_safety.scrub_tracked_files(top)
        except OSError as e:
            # The scan's own read of the tree faulted. ``OSError`` renders itself
            # as the errno words *plus the path it failed on*, so the row is
            # built from the exception's fields rather than from its string:
            # ``fault_text`` keeps the class and the ``strerror`` (the half that
            # says what failed) and never the filename (the half that says where,
            # which no row may print). The scrubber would be the only thing
            # between a host directory and a published report if the string were
            # quoted, and it has lost every race it has been in.
            add(
                "hygiene scan",
                scan_artifact,
                f"hygiene scan did not run: {fault_text(e)} — this run is not a "
                "hygiene-clean guarantee",
            )
            return
        except Exception as e:
            # "Report, never crash": any exception from the scan (a failing or
            # hung git ls-files, an unreadable deny-list store, a malformed
            # pattern table) becomes the not-run row, never a traceback that
            # discards every finding already collected in this run. A public
            # safety scan must not be able to take the whole census down.
            #
            # Not a filesystem fault, so there is no filename to withhold and
            # the exception's own message IS the finding: public_safety raises
            # RuntimeError(f"git ls-files failed: ...") for a scan whose git call
            # did not come back, and a row that named only the class would say
            # that something failed and nothing about what. The text is still
            # somebody else's, so it goes through the scrub-and-clip net that
            # ``bounded`` is.
            add(
                "hygiene scan",
                scan_artifact,
                bounded(f"hygiene scan did not run: {type(e).__name__}: {e} — this run is not a "
                        "hygiene-clean guarantee"),
            )
            return

    labels = _hygiene_labels(public_safety)
    for violation in sorted(violations):
        parsed = _split_violation(violation, labels)
        if parsed is None:
            # Not the documented shape: report the violation verbatim rather
            # than mis-split it (probe honesty — a row that names the whole
            # finding beats a row that garbles it).
            add(violation, violation, f"public hygiene: {violation}")
            continue
        rel, line_no, label = parsed
        add(f"{rel}:{line_no}", rel,
            f"public hygiene: {rel}:{line_no}: {label}")

    if not public_safety._denylist_active(denylist):
        add(
            "deny-list",
            scan_artifact,
            f"deny-list class inactive ({_denylist_state(denylist)}): no deny-list "
            "entry was checked, so operator names, external project/tool names and hostnames "
            "are NOT covered — this run is not a hygiene-clean guarantee",
        )


def _denylist_state(denylist: Any) -> str:
    """Render the deny-list's inactive state word from its result.

    public_safety owns the statuses; this only maps them to a word. The mapping
    is three lines of the census's own reporting — `status` for a file that is
    absent or unreadable, and the comments-only case that loaded "ok" with no
    entries. A status public_safety adds later surfaces under its own name here
    rather than being silently mislabelled. The caller has already established
    the class is inactive, so "ok" with entries cannot reach this function.
    """
    status = getattr(denylist, "status", "absent")
    if status != "ok":
        return str(status)
    return "present but empty" if not getattr(denylist, "entries", []) else "ok"


class _QuietScanStderr:
    """Install a throwaway stderr for the scan, and put the real one back first.

    ``public_safety`` announces an inactive deny-list on ``sys.stderr`` from two
    places (``scrub_tracked_files`` for absent/corrupt, ``load_denylist`` for an
    unreadable candidate, which also leaks a machine-local absolute path). The
    census already reports that same state as a documented ``deny-list`` warn row
    with its own fix hint, so repeating it on stderr makes ``census --json`` a
    stream a machine consumer has to redirect to be clean (issue #77, AC3).

    It is redirected only around the one call, and only for the census, because
    ``public_safety`` is a gate file: its standalone CLI keeps its banner
    (``scripts/public_safety.py``, docs/PUBLISHING.md step 1) and its signature
    is not widened for a caller's convenience.

    The manager is a class rather than a :func:`contextlib.contextmanager`
    generator so the restore is stated where it happens: ``__exit__`` reassigns
    ``sys.stderr`` on the way out, at a point the interpreter has already chosen,
    rather than in a ``finally`` whose position relative to the caller's own
    handler is the interpreter's business. Nothing in the census depends on which
    side of that handler the restore lands: every ``Exception`` the scan raises --
    a hung or failing ``git ls-files``, an unreadable deny-list store, a malformed
    pattern table -- is caught by ``check_hygiene``'s ``except Exception`` and
    becomes the not-run row, and a ``BaseException`` (a Ctrl-C landing on the
    scan's 30 s git call) travels on to the interpreter with its traceback intact.
    "report, never crash" is that guard, not this manager; the manager's job ends
    at putting the stream back, and it does so before anything else can observe
    the swap.

    The buffer keeps the first few writes and nothing else: a banner is a plain
    line and is dropped, and the cap bounds the buffer against a scan that wrote
    without stopping. ``write``/``flush``/``isatty``/``writable`` are answered so
    a caller that inspects the stream during the scan gets a reply rather than an
    ``AttributeError``; ``fileno`` is deliberately absent, because the census
    never hands its stderr to a child and a stub for it would only let a caller
    believe it had a descriptor.
    """

    # Enough of a stream for the calls the scan makes, so a caller that inspects
    # the stream during the scan gets an answer rather than an AttributeError.
    _KEEPS = 3

    def __init__(self) -> None:
        self._chunks: list[str] = []
        self._previous: object = None

    def __enter__(self) -> None:
        self._previous = sys.stderr
        sys.stderr = self
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        # Restore first, then let the exception travel: see the docstring.
        sys.stderr = self._previous
        self._previous = None
        return False

    def write(self, text: str, /) -> int:
        if len(self._chunks) < self._KEEPS:
            self._chunks.append(text)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


@contextlib.contextmanager
def _pinned_hygiene_env():
    """Run the in-process scan with the git environment pinned.

    The census runs public_safety's read-only git calls with its own privileges
    and environment, so the operator's global/system config must not be able to
    redirect them (core.hooksPath, protocol.ext.allow, an alternate object
    store) and no ambient GIT_DIR / GIT_WORK_TREE may move them off the tree
    being audited.

    The deny-list is deliberately NOT pinned here: public_safety's own
    precedence governs (see scripts/public_safety.py, "Deny-list sources"), so
    the census reports the same deny-list verdict the operator's own
    ``scripts/public_safety.py`` gate would — the untracked deny-list of the
    tree being audited, or one named by NONI_SCRUB_DENYLIST, is the vocabulary
    the publish-before-push rule expects there. One owner for that rule.

    The two config files are not pinned here: public_safety passes them to its
    own ``git ls-files`` directly, so the hardening travels with the call rather
    than depending on who wrapped it.
    """
    saved = {k: os.environ.get(k) for k in GIT_ENV_NEUTRAL}
    os.environ.update(GIT_ENV_NEUTRAL)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
