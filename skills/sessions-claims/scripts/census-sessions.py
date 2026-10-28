#!/usr/bin/env python3
"""In-place wrapper for the sessions census: runs the package module.

The product lives in the ``noni`` package (``src/noni/census_sessions.py``).
This file is the compatibility entry point the skills document (and the
``census-sessions.sh`` shim execs): it hands its argv to the package and exits
with the package's code, so the in-place form and the package print the same
bytes. It carries no logic of its own.

The package must be installed (``pip install -e ".[dev]"`` or the built wheel)
or importable on ``PYTHONPATH``; without it this wrapper names the fault and
exits non-zero rather than raising a traceback.
"""

from __future__ import annotations

import sys

try:
    from noni import census_sessions
except ImportError as exc:  # pragma: no cover - the import-failure branch
    print("census-sessions.py: the noni package is not importable "
          f"({exc}); install it or put its src/ on PYTHONPATH", file=sys.stderr)
    raise SystemExit(3) from exc

if __name__ == "__main__":
    raise SystemExit(census_sessions.main(sys.argv[1:]))
