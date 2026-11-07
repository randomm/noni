#!/usr/bin/env python3
"""In-place wrapper for item.py: runs the package module.

The product lives in the ``noni`` package (``src/noni/item.py``). This file is the
compatibility entry point the docs and the tests use: it hands its argv to the package
and exits with the package's code, so the in-place form and ``noni item`` print the
same bytes. It carries no logic of its own.

The item writer has no skill directory yet (the items skill is its own ticket), so
this is the one wrapper that lives under ``scripts/`` rather than beside a skill.

The package must be installed (docs/QUICKSTART.md, *Install noni*) or importable on
``PYTHONPATH``; without it this wrapper names the fault and exits non-zero rather than
raising a traceback.
"""

from __future__ import annotations

import sys

try:
    from noni import item
except ImportError as exc:  # pragma: no cover - the import-failure branch
    print(f"item.py: the noni package is not importable ({exc}); "
          "install it or put its src/ on PYTHONPATH", file=sys.stderr)
    raise SystemExit(3) from exc

if __name__ == "__main__":
    raise SystemExit(item.main(sys.argv[1:]))
