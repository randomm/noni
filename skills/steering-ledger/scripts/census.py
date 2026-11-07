#!/usr/bin/env python3
"""In-place wrapper for the ledger census: runs the package's ledger entry point.

The product lives in the ``noni`` package (``src/noni/census_wrapper.py``). This
file is the compatibility entry point the steering-ledger skill documents, and
the ``census.sh`` shim execs it: it hands its argv to the package and exits with
the package's code, so the two forms print the same bytes. It carries no logic
of its own.

The package must be installed (docs/QUICKSTART.md, *Install noni*) or importable
on ``PYTHONPATH``; without it this wrapper names the fault and exits non-zero
rather than raising a traceback.
"""

from __future__ import annotations

import sys

try:
    from noni import census_wrapper
except ImportError as exc:  # pragma: no cover - the import-failure branch
    print("census.sh: the noni package is not importable "
          f"({exc}); install it or put its src/ on PYTHONPATH", file=sys.stderr)
    raise SystemExit(3) from exc

if __name__ == "__main__":
    raise SystemExit(census_wrapper.run_ledger(sys.argv[1:]))
