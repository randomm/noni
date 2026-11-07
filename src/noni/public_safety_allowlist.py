"""The committed per-tree allowlist that makes an intentional fixture visible.

The hygiene scan has no way to say "this file holds a fake token on purpose": a
tracked fixture built to prove the secret shapes catch something trips the check
it documents, and the only exemption the checker had was a hard-coded list of
three of noni's own files (``_SELF_FILES`` in ``public_safety``). This module is
the general form of that exemption: a committed file in the tree being audited
that names, per exact tracked path, the one finding label that path may carry
and why.

Why committed rather than local, unlike the deny-list: an allowlist widens what
the gate accepts, so it has to be reviewable, and a file git ignores would let
anyone quietly declare their tree clean. It is therefore tracked, and it is read
from the tree being audited, never from the process's cwd: this module ships
inside a wheel and the gate may run from anywhere.

Three rules hold the exemption narrow, and all three are load-bearing:

- **Exact paths only.** No glob, no directory, no prefix. ``git ls-files`` names
  are repository-relative with forward slashes, so a normalisation step (strip a
  leading ``./``, fold case) would silently widen matching on a case-sensitive
  filesystem. Comparison is byte-for-byte on the listing's own bytes; the only
  thing dropped is whitespace around a field, which an entry can be typed with
  and a listing cannot.
- **One label per path, and never the deny-list class.** The exemption keys on
  the (path, label) pair, so a second, non-allowlisted label on the same line
  still fails. ``"deny-list entry"`` is refused at load time: the deny-list is
  the operator's own vocabulary and a committed file must not switch half of it
  off.
- **Neither config file exempts anything.** An entry naming the allowlist or the
  deny-list is refused at load time rather than honoured, so the file cannot
  exempt itself and cannot be used to hide the deny-list the operator wrote.

Every state but an absent file is reported. A malformed, non-regular or
oversized file is the gate-could-not-run state and never a silent skip, because
the failure mode this feature adds is an exemption nobody reviewed.

The read is the guarded one (``public_safety_io.open_regular``), the same seam
#91 forced on every other blocking open in this package: the allowlist path is
someone else's tree, and a named pipe there must be refused at the open rather
than waited on.

Import contract: part of the installed ``noni`` package, as
``noni.public_safety_allowlist``. ``noni.public_safety`` imports it and re-binds
its names, so the scan and its tests reach the whole contract through the module
that owns the scan.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import public_safety_io as _io

# The deny-list's committed name, resolved lazily through the package so the two
# hygiene configuration files have one owner each and this module never grows a
# second spelling of the other one. ``public_safety`` imports this module, so the
# lookup happens at call time and not at import.
_DENYLIST_FILENAME_LOOKUP = "DENYLIST_FILENAME"

# The committed allowlist's name, at the root of the tree being audited. Follows the
# deny-list's convention (``DENYLIST_FILENAME``) and, unlike that file, this one is
# tracked: the docs tests read this constant rather than typing the name, so a rename
# strands the page instead of the suite.
ALLOWLIST_FILENAME = ".noni-scrub-allowlist"

# The row labels of the two findings this module can raise, and the pattern table that
# publishes them. The census harvests its label vocabulary from ``*_PATTERNS``
# attributes (``census_hygiene._hygiene_labels``) rather than hard-coding one, and a
# label it has never seen is reported verbatim: subject and artifact both the whole
# finding, which breaks the documented path:line subject contract. So both labels live
# in a table here, beside the code that emits them, and each entry's first slot stays
# None the way ``UNREADABLE_TRACKED_FILE_PATTERNS`` leaves it: no pattern selects these
# classes, the file earns them.
ALLOWLIST_STALE_LABEL = "allowlist entry matches nothing"
ALLOWLIST_REFUSED_LABEL = "allowlist entry refused"
ALLOWLIST_PATTERNS: tuple[tuple[None, str], ...] = (
    (None, ALLOWLIST_STALE_LABEL),
    (None, ALLOWLIST_REFUSED_LABEL),
)

# The class no allowlist may exempt: the deny-list half of the scan.
_DENYLIST_LABEL = "deny-list entry"

# How many per-line rows one file may contribute. Past this the verdict is already
# "the file was refused" and further rows add nothing a reader can act on, while an
# unbounded list would let a hostile file turn the row buffer into the report.
_MAX_FINDINGS = 50


@dataclass
class AllowlistEntry:
    """One reviewed exemption: a tracked path, the label it may carry, and why."""

    path: str
    label: str
    reason: str


@dataclass
class AllowlistResult:
    """Outcome of :func:`load_allowlist`: entries, source, and an explicit status.

    ``status`` is "ok" (a file was read; entries may be empty for a comments-only
    file), "absent" (no candidate exists), "malformed" (a file was read and refused
    to parse: a bad line, or an entry naming a label or path that may not be
    exempted) or "unreadable" (a candidate existed but the read declined it: not a
    regular file, past the size bound, or not valid UTF-8).

    The last two are the gate-could-not-run states, and they are distinct because
    their fixes differ: one is a rewrite of the file's contents, the other its
    permissions or its size. Both answer exit 3 at the CLI and the same hygiene row
    at the census: a gate that could not read the exemptions it was told to honour
    did not run, and CI tolerates exit 2 but never 3.

    ``source`` is the file the verdict came from, tree-relative when the audited tree
    holds it, which is the only route there is. ``findings`` carries one
    ``path:line: label`` string per stale or
    refused entry, in the shape the scan's own violations use, so the census splits
    them into path/line/label rows with no extra vocabulary.
    """

    entries: list[AllowlistEntry]
    source: str | None
    status: Literal["ok", "absent", "malformed", "unreadable"]
    findings: list[str]


def default_allowlist_file(repo: Path) -> Path:
    """The committed allowlist path of the tree being audited."""
    return Path(repo).resolve() / ALLOWLIST_FILENAME


def _default_allowlist_file(repo: Path) -> Path:
    """The seam tests patch: the tree's own allowlist path.

    A separate name from the public one, as ``_default_denylist_file`` is for the
    deny-list: the scan reaches the default through this spelling, so a test can
    point it elsewhere without touching what docs and tests name.
    """
    return default_allowlist_file(repo)


def _load_candidates(repo: Path) -> list[Path]:
    """The one allowlist this run may honour: the tree's own committed file.

    There is no environment route. An allowlist widens what the gate accepts, so the
    only file that may widen it is one a reviewer saw in the diff: a file named from
    outside the tree is not tracked, and an exemption that arrives that way is the
    exemption nobody reviewed. The deny-list keeps its env route because that file only
    ever narrows the check.

    The default is reached through ``public_safety`` -- the module that owns the scan and
    the name the tests patch -- because there is one per-tree config default per scan and
    it must have one patch point. Falling back to this module's own copy keeps the loader
    usable on its own (a tool that imports only the loader) without giving the two
    modules two seams that a test would have to bend in tandem.
    """
    from . import public_safety

    return [public_safety._default_allowlist_file(repo)]


def _read_candidate(path: Path) -> tuple[str | None, str]:
    """The text of the committed allowlist, plus a reason word when it has none.

    ``(text, "")`` is a body to parse; ``(None, "")`` is a path that simply is not
    there (the open faulted with ENOENT/ENOTDIR, or the kind has no content), which
    is absence and stays silent; ``(None, reason)`` is a file that exists and was
    declined. Never a raw exception message: ``public_safety_io`` owns the guard and
    hands back class and errno words, and the words below are this module's own.
    """
    fd, fault = _io.open_regular(path)
    if fd is None and fault is None:
        return None, ""
    if fd is None:
        return None, ": ".join(filter(None, fault)) or "could not be opened"
    if fd == _io.NOT_REGULAR:
        # The guard already gave the descriptor back; NOT_REGULAR only says the kind
        # was refused. A fifo, a socket or a directory where the tree stated an
        # allowlist is a file that exists and cannot be read, not a missing one.
        return None, "it is not a regular file"
    try:
        raw = _io.read_bytes_capped(fd)
    except OSError as read_fault:
        _io.close(fd)
        return None, ": ".join(filter(None, _io.fault_pair(read_fault)))
    _io.close(fd)
    if raw is None:
        return None, "past the scan's size bound"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "not valid UTF-8"


def _denylist_filename() -> str:
    """The deny-list's committed name, asked of the module that owns it.

    Asked rather than imported: ``public_safety`` imports this module, so a
    module-level import would be circular, and a literal copy here is the drift the
    refusal rule exists to prevent.
    """
    from . import public_safety

    return str(getattr(public_safety, _DENYLIST_FILENAME_LOOKUP, ""))


def _entry_problem(path: str, label: str) -> str | None:
    """Why this entry may not be honoured, or None when it may.

    The three refusals are the rules that keep the exemption from widening: the
    deny-list class is not exemptable, neither hygiene config file is exemptable,
    and a path has to read as one tracked name rather than a pattern.
    """
    if label == _DENYLIST_LABEL:
        return "the deny-list class cannot be exempted"
    if path in (ALLOWLIST_FILENAME, _denylist_filename()):
        return "a hygiene configuration file cannot be exempted"
    if not _looks_like_tracked_path(path):
        return "an entry must name one exact tracked path"
    return None


def _looks_like_tracked_path(path: str) -> bool:
    """True for the shape ``git ls-files`` produces, and nothing wider.

    Repository-relative, forward slashes, no leading slash, home expansion, drive
    spec, parent traversal, and none of the characters a pattern would need: ``*``,
    ``?`` and ``[`` (a glob), ``~`` (a home expansion), ``\\`` (a Windows separator)
    and ``$`` (an expansion a reviewer would read as part of the name). ``..`` is
    refused as a path *component*, so an entry can never reach outside the tree it
    documents; ``a..b.txt`` stays a name.
    """
    if not path or path[0] in ("/", "~"):
        return False
    if "\\" in path or "$" in path or "~" in path:
        return False
    if any(char in path for char in "*?["):
        return False
    if ":" in path[:2]:  # a drive spec: "C:/…" or "C:\…"
        return False
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    return True


def _parse_allowlist(raw: str) -> tuple[list[AllowlistEntry], list[str], list[str]]:
    """The entries, the finding rows, and the reasons the file must be refused.

    Blank lines and ``#`` comments carry no exemption; any other line is
    ``path | label | reason``, split on the first two pipes so the reason may carry
    more (it is free text for a reviewer, and a reason that quoted a shell pipeline
    is not a malformed file). A line that cannot be read that way is a finding naming
    its line number: silence on a line nobody wrote is the exemption nobody reviewed.
    An entry whose label or path may not be exempted is refused outright.
    """
    entries: list[AllowlistEntry] = []
    findings: list[str] = []
    refusals: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split("|", 2)
        if len(fields) != 3:
            findings.append(f"{ALLOWLIST_FILENAME}:{lineno}: malformed allowlist line")
            refusals.append(f"line {lineno} is not path | label | reason")
            continue
        path, label, reason = (field.strip() for field in fields)
        problem = _entry_problem(path, label)
        if problem is not None:
            findings.append(f"{ALLOWLIST_FILENAME}:{lineno}: {ALLOWLIST_REFUSED_LABEL}"
                            f" ({problem})")
            refusals.append(problem)
            continue
        if not reason:
            findings.append(f"{ALLOWLIST_FILENAME}:{lineno}: malformed allowlist line")
            refusals.append(f"line {lineno} carries no reason")
            continue
        entries.append(AllowlistEntry(path, label, reason))
    return entries, findings[:_MAX_FINDINGS], refusals


def _source_of(candidate: Path, repo: Path) -> str:
    """The allowlist's identity for a row: tree-relative when the tree holds it.

    The census never prints a machine-local absolute path, so the file is named by its
    repository-relative path. A path that will not root inside the tree (a symlink onto
    a target outside it, a tree on a mount that moved) still gets a name rather than a
    host path, so the fallback stays and is not a route of its own.
    """
    try:
        return candidate.resolve().relative_to(Path(repo).resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        return candidate.name


def _listing_of(repo: Path) -> list[str]:
    """The audited tree's tracked names, asked of the scan's own hardened listing.

    Reached through the scan module (which owns the hardened ``git ls-files``) rather than
    by running git here: the scan and the stale-entry check must ask one listing, or a
    live exemption reports as stale depending on which caller answered first. Imported
    inside the function because ``public_safety`` imports this module, so a module-level
    import of the sibling that imports this one would be a cycle at load time.
    """
    from .public_safety_scan import tracked_listing

    return tracked_listing(repo)


def load_allowlist(repo: Path) -> AllowlistResult:
    """Load the committed allowlist of ``repo`` and classify the outcome.

    Returns an explicit status rather than raising: the scan's contract is to report,
    never to crash, and the caller decides what each state costs (the CLI exits 3 on
    both failure states, the census earns a row for each). Absence is the only quiet
    state, because an attached project that wrote no allowlist is a real state rather
    than an oversight: the exemption mechanism is opt-in.

    The tree's committed file is the only candidate. Nothing else is consulted when it
    cannot be read or parsed, because honouring a different file than the one the tree
    committed would report one set of exemptions as another.
    """
    candidate, = _load_candidates(repo)
    raw, reason = _read_candidate(candidate)
    if raw is None and not reason:
        # Nothing at the committed path and nothing to report: absence. Only a path the
        # filesystem describes as absent counts -- a directory or an empty path is not
        # "no allowlist", and answering so would read a wrong location as a tree that
        # opted out of the mechanism.
        if _io.is_absent(candidate):
            return AllowlistResult([], None, "absent", [])
        return AllowlistResult([], None, "malformed", [_refused_row(
            "the allowlist path is not a readable file")])
    if raw is None:
        # A file that exists and was declined: a fifo, a file the filesystem
        # refused, a body past the bound, bytes that are not UTF-8. Not a skip:
        # the tree stated an allowlist and this run could not hold it.
        print(f"public-safety: WARNING — allowlist {candidate.as_posix()} is "
              f"unusable ({reason}); the gate cannot run without reading it.",
              file=sys.stderr)
        return AllowlistResult([], candidate.as_posix(), "unreadable",
                               [_refused_row(reason)])
    entries, findings, refusals = _parse_allowlist(raw)
    source = _source_of(candidate, repo)
    if refusals:
        detail = f" ({refusals[0]})" if len(refusals) == 1 else ""
        print(f"public-safety: WARNING — allowlist {source} was refused{detail}; "
              "the gate cannot run until the file names only exemptable entries.",
              file=sys.stderr)
        return AllowlistResult(entries, source, "malformed", findings)
    # A file that parsed is checked against the listing before it is handed back, so
    # the stale rows travel on the result: every caller of the loader -- the scan, the
    # gate, a test -- sees a stale entry without having to remember to ask for it.
    findings = findings + stale_entry_findings(
        AllowlistResult(entries, source, "ok", []), set(_listing_of(repo)))
    return AllowlistResult(entries, source, "ok", sorted(findings))


def _refused_row(reason: str) -> str:
    """One row naming the allowlist file and why this run could not use it.

    The state rows name the file rather than a path inside it, at line 0: like the
    unreadable-tracked-file class, the finding is about the whole artefact, and line 0 is
    the shape the scan already uses for "the file itself".
    """
    return (f"{ALLOWLIST_FILENAME}:0: {ALLOWLIST_REFUSED_LABEL}"
            f" ({reason})")


def allowlist_exempt(result: AllowlistResult, rel: str, label: str) -> bool:
    """True when the allowlist permits this label at this path.

    Exact match on both halves, against the ``git ls-files`` name the scan already
    holds: no normalisation, no case folding, no directory prefix. The pair is the
    unit, so a second label at the same path is not exempted by the first.
    """
    if result.status != "ok" or label == _DENYLIST_LABEL:
        return False
    return any(entry.path == rel and entry.label == label for entry in result.entries)


def exempted_pairs(result: AllowlistResult) -> frozenset[tuple[str, str]]:
    """The exempted (path, label) pairs, for a caller that asks them in bulk.

    The scan asks once before its per-line loop, so the exemption test costs one
    membership check per line rather than a scan of the entries -- a few thousand
    files times a few dozen entries is the difference between a lookup and a
    quadratic inner loop.
    """
    if result.status != "ok":
        return frozenset()
    return frozenset((entry.path, entry.label) for entry in result.entries)


def allowlist_reason(result: AllowlistResult, rel: str, label: str) -> str:
    """The reviewed one-line reason behind an exemption, for the row that reports it.

    The reason lives in the file, and the row quotes it: a reader of the report needs
    the justification beside the exemption, not a pointer to a file they then have to
    open to judge the call.
    """
    for entry in result.entries:
        if entry.path == rel and entry.label == label:
            return entry.reason
    return ""


def stale_entry_findings(result: AllowlistResult, tracked: set[str]) -> list[str]:
    """One row per entry whose path the listing does not hold: a stale exemption.

    An entry that matches nothing is a finding rather than a silence, because the
    dangerous direction is the one that stops matching: a file that was renamed or
    deleted leaves its exemption standing, and the next file that lands on that path
    inherits an exemption nobody re-reviewed. The row names the allowlist file (not
    the vanished path) so it groups with the other rows about that file, and carries
    the entry's path and label as its detail.
    """
    if result.status != "ok":
        return []
    source = result.source or ALLOWLIST_FILENAME
    rows = [f"{source}:0: {ALLOWLIST_STALE_LABEL} ({entry.path}: {entry.label})"
            for entry in result.entries
            if entry.path not in tracked]
    # Sorted here rather than left to the caller: the census sorts the whole row
    # list, but a run whose rows must be byte-identical across runs cannot depend on
    # the file's own iteration order surviving into that sort.
    return sorted(rows)

