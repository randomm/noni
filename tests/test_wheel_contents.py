"""The wheel ships the package and nothing else.

The distribution is one thing: ``noni/`` plus its metadata. Everything else in
the repository is either the test suite, the skills' documentation and wrappers,
the adapters, or this repository's own direction state under ``noni/`` — none of
which belongs in a wheel a team installs.

The assertion is written as a whitelist over the entry names rather than a
list of forbidden prefixes, because the failure that matters is the silent one:
a build config that starts shipping ``tests/`` or the repo's ``noni/decisions/``
records (which are this repository's own data, and the one thing the public-repo
rule is most particular about) would otherwise reach a reader's machine.

The wheel is built here rather than reused: the test must measure the artifact
the same tree produces, so a stale ``dist/`` cannot make this pass.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from _harness import REPO

BUILD_TIMEOUT = 300


def _build_wheel(tmp_path: Path) -> Path:
    """Build the wheel from this tree and hand back its path.

    Skipped only when the build module is not importable at all: this suite runs
    offline and the isolation mode spins up a resolver that needs the network,
    so the build runs ``--no-isolation`` against the interpreter's own
    setuptools. A build that *fails* while ``build`` is installed is a real
    defect in the packaging config, so it is a failure that carries build's own
    stderr rather than a silent skip that would hide it. The build runs in a
    copy of the tree so the build's own droppings (``build/``,
    ``*.egg-info/``) never land in the working tree the suite is measuring.
    """
    if importlib.util.find_spec("build") is None:
        pytest.skip("the build module is not installed in this environment")
    build_tree = tmp_path / "build-tree"
    build_tree.mkdir()
    for name in ("src", "pyproject.toml"):
        source = REPO / name
        target = build_tree / name
        if source.is_dir():
            subprocess.run(["cp", "-r", str(source), str(target.parent)], check=True,
                           timeout=BUILD_TIMEOUT)
        else:
            target.write_bytes(source.read_bytes())
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(tmp_path / "dist"), str(build_tree)],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"python -m build failed although the module is installed "
            f"(exit {proc.returncode}):\n{proc.stderr[-4000:]}"
        )
    wheels = sorted((tmp_path / "dist").glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {[w.name for w in wheels]}"
    return wheels[0]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    return _build_wheel(tmp_path_factory.mktemp("wheel"))


def _entries(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return sorted(archive.namelist())


def test_wheel_ships_only_the_package_and_metadata(wheel: Path):
    """Every entry is under ``noni/`` or under the one dist-info / data dir."""
    entries = _entries(wheel)
    assert entries, "the wheel is empty"
    metadata_dirs = [name.split("/")[0] for name in entries
                     if name.endswith("/") or (name.split("/")[0].endswith((".dist-info", ".data")))]
    top_levels = {name.split("/")[0] for name in entries}
    allowed_extra = {name for name in top_levels
                     if name.endswith((".dist-info", ".data"))}
    assert len(allowed_extra) <= 2, (
        f"the wheel carries more than the package and its metadata: {sorted(top_levels)}"
    )
    for name in entries:
        head = name.split("/")[0]
        assert head == "noni" or head.endswith((".dist-info", ".data")), (
            f"wheel entry outside the package: {name}"
        )
    assert metadata_dirs


@pytest.mark.parametrize("forbidden", [
    "tests/", "skills/", "integrations/", "scripts/", "noni/decisions",
    "noni/sessions", "noni/direction", "docs/", ".github/",
])
def test_wheel_carries_no_repository_only_content(wheel: Path, forbidden: str):
    """The directories that are repo content, never product content, stay out."""
    leaked = [name for name in _entries(wheel) if name.startswith(forbidden)]
    assert not leaked, f"the wheel ships {forbidden!r}: {leaked}"


def test_wheel_has_no_top_level_config_or_docs(wheel: Path):
    """No pyproject, README or AGENTS file sits at the wheel's top level.

    A stray top-level file is not merely untidy: it is a sign the build ran over
    the repository root rather than over ``src/``.
    """
    top_level_files = [name for name in _entries(wheel)
                       if "/" not in name and not name.endswith("/")]
    allowed = {name for name in top_level_files if name.endswith((".dist-info", ".data"))}
    assert not [name for name in top_level_files if name not in allowed], (
        f"unexpected top-level wheel entries: {top_level_files}"
    )
    for name in _entries(wheel):
        assert Path(name).name not in {"pyproject.toml", "AGENTS.md", "CONTRIBUTING.md"}, name


def test_wheel_ships_every_package_module(wheel: Path):
    """The wheel is complete: every module of the package is in it.

    The other direction from the exclusions above. A module missing from the
    wheel is an installed ``noni`` that raises ImportError on one command, which
    is exactly what the reader's one-install try-it depends on.
    """
    entries = set(_entries(wheel))
    shipped = {p.name for p in (REPO / "src" / "noni").glob("*.py")}
    assert shipped, "no package modules found under src/noni/"
    missing = [name for name in sorted(shipped) if f"noni/{name}" not in entries]
    assert not missing, f"the wheel omits package modules: {missing}"


def test_wheel_declares_the_noni_console_command(wheel: Path):
    """The installed distribution provides ``noni``.

    This is the acceptance criterion's first clause stated against the artifact:
    the entry point must be declared in the wheel's metadata, not merely in
    pyproject.toml.
    """
    entries = _entries(wheel)
    scripts = [name for name in entries if name.endswith("/entry_points.txt")]
    assert scripts, f"the wheel carries no entry_points.txt: {entries}"
    with zipfile.ZipFile(wheel) as archive:
        body = archive.read(scripts[0]).decode("utf-8")
    assert "noni" in body and "noni.cli:main" in body, body
