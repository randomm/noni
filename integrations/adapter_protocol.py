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


def load_allowlist(env_var: str, default_file: str | Path | None) -> set[str]:
    """Load the allow-list of trusted accounts from local configuration.

    The allow-list is **never hard-coded**: it comes from an untracked local
    file (the same noni pattern as the scrub's deny-list — a file in
    .gitignore, or an env-var-named path), so a public repo can ship an
    adapter without shipping the operator's trusted accounts.

    Load order: the default file (when it exists) takes precedence over the
    env-var-named file; when neither exists the allow-list is empty (an empty
    allow-list authorizes no account — an adapter running without local
    configuration must not authorize anything).

    File format: one account per line; blank lines and lines starting with
    ``#`` are ignored. An unreadable or non-UTF-8 file is skipped (with the
    next candidate still consulted, and a prominent stderr notice, mirroring
    the scrub's deny-list loader), never a crash.
    """
    import os
    import sys

    candidates: list[Path] = []
    if default_file is not None:
        candidates.append(Path(default_file))
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value:
            candidates.append(Path(env_value))

    for path in candidates:
        try:
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(
                f"adapter-allowlist: WARNING — {path} unreadable ({e}); "
                f"continuing with the next candidate if any.",
                file=sys.stderr,
            )
            continue
        accounts = set()
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                accounts.add(stripped)
        return accounts

    return set()


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
        params = [p.name for p in inspect.signature(fn).parameters.values()]
        if len(params) != 2:
            problems.append(f"seam {seam} must take exactly two arguments (payload, allowlist), got {len(params)}")
    return problems
