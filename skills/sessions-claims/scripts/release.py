#!/usr/bin/env python3
"""In-place wrapper for release.py: runs the package module.

The product lives in the ``noni`` package (``src/noni/release.py``). This file
is the compatibility entry point the skills document: it hands its argv to the
package and exits with the package's code, so the in-place form and
``noni release`` print the same bytes. It carries no logic of its own.

The package must be installed (``pip install -e ".[dev]"`` or the built wheel)
or importable on ``PYTHONPATH``; without it this wrapper names the fault and
exits non-zero rather than raising a traceback.
"""

from __future__ import annotations

import sys

try:
    from noni import release
except ImportError as exc:  # pragma: no cover - the import-failure branch
    print(f"release.py: the noni package is not importable ({exc}); "
          "install it or put its src/ on PYTHONPATH", file=sys.stderr)
    raise SystemExit(3) from exc

if __name__ == "__main__":
    raise SystemExit(release.main(sys.argv[1:]))
