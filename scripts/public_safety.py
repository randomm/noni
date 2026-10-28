#!/usr/bin/env python3
"""The repository script form of the public-repo hygiene scrub.

The product lives in the ``noni`` package as ``noni.public_safety``, which is
what the census's hygiene class imports in-process. This file is the gate
AGENTS.md names: the CLI contract stays here, with the honest exit codes the
publishing checklist depends on — exit 1 on a violation, exit 2 when the
deny-list class was not active, exit 0 (with a ``clean`` line) only when both
halves ran.

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
    raise SystemExit(2) from exc


def main() -> int:
    found, _source, denylist = public_safety.scrub_tracked_files(REPO)
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
