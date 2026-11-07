#!/usr/bin/env python3
"""The repository script form of the public-repo hygiene scrub.

The product lives in the ``noni`` package as ``noni.public_safety``, which is
what the census's hygiene class imports in-process. This file is the gate
AGENTS.md names: the CLI contract stays here, with the honest exit codes the
publishing checklist depends on: exit 0 (with a ``clean`` line) only when both
halves ran, exit 1 on a violation, exit 2 when the deny-list class was not
active, and exit 3 when the gate could not run at all — the package it imports
was not importable, so no file was scanned, or the tree's committed allowlist
could not be read or refused to parse, so the scan did not know its exemptions.
The last two must never share a number with exit 2: the CI step tolerates exit 2
(a public runner has no deny-list), and a gate that never ran is not the same
verdict as a gate that ran and found nothing to refuse. Exit 3 therefore covers
every state in which the scan did not answer, and the CI step's code table keeps
rejecting it however many causes share it.

The tree to audit is this repository: it is named from this script's own
location, never from the package's, because the package may be installed from a
wheel anywhere on the machine.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    from noni import public_safety
except ImportError as exc:  # pragma: no cover - the import-failure branch
    print(f"public-safety: the noni package is not importable ({exc}); "
          'install it or put its src/ on PYTHONPATH', file=sys.stderr)
    # Exit 3, not 2: 2 is the state a public CI runner passes on, and an
    # unimportable package means the scan never happened. Exercised by
    # tests/test_public_safety.py, which runs this script as a child under
    # ``-S -I`` so no install can satisfy the import; the branch is therefore
    # never taken in-process and stays excluded from the coverage report.
    raise SystemExit(3) from exc


def main() -> int:
    found, _source, denylist, allowlist = public_safety.scrub_tracked_files(REPO)
    if getattr(allowlist, "status", "absent") in ("malformed", "unreadable"):
        # Exit 3, not 1 and not 2: the findings below are the allowlist's own rows, and
        # reporting them as violations would say the scan ran and disapproved, when in
        # fact it never learned its exemptions. 3 is the code CI refuses, which is the
        # only answer that keeps an unreadable allowlist from reading as clean.
        state = getattr(allowlist, "status", "unusable")
        for violation in found:
            print(violation, file=sys.stderr)
        print(f"public-safety: NOT clean — {public_safety.GATE_COULD_NOT_RUN_WORD}: "
              f"the committed allowlist is {state}", file=sys.stderr)
        return 3
    if found:
        for v in found:
            print(v, file=sys.stderr)
        return 1
    if not public_safety._denylist_active(denylist):
        # Refuse to report clean when the deny-list class was not active:
        # skipped (absent), corrupt, or present but empty.
        state = denylist.status if denylist.status != "ok" else "present but empty"
        print(f"public-safety: NOT clean — deny-list class inactive ({state})", file=sys.stderr)
        return 2
    print("public-safety: clean", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
