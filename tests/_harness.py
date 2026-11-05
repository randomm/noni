"""Shared git / script helpers for the steering-ledger test harness.

Held in its own module (not ``conftest.py``) so that ``scenario_eval.py`` —
which is both a test module and a standalone build tool
(``python tests/scenario_eval.py <path>``) — can import these helpers
without pulling in ``conftest.py`` and its module-level ``import pytest``.

The bodies live in the ``harness_*`` helper modules (issue #52, the file-size
ratchet) and are re-exported here, so ``_harness`` stays the one import
surface the test modules use. The bootstrap is the first import below:
``harness_module`` inserts this tree's ``src/`` at the head of ``sys.path``
and registers the bare package aliases (``census``, ``public_safety``, ...) in
``sys.modules``, both as import side effects. It runs on its own line, ahead
of every helper that imports a product name, so no helper can reach a product
import before that bootstrap has run. It is bound to a private name: the
bootstrap is a side effect, not part of the surface this facade exports, and
the helpers import the bootstrap module themselves through their own imports,
so none of them re-imports it.
"""

from __future__ import annotations

import harness_module as _bootstrap  # noqa: F401  # bootstrap side effects only: src/ on sys.path + bare package aliases, before any product import
from harness_faults import (
    _HOME_PATH_KNOWN_IDENTITY,
    _SECRET_TOKEN_PREFIX,
    _fault_the_ledger_listing,
    _fault_the_sessions_listing,
    _home_path_violation,
    _permission_fault_guard,
    _permission_fault_on,
    _plant_fifo,
    _plant_fifo_link,
    _plant_non_regular,
    _plant_untracked_fifo,
    _secret_violation,
)
from harness_git import (
    PushProtocolDrift,
    _commit_file,
    _git,
    _git_e2,
    _git_env_with_identity,
    _git_ok,
    _git_porcelain,
    _git_porcelain_git_dir,
    _git_show,
    _init_repo,
    _tree_bytes,
    advance_origin_with_claim,
    assert_writers_clear_git_env,
    build_bare_origin,
    build_gone_upstream,
    decoy_git_index,
    decoy_git_repo,
    git_pin_date,
    push_with_retry,
)
from harness_module import (
    HOME_PATH_PATTERNS,
    SECRET_PATTERNS,
    _claim_module,
    _decide_module,
    load_package_module,
)
from harness_paths import (
    CENSUS,
    CENSUS_SESSIONS,
    CENSUS_SESSIONS_PY,
    CENSUS_SH,
    CENSUS_SKILL,
    CLAIM,
    CLOSE,
    COVERAGE_PROCESS_START,
    DECIDE,
    DIRECTION_SKILL,
    HELP_COLUMNS,
    INTENT,
    ORDER,
    PRODUCT_MODULES,
    REGISTER,
    RELEASE,
    REPO,
    SESSIONS_SKILL,
    SRC,
    STEERING_SKILL,
    TOOL_WRAPPERS,
)
from harness_runners import (
    _cwd_kwarg,
    _order_module,
    _run_session_writer,
    run_claim,
    run_close,
    run_decide,
    run_from,
    run_noni,
    run_order,
    run_register,
    run_release,
    run_wrapper,
    subprocess_env,
)
from harness_sources import _harness_source, _product_source, _script_ast, _script_constant

# Exactly the top-level names the pre-split ``_harness.py`` defined: the facade
# re-exports the helpers, it does not widen the surface tests may reach for.
__all__ = [
    "CENSUS",
    "CENSUS_SESSIONS",
    "CENSUS_SESSIONS_PY",
    "CENSUS_SH",
    "CENSUS_SKILL",
    "CLAIM",
    "CLOSE",
    "COVERAGE_PROCESS_START",
    "DECIDE",
    "DIRECTION_SKILL",
    "HELP_COLUMNS",
    "HOME_PATH_PATTERNS",
    "INTENT",
    "ORDER",
    "PRODUCT_MODULES",
    "PushProtocolDrift",
    "REGISTER",
    "RELEASE",
    "REPO",
    "SECRET_PATTERNS",
    "SESSIONS_SKILL",
    "SRC",
    "STEERING_SKILL",
    "TOOL_WRAPPERS",
    "_HOME_PATH_KNOWN_IDENTITY",
    "_SECRET_TOKEN_PREFIX",
    "_claim_module",
    "_commit_file",
    "_cwd_kwarg",
    "_decide_module",
    "_fault_the_ledger_listing",
    "_fault_the_sessions_listing",
    "_git",
    "_git_e2",
    "_git_env_with_identity",
    "_git_ok",
    "_git_porcelain",
    "_git_porcelain_git_dir",
    "_git_show",
    "_harness_source",
    "_home_path_violation",
    "_init_repo",
    "_order_module",
    "_permission_fault_guard",
    "_permission_fault_on",
    "_plant_fifo",
    "_plant_fifo_link",
    "_plant_non_regular",
    "_plant_untracked_fifo",
    "_product_source",
    "_run_session_writer",
    "_script_ast",
    "_script_constant",
    "_secret_violation",
    "_tree_bytes",
    "advance_origin_with_claim",
    "assert_writers_clear_git_env",
    "build_bare_origin",
    "build_gone_upstream",
    "decoy_git_index",
    "decoy_git_repo",
    "git_pin_date",
    "load_package_module",
    "push_with_retry",
    "run_claim",
    "run_close",
    "run_decide",
    "run_from",
    "run_noni",
    "run_order",
    "run_register",
    "run_release",
    "run_wrapper",
    "subprocess_env",
]
