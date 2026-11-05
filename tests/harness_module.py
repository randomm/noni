"""Product-module loading for the test harness.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every ``from _harness import`` keeps resolving.
Importing this module is what puts ``src/`` on ``sys.path``, registers the
bare package aliases the flat-layout tests import, and hands out a fresh
copy of a package module. The two pattern tables it re-exports from
``noni.public_safety`` feed the synthetic fixtures in ``harness_faults``.
The bootstrap itself is not declared here: ``tests/_harness.py`` carries the
single ``harness_module`` import, and it runs before any helper body. A helper
module: never named ``test_*``.

"""

from __future__ import annotations

import importlib
import importlib.util
import sys

from harness_paths import SRC
from harness_sources import _product_source

# The package is the single importable home of the product modules (the
# wrappers under skills/*/scripts/ are shims, and scripts/public_safety.py is
# reached only as a subprocess for its CLI exit-code contract). Put src/ on
# sys.path here so every harness consumer gets the same noni.public_safety
# object whether or not the wheel was installed, and so the fixture builders
# below can derive from its pattern tables.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from noni.public_safety import (
    HOME_PATH_PATTERNS,  # noqa: F401  (re-exported for harness_faults)
    SECRET_PATTERNS,  # noqa: F401  (re-exported for harness_faults)
)

# Back-compatible module aliases for the tests that were written against the
# flat scripts/ layout. Those files imported the tool by its script name
# (``import census``, ``import public_safety``) after putting the script's own
# directory on sys.path; the package is the only importable home now, and a
# lookalike earlier on sys.path must not be trusted as the census's own code, so
# the aliases are registered here from the package rather than by path. They are
# the *same objects* the console route imports, which is what makes a seam a test
# installs visible to the other route as well.
for _alias, _pkg_name in (
    ("_session_git", "_session_git"),
    ("close", "close"),
    ("release", "release"),
    ("census", "census"),
    ("census_hygiene", "census_hygiene"),
    ("census_hygiene_rows", "census_hygiene_rows"),
    ("census_json", "census_json"),
    ("census_ledger", "census_ledger"),
    ("census_ordering", "census_ordering"),
    ("census_ordering_readers", "census_ordering_readers"),
    ("census_sessions", "census_sessions"),
    ("census_sessions_probe", "census_sessions_probe"),
    ("census_text", "census_text"),
    ("claim", "claim"),
    ("decide", "decide"),
    ("gitenv", "gitenv"),
    ("gitwrite", "gitwrite"),
    ("order", "order"),
    ("order_gitwrite", "order_gitwrite"),
    ("orderschema", "orderschema"),
    ("orderstate", "orderstate"),
    ("public_safety", "public_safety"),
    ("register", "register"),
    ("targetschema", "targetschema"),
):
    _module = importlib.import_module(f"noni.{_pkg_name}")
    sys.modules.setdefault(_alias, _module)
del _alias, _pkg_name, _module


def load_package_module(name: str) -> object:
    """A fresh copy of a package module, under a test-private name.

    For the tests that mutate a module's globals (a seam on a constant, a
    replaced helper) and must not leak the change into the module the next test
    imports. The package's own copy is left untouched, and the copy is exec'd
    from the same source rather than shallow-copied: a module whose globals are a
    borrowed dict would make a seam on one module visible through the other.
    """
    module = importlib.import_module(f"noni.{name}")
    # Importing first is the point: it proves the module exists in the package
    # before a copy of its file is exec'd, so a name that is not a package
    # module fails here rather than as a confusing file-not-found below.
    del module
    source = _product_source(SRC / "noni" / f"{name}.py")
    private = f"noni_under_test_{name}"
    sys.modules.pop(private, None)
    spec = importlib.util.spec_from_file_location(private, source)
    if spec is None or spec.loader is None:  # pragma: no cover - path is fixed
        raise RuntimeError(f"cannot load a fresh copy of the package module {name}")
    fresh = importlib.util.module_from_spec(spec)
    sys.modules[private] = fresh
    spec.loader.exec_module(fresh)
    return fresh


def _claim_module() -> object:
    """The claim module, for the tests that drive its internals.

    Defined here, next to the wrapper path the subprocess tests launch. It is
    the package module, imported under its real name, so a seam a test puts on
    it is visible to the console route too. ``claim_fixtures``
    re-exports it so the name resolves inside those files' globals.
    """
    from noni import claim

    return claim


def _decide_module() -> object:
    """The decide module, for the tests that name its constants.

    The exit-5 tests need the writer's own failure-seam constant rather than a
    copy of its name: a rename in the product then fails the test that drives
    it instead of leaving that test exercising a real commit. The package module
    under its real name, so the constants are the ones the shipped code reads.
    """
    from noni import decide

    return decide
