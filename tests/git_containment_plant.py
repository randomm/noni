"""The shared plant the containment suites measure a refused git call against.

Both modules that hold an issue #220 test need the same three things: a real
repository under ``tmp_path`` whose config is the witness, a plain directory inside
it (the state that leaked), and a way to read back which identity a config holds.
This module owns those, so the two suites cannot disagree about what "the leak did
not happen" means -- a witness one of them built differently would let a leak through
one side and stay green on the other.

A helper module: never named ``test_*``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# How git spells a key it wrote into a config file: its own sectioned form, which is
# what a leak puts there (``git config user.name Replay`` writes a ``[user]`` section
# holding ``name = Replay``, never the flat ``user.name =`` a caller typed). Both
# spacings are named because git's output depends on the key it was given and the
# file's existing shape, and an assertion that matched only one could pass on a leak
# it simply failed to recognise.
LEAK_IDENTITY_ROWS = (b"name = Replay", b"name=Replay",
                      b"email = replay@fixture.invalid",
                      b"email=replay@fixture.invalid")

# The identity the plant's own config carries, and the value a nested write plants.
# Both are asserted on: the parent's must survive a nested clone's config write, and
# the nested one's must not appear in it.
WITNESS_IDENTITY = b"name = Witness"
NESTED_IDENTITY = b"name = Nested"


def plant_enclosing_repo(root: Path) -> Path:
    """A real repository under ``root``, with its config taken as the witness.

    Deliberately *not* built by the harness helpers: the witness for a guard has to
    exist before the guard runs, and a repository built through ``_init_repo`` would
    be refused (or, before the fix, would be the leak itself). Its identity is not the
    fixture's, so a config that gained the fixture's is unambiguously a leak rather
    than a re-assertion of something already there.
    """
    enclosing = root / "enclosing"
    enclosing.mkdir(parents=True)
    for argv in (["init", "-q", "-b", "main"],
                 ["config", "user.name", "Witness"],
                 ["config", "user.email", "witness@example.invalid"]):
        proc = subprocess.run(["git", "-C", str(enclosing), *argv],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"git {argv}: {proc.stderr}"
    assert (enclosing / ".git" / "config").is_file(), (
        "the plant has no config of its own, so it cannot witness a write")
    return enclosing


def plain_subdirectory(under: Path) -> Path:
    """A directory with no ``.git`` anywhere in it, inside ``under``.

    The name carries no git meaning and nothing in it is git state: this is the state
    that leaked, a scratch directory that happened to sit inside a repository.
    """
    plain = under / "scratch" / "issue-220"
    plain.mkdir(parents=True)
    assert not any(p.name == ".git" for p in plain.rglob("*")), (
        f"the plant's 'plain' directory holds git state, so refusing a call on it "
        f"would prove nothing about the guard: {sorted(plain.rglob('*'))}")
    return plain


def identity_lines(config: Path) -> list[bytes]:
    """The config's identity rows, stripped of the whitespace git pads them with.

    Stripping (rather than matching one fixed ``name = X``) is what lets the same
    helper read git's tab-indented sectioned form and a caller's unindented one. The
    list keeps each row separate, so an assertion can say *which* identity a config
    holds instead of only that it holds something.
    """
    return [line.strip() for line in config.read_bytes().splitlines()
            if b"user." in line or b"name =" in line or b"email =" in line]


def assert_no_identity_written(config: Path) -> None:
    """The witness's claim: the fixture identity is nowhere in this config.

    Asserted on rows rather than "the bytes are unchanged" where a test has already
    pinned the bytes, so the two assertions answer different questions -- one about
    the leak's content, one about any write at all.
    """
    body = config.read_bytes()
    for row in LEAK_IDENTITY_ROWS:
        assert row not in body, (
            f"the fixture identity reached the enclosing repository's config: "
            f"{config}\n{body.decode('utf-8', 'replace')}")
