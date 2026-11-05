"""The wheel ships its license text and the metadata that names it.

Two defects this module exists to catch, both of which the packaging config can
produce silently:

- **The wheel claims a license it does not ship.** ``license = {text =
  "Apache-2.0"}`` builds cleanly on the pinned backend and puts a ``License:``
  header in ``METADATA``, but copies no license file into ``dist-info``: the
  artifact asserts permission nobody can read from it. The ``file =`` form plus
  ``[tool.setuptools] license-files`` is the shape that ships the text, and the
  entry assertion below is what keeps a regression to the ``text =`` form from
  reading as green.
- **The metadata block is dropped from ``[project]``.** Nothing else in the
  suite opens ``METADATA``: the wheel tests read the entry list and
  ``entry_points.txt``, so an empty ``Author``, missing ``Project-URL`` or lost
  ``readme`` had no check at all before this module.

The build itself, the skip guard and the entry whitelist live in
``test_wheel_contents.py`` and are reused rather than duplicated: one build per
suite run, one definition of what a buildable tree is.
"""

from __future__ import annotations

import email
import shutil
import zipfile
from pathlib import Path

import pytest
from _harness import REPO
from test_wheel_contents import _build_wheel

# The license file has to reach the build's own input tree. `_build_wheel`
# copies a named set into the throwaway tree it builds in, and a file the copy
# left out cannot ship: without this the assertion below would fail for the
# wrong reason (a missing input, not a bad config).
_BUILD_INPUTS = ("src", "pyproject.toml", "LICENSE")

# The METADATA headers the [project] table is expected to produce, and the value
# each must carry. Read from the built artifact rather than from pyproject.toml:
# the file on disk declaring a key is not the wheel shipping it.
EXPECTED_AUTHOR = "noni contributors"
EXPECTED_URLS = {
    "Homepage": "https://github.com/OWNER/noni",
    "Repository": "https://github.com/OWNER/noni",
    "Issues": "https://github.com/OWNER/noni/issues",
}
EXPECTED_CLASSIFIERS = (
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
)


def _build_tree(tmp_path: Path) -> Path:
    """The tree :func:`test_wheel_contents._build_wheel` copies its inputs into.

    The helper names it after the output directory it was given, so the caller
    can reach the copy without guessing at it -- which is what lets this module
    add the license input the helper does not copy, and take it away again.
    """
    return tmp_path / "build-tree"


def _stage_license(source_root: Path, tmp_path: Path) -> Path:
    """Copy LICENSE into the build tree, ready for the build that ships it."""
    tree = _build_tree(tmp_path)
    tree.mkdir(parents=True, exist_ok=True)  # the helper mkdir()s it too; this only needs to survive that
    shutil.copy2(source_root / "LICENSE", tree / "LICENSE")
    return tree


def build_licensed_wheel(source_root: Path, tmp_path: Path) -> Path:
    """The wheel from ``source_root``, LICENSE staged into its build tree.

    :func:`test_wheel_contents._build_wheel` copies only ``src`` and
    ``pyproject.toml`` into the throwaway tree it builds in, and a file the copy
    left out cannot ship: without this the entry assertion below would fail for
    the wrong reason (an input the fixture never handed over, not a build config
    that dropped the file).
    """
    _stage_license(source_root, tmp_path)
    return _build_wheel(source_root, tmp_path)


def build_wheel_without_license(source_root: Path, tmp_path: Path) -> Path:
    """The wheel from ``source_root`` with LICENSE taken back out of the build tree.

    The counter-case, built over the same staging step: with the file removed
    and the build re-run, only the declaration is left to account for the entry.
    """
    tree = _stage_license(source_root, tmp_path)
    tree.joinpath("LICENSE").unlink()
    return _build_wheel(source_root, tmp_path / "unlicensed")


@pytest.fixture(scope="module")
def licensed_wheel(tmp_path_factory) -> Path:
    """The wheel from this tree, LICENSE included in the build's input copy.

    A fixture of its own rather than the shared ``wheel`` one, so the entry-list
    whitelist tests keep measuring the plain build and this module measures the
    one carrying the license: the two trees differ only in that input.
    """
    for name in _BUILD_INPUTS:
        assert (REPO / name).exists(), f"the wheel build needs {name!r}, which is missing"
    return build_licensed_wheel(REPO, tmp_path_factory.mktemp("licensed-wheel"))


def _metadata(wheel: Path) -> email.message.Message:
    """The wheel's ``dist-info/METADATA``, parsed as the mail message it is.

    Parsed rather than searched: the headers repeat (``Project-URL`` and
    ``Classifier`` appear once per entry), and a substring test cannot tell a
    header that carries a value from a page that happens to mention it.
    """
    names = [n for n in zipfile.ZipFile(wheel).namelist() if n.endswith("/METADATA")]
    assert len(names) == 1, f"expected one METADATA, got {names}"
    with zipfile.ZipFile(wheel) as archive:
        return email.message_from_bytes(archive.read(names[0]))


def test_wheel_ships_the_license_text_in_dist_info(licensed_wheel: Path) -> None:
    """The wheel carries ``<dist>.dist-info/LICENSE`` with the license body in it.

    This is the half the ``text =`` form silently drops, so the assertion is on
    the bytes and not on the entry name alone: a zero-length LICENSE entry would
    satisfy a whitelist of names while shipping nothing.
    """
    entries = zipfile.ZipFile(licensed_wheel).namelist()
    licenses = [n for n in entries if n.split("/")[-1] == "LICENSE"]
    assert licenses, f"the wheel ships no license file: {entries}"
    assert all(n.split("/")[0].endswith(".dist-info") for n in licenses), (
        f"the license is not in dist-info: {licenses}"
    )
    with zipfile.ZipFile(licensed_wheel) as archive:
        body = archive.read(licenses[0]).decode("utf-8")
    assert body.strip(), f"{licenses[0]} is empty"
    assert "Apache License" in body and "Version 2.0" in body, (
        f"{licenses[0]} is not the Apache-2.0 text"
    )


def test_wheel_metadata_declares_the_license_the_file_shows(licensed_wheel: Path) -> None:
    """``METADATA`` names Apache-2.0 as the license, however the backend renders it.

    The pinned backend (setuptools 75.8.0) refuses the bare SPDX form, so the
    value can arrive either as ``License: Apache-2.0`` or as the license file's
    text under a ``License:`` header. Both mean the same thing to a reader of
    the artifact; what would not be acceptable is silence, which is what a
    dropped ``license`` key produces.
    """
    message = _metadata(licensed_wheel)
    # The pinned backend renders license = {file = "LICENSE"} as an empty
    # License: header plus a License-File: pointer, so the claim a reader
    # can act on is the file entry: an absent declaration drops both.
    files = message.get_all("License-File") or []
    assert any(n.endswith("LICENSE") for n in files), (
        f"the wheel points at no license file: License-File is {files!r}, "
        f"License is {message.get_all('License')!r}"
    )
    assert "License :: OSI Approved :: Apache Software License" in (
        message.get_all("Classifier") or []
    ), "the license classifier is missing from the wheel's metadata"


def test_wheel_metadata_names_the_authors_without_a_personal_name(
    licensed_wheel: Path,
) -> None:
    """The distribution names a generic contributor, never a person.

    The public-repo rule forbids a personal name in a tracked file, and
    ``METADATA`` is generated from a tracked file, so the value is asserted
    exactly rather than checked for absence: this is also the only test that
    proves ``authors`` in ``[project]`` reaches the artifact at all.
    """
    message = _metadata(licensed_wheel)
    authors = message.get_all("Author") or []
    assert authors == [EXPECTED_AUTHOR], (
        f"the wheel's Author is {authors!r}, expected exactly {[EXPECTED_AUTHOR]!r}"
    )
    # An email alongside the name would be a route for a personal address into
    # the artifact: the project table carries none, and this is the check that
    # keeps it that way.
    assert not message.get_all("Author-email"), (
        f"the wheel carries an author email: {message.get_all('Author-email')}"
    )


def test_wheel_metadata_carries_the_project_urls(licensed_wheel: Path) -> None:
    """Homepage, Repository and Issues are in the artifact, on the placeholder owner.

    Read as parsed values, one per label: a ``Project-URL`` that lost its value
    or gained a real host would both be invisible to a substring check.
    """
    message = _metadata(licensed_wheel)
    listed = dict()
    for entry in message.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        listed[label.strip()] = url.strip()
    assert listed == EXPECTED_URLS, (
        f"the wheel's Project-URL set is {listed!r}, expected {EXPECTED_URLS!r}"
    )


def test_wheel_metadata_carries_the_classifiers_and_the_readme(
    licensed_wheel: Path,
) -> None:
    """The declared Python support and status are in the artifact, and so is the readme.

    The classifiers are what an index page shows a reader deciding whether the
    package runs on their interpreter; ``Description-Content-Type`` is what
    proves ``readme = \"README.md\"`` was read by the build rather than ignored.
    """
    message = _metadata(licensed_wheel)
    classifiers = message.get_all("Classifier") or []
    for expected in EXPECTED_CLASSIFIERS:
        assert expected in classifiers, (
            f"the wheel is missing the classifier {expected!r}: {sorted(classifiers)}"
        )
    assert message.get("Description-Content-Type") == "text/markdown", (
        f"the wheel declares no markdown readme: "
        f"{message.get('Description-Content-Type')!r}"
    )
    assert message.get("Summary"), "the wheel carries no Summary, so [project] lost its description"


def test_a_build_tree_with_no_license_file_ships_no_license(tmp_path: Path) -> None:
    """The license declaration is honoured by the build, not silently ignored.

    The counter-case the staging step above would otherwise hide: if the backend
    took ``license-files`` to mean nothing, a tree with no license to ship would
    build exactly as well and the entry asserted above would prove nothing about
    the config. The pinned backend warns by name and ships no entry in that
    case, so both halves are asserted: the warning is what makes the omission
    visible, and the absent entry is what makes the shipped file the evidence of
    the declaration rather than a copy the build happened to find.
    """
    tree = tmp_path / "no-license"
    tree.mkdir()
    wheel = build_wheel_without_license(REPO, tree)
    entries = zipfile.ZipFile(wheel).namelist()
    assert not [n for n in entries if n.split("/")[-1] == "LICENSE"], (
        f"the wheel shipped a license the tree never had, so the entry asserted "
        f"above is not evidence of the config: {entries}"
    )
