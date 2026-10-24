"""The noni adapter interface — the contract every tracker adapter fills.

Two-tier purity (docs/PRODUCT.md §3): the core (skills/, scripts/) carries
neither project content nor vocabulary from any specific driver, tracker or
project and must stay viable with no adapter installed. Adapters live only
under ``integrations/`` and implement this interface. This module is the
documented contract for that interface: it carries no tool-specific code,
only the shapes and names the seams must present, so the core can talk
about adapters without naming any tool.

An adapter is a plain module (no package, no ``__init__.py`` — the same
``sys.path`` insertion pattern every noni script uses) exposing:

  question_legitimacy(question_payload, allowlist) -> QuestionVerdict
  label_authorization(label_payload, allowlist) -> bool

Exactly two seams. The interface is structural — there is no base class
and no import of it required from an adapter (importing this module from an
adapter would be a fine thing to do; the contract is that the two functions
exist with these shapes, and ``test_adapter_interface.py`` proves both).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# The four verdicts of the question-legitimacy seam. A steer is:
#   "none"     no answer was given (no tick); persist as status open, no answer.
#   "one"      exactly one tick, applied last by an allow-listed account.
#   "many"     several ticks — ambiguous; persist as status open, no answer.
#   "stranger" the last tick was applied by an account not on the allow-list.
# A `many` or `stranger` verdict is never stored as an answer.
VERDICT_NONE = "none"
VERDICT_ONE = "one"
VERDICT_MANY = "many"
VERDICT_STRANGER = "stranger"

#: The closed set of verdicts. An adapter verdict outside this set violates
#: the interface.
LEGAL_VERDICTS = frozenset({VERDICT_NONE, VERDICT_ONE, VERDICT_MANY, VERDICT_STRANGER})


STATUS_ABSENT = "absent"
STATUS_ACTIVE = "active"
STATUS_REFUSED = "refused"

#: The closed set of allow-list load statuses. ``absent`` — no candidate
#: file existed, so the allow-list is empty with no configuration to warn
#: about. ``active`` — a candidate was loaded (possibly to an empty set).
#: ``refused`` — a candidate was present but not trustworthy (symlink,
#: world-writable, unreadable, undecodable); the allow-list is **inactive**
#: and no further candidate is consulted.
LEGAL_STATUS = frozenset({STATUS_ABSENT, STATUS_ACTIVE, STATUS_REFUSED})


class Allowlist:
    """The result of ``load_allowlist`` — never a bare set.

    ``accounts`` is the trusted-account set (empty when the allow-list is
    inactive or loaded with no valid lines). ``status`` is one of
    LEGAL_STATUS (``active``, ``absent``, ``refused``). ``reason`` names
    the refusal when status is ``refused`` (None otherwise).

    ``authorized`` is the seam-facing accessor: **every**
    authorization/legitimacy decision funnels through it, and it is
    negative whenever the allow-list is not active — an empty set
    authorizes nothing, and a refused one cannot be downgraded back to an
    active-but-empty one by a caller passing ``set(allowlist)``.

    Account names are stored casefolded (``"OP-1"`` is stored as
    ``"op-1"``) and compared casefolded at lookup, so the
    case-insensitive match is symmetric: a lookup in any case matches an
    account stored in any case, and vice versa. Tracker logins are
    case-insensitive on GitHub, so case folding is the correct comparison.
    """

    def __init__(self, accounts: set[str], status: str, reason: str | None = None) -> None:
        if status not in LEGAL_STATUS:
            raise ValueError(f"status must be one of {sorted(LEGAL_STATUS)}, got {status!r}")
        self.accounts = {name.casefold() if isinstance(name, str) else name for name in accounts}
        self.status = status
        self.reason = reason

    @property
    def authorized(self) -> bool:
        return self.status == STATUS_ACTIVE

    def __contains__(self, name: str) -> bool:
        return self.status == STATUS_ACTIVE and name.casefold() in self.accounts

    def __bool__(self) -> bool:
        return self.status == STATUS_ACTIVE

    def __len__(self) -> int:
        return len(self.accounts) if self.status == STATUS_ACTIVE else 0

    def __repr__(self) -> str:
        return f"Allowlist(status={self.status!r}, accounts={self.accounts!r}, reason={self.reason!r})"


def is_allowed(allowlist, name: str) -> bool:
    """True iff ``name`` is an allow-listed account.

    ``allowlist`` is an :class:`Allowlist` (from ``load_allowlist``) or a
    bare set (the legacy shape the adapter seams take from callers that
    built their own). A ``None`` allow-list, a bare set built from a
    refused loader result (empty), or any non-str/empty name is **never**
    authorized. Comparison is case-insensitive and **symmetric**: account
    names are casefolded at parse time (``_parse_allowlist_lines``) and at
    lookup time, so a stored ``"OP-1"`` matches lookup ``"op-1"`` and a
    stored ``"op-1"`` matches lookup ``"OP-1"`` — tracker logins are
    case-insensitive on GitHub.
    """
    if not name or not isinstance(name, str):
        return False
    if isinstance(allowlist, Allowlist):
        return allowlist.authorized and name.casefold() in allowlist.accounts
    try:
        return name.casefold() in {a.casefold() for a in allowlist if isinstance(a, str)}
    except TypeError:
        return False


@dataclass(frozen=True)
class QuestionVerdict:
    """The result of the question-legitimacy seam.

    ``verdict`` is one of LEGAL_VERDICTS. ``answer`` is the chosen option's
    string — non-None if and only if ``verdict`` is ``one``. For ``none`` and
    ``many`` the answer is absent (None): an ambiguous steer is persisted as
    an open record, never as an answer. ``stranger`` likewise carries no
    answer (a foreign tick voids the reply).
    """

    verdict: str
    answer: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in LEGAL_VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(LEGAL_VERDICTS)}, got {self.verdict!r}")
        if self.verdict == VERDICT_ONE and self.answer is None:
            raise ValueError("verdict 'one' requires an answer")
        if self.verdict != VERDICT_ONE and self.answer is not None:
            raise ValueError(f"verdict {self.verdict!r} must carry no answer")


def _is_trustworthy_allowlist_file(path: Path) -> bool:
    """True when a candidate allow-list file is a plain, locally-owned file
    (not a symlink, not world-writable) — the trust boundary the allow-list
    is meant to enforce: a file an untrusted party can replace should not
    itself be trusted to name trusted parties.
    """
    if path.is_symlink():
        return False
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return not (mode & 0o002)


def _is_printable_token(line: str) -> bool:
    """True iff ``line`` is a single printable, whitespace-free token.

    A control or non-printable character anywhere in the line (not just the
    internal whitespace already covered by ``\t``) or **any** Unicode
    whitespace inside the name makes the line malformed: an account name
    must be a single bounded printable token, and a line that smuggles a
    hidden character must not authorize anything.
    """
    if len(line) > 200:
        return False
    for ch in line:
        if not ch.isprintable() or ch.isspace():
            return False
    return True


def _parse_allowlist_lines(raw: str) -> tuple[set[str], list[str]]:
    """Parse allow-list text into (accounts, warnings).

    One account per line; blank lines and ``#`` comments are ignored. Each
    remaining line must be a single token: printable, no internal
    whitespace, no control or non-printable characters, no path separators.
    A malformed line is reported in ``warnings`` and the account is **not**
    added (fail closed — a broken allow-list must not accidentally authorize
    a prefix of a line or the contents of an uncurated file). Account names
    are stored as-is and compared case-insensitively at lookup time (tracker
    logins are case-insensitive on GitHub).
    """
    accounts: set[str] = set()
    warnings: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _is_printable_token(stripped) or "/" in stripped:
            warnings.append(f"malformed line (skipped): {stripped!r}")
            continue
        accounts.add(stripped)
    return accounts, warnings


def load_allowlist(env_var: str, default_file: str | Path | None, warnings: list[str] | None = None) -> Allowlist:
    """Load the allow-list of trusted accounts from local configuration.

    The allow-list is **never hard-coded**: it comes from an untracked local
    file (the same noni pattern as the scrub's deny-list — a file in
    .gitignore, or an env-var-named path), so a public repo can ship an
    adapter without shipping the operator's trusted accounts. The loader is
    the safety boundary between local configuration and the two seams: a
    candidate must be a plain, non-symlink, non-world-writable file, and
    every account line must be a single bounded printable token — anything
    else is skipped, never trusted (the operator is responsible for pointing
    the configuration at a curated file).

    Returns an :class:`Allowlist` (status ``active``/``absent``/``refused``
    plus the account set and, on refusal, a ``reason`` naming the cause).

    Load order — fail closed:

    * **Default file absent** (no candidate file): fall back to the
      env-var-named file if it is present and trustworthy; if neither
      exists the allow-list is ``absent`` (no notices — "no allow-list
      configured" is not an error).
    * **Default file present but refused** (symlink, world-writable,
      unreadable, or undecodable): do **not** fall back to the env-var
      candidate. Return an ``Allowlist`` with status ``refused`` and an
      empty account set, and emit a prominent stderr notice naming the
      file and the reason. An operator who pointed the default file at a
      suspicious path must not silently get a different allow-list from the
      env var; the refusal is the signal that the configuration is broken.
    * **Default file present and trustworthy**: use it (malformed account
      lines are skipped with a warning); the env-var candidate is not
      consulted.

    File format: one account per line; blank lines and lines starting with
    ``#`` are ignored; any other malformed line is skipped with a warning
    (see ``_parse_allowlist_lines``). An active allow-list with no valid
    lines is still ``active`` (it authorizes nothing — an empty allow-list
    is not a refusal).

    ``warnings`` (optional): when a list is passed, the same notice strings
    that are printed to stderr are appended to it, so programmatic callers
    get the same signal as a human reading stderr.
    """
    warnings = [] if warnings is None else warnings

    def _warn(message: str) -> None:
        warnings.append(message)
        print(f"adapter-allowlist: WARNING — {message}", file=sys.stderr)

    def _refuse(path: Path, reason: str) -> Allowlist:
        _warn(f"{path} refused as an allow-list source ({reason}); allow-list INACTIVE — nothing is authorized")
        return Allowlist(set(), STATUS_REFUSED, f"{path} refused: {reason}")

    def _load(path: Path) -> Allowlist:
        if path.is_symlink():
            return _refuse(path, "symlink")
        try:
            mode = path.stat().st_mode
        except OSError as e:
            return _refuse(path, f"not a plain file ({e})")
        if mode & 0o002:
            return _refuse(path, "world-writable")
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return _refuse(path, f"unreadable or undecodable ({e})")
        accounts, line_warnings = _parse_allowlist_lines(raw)
        for w in line_warnings:
            _warn(f"{path}: {w}")
        return Allowlist(accounts, STATUS_ACTIVE)

    default = Path(default_file) if default_file is not None else None
    env_value = os.environ.get(env_var) if env_var else None
    env_path = Path(env_value) if env_value else None

    # The default file is the operator's primary source. When it is present
    # but refused we do not fall back to the env-var candidate: a broken
    # primary must be visible, not silently replaced by a different list.
    if default is not None and default.is_file():
        return _load(default)
    if env_path is not None and env_path.is_file():
        return _load(env_path)
    return Allowlist(set(), STATUS_ABSENT)


def check_interface(adapter_module) -> list[str]:
    """Structurally verify that ``adapter_module`` implements the interface.

    Returns a list of problems (empty = the module satisfies the contract).
    The interface is exactly two seams with fixed names and fixed shapes;
    anything else is a contract violation. This is the core-side of the
    contract — it is what ``test_adapter_interface.py`` runs, and it
    imports nothing from any specific adapter.
    """
    import inspect

    problems: list[str] = []
    for seam in ("question_legitimacy", "label_authorization"):
        fn = getattr(adapter_module, seam, None)
        if fn is None:
            problems.append(f"missing seam: {seam}")
            continue
        if not callable(fn):
            problems.append(f"seam {seam} is not callable")
            continue
        try:
            params = [p.name for p in inspect.signature(fn).parameters.values()]
        except (TypeError, ValueError) as e:
            # A C-level/built-in seam has no inspectable signature; that is a
            # contract violation to report, not an exception to propagate.
            problems.append(f"seam {seam} has no inspectable signature: {e}")
            continue
        if len(params) != 2:
            problems.append(f"seam {seam} must take exactly two arguments (payload, allowlist), got {len(params)}")
    return problems
