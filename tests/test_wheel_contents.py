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

import ast
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from _harness import REPO

BUILD_TIMEOUT = 300


def build_is_installed() -> bool:
    """Whether the ``build`` module is really installed here, not merely a name.

    The wheel job builds the wheel first, which leaves a ``build/`` directory at
    the repository root, and pytest puts that rootdir on ``sys.path``. This suite
    then runs under ``.venv-wheel``, which has no ``build`` installed, and
    ``find_spec("build")`` resolves the stray directory as a namespace package:
    a spec that is not None, so a guard that trusts presence alone believes the
    module is there and runs ``python -m build`` over it, which fails with
    "'build' is a package and cannot be directly executed". A namespace directory
    carries no file of its own, so ``origin`` is what separates it from the real
    package, which always resolves to its ``__init__.py``.
    """
    spec = importlib.util.find_spec("build")
    return spec is not None and spec.origin is not None


def _skip_when_build_absent() -> None:
    """Skip this test unless the build module is genuinely installed.

    Split from the build itself so the decision can be exercised on its own: the
    wheel job's whole failure was this line believing a stray directory was the
    module, and a caller that only wants the verdict should not have to copy a
    tree to ask for it.

    This suite runs offline and the isolation mode spins up a resolver that needs
    the network, so the build runs ``--no-isolation`` against the interpreter's
    own setuptools. A build that *fails* while ``build`` is installed is a real
    defect in the packaging config, so it stays a failure that carries build's own
    stderr (see :func:`_build_wheel`) rather than a silent skip hiding it.
    """
    if not build_is_installed():
        pytest.skip("the build module is not installed in this environment")


def _build_wheel(source_root: Path, tmp_path: Path) -> Path:
    """Build the wheel from this tree and hand back its path.

    The build runs in a copy of the tree so the build's own droppings
    (``build/``, ``*.egg-info/``) never land in the working tree the suite is
    measuring.
    """
    _skip_when_build_absent()
    build_tree = tmp_path / "build-tree"
    # parents=True: the caller may hand over a fresh output directory of its own
    # (the suite's fixture does, and so does the broken-backend test below).
    # exist_ok: a caller that staged an input the copy list does not carry (the
    # license, in test_wheel_license.py) has to be able to make that tree first.
    build_tree.mkdir(parents=True, exist_ok=True)
    for name in ("src", "pyproject.toml"):
        source = source_root / name
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
    return _build_wheel(REPO, tmp_path_factory.mktemp("wheel"))


def _guard_source() -> str:
    """The text of :func:`build_is_installed`, read from this file.

    The probe runs the guard as it ships rather than a retyped copy, so the test
    cannot pass while the shipped guard stays broken.
    """
    path = REPO / "tests" / "test_wheel_contents.py"
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_is_installed":
            segment = ast.get_source_segment(text, node)
            assert segment is not None, "build_is_installed has no source to probe"
            return segment
    raise AssertionError("this file defines no build_is_installed() to probe")


def _site_packages() -> Path:
    """The directory this interpreter loads its installed packages from."""
    return Path(importlib.util.find_spec("pytest").origin).parent.parent


def _build_free_libs(tmp_path: Path) -> Path:
    """A copy of this interpreter's packages with ``build`` removed.

    The wheel job runs this suite under ``.venv-wheel``, which carries the wheel
    and pytest and no ``build``. The environment running the suite has the real
    module, so a child that is to answer as the job's interpreter would must be
    given packages to import with it taken out.
    """
    libs = tmp_path / "site"
    libs.mkdir()
    for entry in _site_packages().iterdir():
        if entry.name == "build" or entry.name.startswith("build-"):
            continue
        subprocess.run(["cp", "-r", str(entry), str(libs)], check=True,
                       timeout=BUILD_TIMEOUT)
    return libs


def _build_free_child(tmp_path: Path, decoy: Path) -> tuple[int, str, str]:
    """Run a probe in a child that cannot see the installed ``build``.

    ``-s`` is what makes the child honest: without it a venv bootstrap finder
    answers for ``build`` from the real site-packages no matter what ``sys.path``
    says, which is why editing ``sys.path`` in-process cannot model the job. The
    decoy directory goes first on the path the way pytest puts the rootdir there.
    """
    libs = _build_free_libs(tmp_path)
    code = (
        "import sys\n"
        "sys.path = [p for p in sys.path if 'site-packages' not in p]\n"
        f"sys.path.insert(0, {str(libs)!r})\n"
        f"sys.path.insert(0, {str(decoy)!r})\n"
        + tmp_path.joinpath("probe-body.py").read_text(encoding="utf-8")
    )
    proc = subprocess.run(
        [sys.executable, "-s", "-c", code],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
    )
    assert proc.returncode == 0, f"child probe failed: {proc.stderr[-2000:]}"
    return proc.returncode, proc.stdout, proc.stderr


def _write_probe(tmp_path: Path, body: str) -> None:
    """Put the probe's body where the child can read it."""
    tmp_path.joinpath("probe-body.py").write_text(body, encoding="utf-8")


def test_build_guard_skips_on_a_namespace_build_directory(tmp_path):
    """A ``build/`` directory on sys.path is not the build module.

    The regression the wheel job hit: its build step leaves a ``build/`` directory
    at the repository root, pytest puts the rootdir on ``sys.path``, and
    ``.venv-wheel`` has no ``build`` installed. The old guard asked only whether
    the name resolved, got a namespace spec, and turned all thirteen wheel tests
    into ``AssertionError`` out of ``python -m build`` instead of skipping them.

    The probe carries the guard's own text, read from this file so a change to the
    guard is a change to what the probe runs.
    """
    decoy = tmp_path / "checkout"
    decoy.mkdir()
    (decoy / "build").mkdir()
    _write_probe(tmp_path, (
        "import importlib.util\n"
        f"{_guard_source()}\n"
        "print(build_is_installed())\n"
    ))
    assert _build_free_child(tmp_path, decoy)[1].strip() == "False"


def test_build_guard_reports_installed_when_build_can_run(tmp_path):
    """The other half of the guard: a real ``build`` must not be skipped away.

    A guard that answered False for everything would keep the wheel job green by
    skipping, which is how a packaging defect hides. So the same directory shape as
    the decoy above, carrying an ``__init__.py`` and a ``__main__.py``, must read
    as installed: a package with files is what a namespace directory is not.
    """
    package = tmp_path / "checkout" / "build"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text("print('runnable')\n", encoding="utf-8")
    _write_probe(tmp_path, (
        "import importlib.util\n"
        f"{_guard_source()}\n"
        "print(build_is_installed())\n"
    ))
    assert _build_free_child(tmp_path, tmp_path / "checkout")[1].strip() == "True"


def test_build_wheel_skips_rather_than_fails_without_build(tmp_path, monkeypatch):
    """In the wheel job's environment the build skips, it does not raise.

    What the CI log argues for: with a stray ``build/`` on the path and no
    ``build`` installed, the module-scoped ``wheel`` fixture raised
    ``AssertionError`` for every wheel test rather than skipping them. The child
    above is what establishes the environment; its verdict is then handed to the
    real skip decision so the assertion lands on the line the job reached.
    """
    decoy = tmp_path / "checkout"
    decoy.mkdir()
    (decoy / "build").mkdir()
    _write_probe(tmp_path, (
        "import importlib.util\n"
        f"{_guard_source()}\n"
        "print(build_is_installed())\n"
    ))
    verdict = _build_free_child(tmp_path, decoy)[1].strip() == "False"
    assert verdict, "the child must have seen the job's environment"
    monkeypatch.setattr("test_wheel_contents.build_is_installed", lambda: False,
                        raising=False)
    with pytest.raises(pytest.skip.Exception):
        _skip_when_build_absent()


def test_build_wheel_fails_rather_than_skips_when_build_is_broken(tmp_path, monkeypatch):
    """A build that really fails must still fail, with stderr attached.

    The direction the skip must never cover: with the guard saying installed, a
    ``python -m build`` that exits non-zero has to surface as an ``AssertionError``
    carrying the tool's own output, never as a quiet skip.
    """
    if not build_is_installed():
        pytest.skip("build is not installed in this environment")
    monkeypatch.setattr("test_wheel_contents.build_is_installed", lambda: True,
                        raising=False)
    tree = tmp_path / "broken-tree"
    (tree / "src").mkdir(parents=True)
    (tree / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools\"]\n"
        "build-backend = \"no.such.backend\"\n\n"
        '[project]\nname = "noni"\nversion = "0"\n', encoding="utf-8")
    try:
        _build_wheel(tree, tmp_path / "run")
    except AssertionError as exc:
        assert "no.such.backend" in str(exc) or "Backend" in str(exc), str(exc)[:500]
    else:
        pytest.fail("a build with an unusable backend must raise, not skip")


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
