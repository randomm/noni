"""The try-it block's commands, read out of the page and validated as they go.

Split out of ``readme_support`` because the extraction owns the page's
allow-lists: which programs a page may tell a reader to run, which ``git
config`` keys it may set, and which attached-state paths it may name without
one of them being a broken promise. Those rules are data plus a walk over the
block's argv, and the assertions that apply them live with the extraction, not
with the parsing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from readme_support import (
    _ALLOWED_GIT_CONFIG_KEYS,
    _ALLOWED_SHELL,
    _CLONE_URL_PLACEHOLDER,
    _READER_DIR_PLACEHOLDER,
    _STATE_DOCS,
    _VENV_PATTERNS,
    NONI_DIR,
    REPO,
    _block_commands,
    _block_words,
    _try_it_block,
)


class StateClaim(NamedTuple):
    """An attached-state exemption: which pattern matched, and the file that
    claims the path. A named pair, so the two halves cannot be swapped."""

    pattern: str
    doc: Path

    @property
    def is_venv(self) -> bool:
        """True when this exemption is the venv-tool kind, not a noni path."""
        return self.pattern in _VENV_PATTERNS


def _state_token_claim(token: str) -> StateClaim | None:
    """The claiming record when ``token`` names attached state, else None.

    The claiming file is the one the table names, and it must carry the token's
    own basename, so a token cannot be excused by a table nobody maintains.
    """
    for pattern, doc in _STATE_DOCS.items():
        if re.fullmatch(pattern, token):
            return StateClaim(pattern, doc)
    return None


def _claim_is_documented(token: str, claim: StateClaim) -> bool:
    """True when the claiming file makes the same claim about ``token``.

    Both branches prove the same kind of thing: that the token's own basename
    appears in the file that owns it. The claim is checked where it is made: the
    directory or file noni tells a reader it will create has to appear in the
    skill that creates it, and a venv tool has to appear in the gate
    configuration that installs it (CI's own install step runs ``.venv/bin/pip``,
    which is the other route to it). Checking the basename on the venv branch
    too is what stops a fabricated ``.venv/bin/whatever`` passing on a word that
    has nothing to do with it.
    """
    doc = REPO / claim.doc
    if not doc.is_file():
        return False
    body = doc.read_text(encoding="utf-8")
    if claim.is_venv:
        body += (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return Path(token).name.rstrip("/") in body


def _try_it_commands() -> list[list[str]]:
    """The commands of the try-it block that operate on the reader's repository.

    The page's two outside steps are asserted here and then dropped: the
    ``git clone`` of the placeholder URL and the ``cd`` into the reader's own
    directory. The first is replaced by the materialised clone
    (``_materialise_clone``) and the second by the scratch tree the commands run
    in (``_reader_repository``), so nothing in the run reaches the network or a
    directory the page cannot name.

    ``decide.py`` refuses exit 3 without a name in ``git config user.name``, and
    the commit it then makes also needs ``user.email``, so a page that dropped
    either line documents a five-minute path that stops partway. The identity the
    run has is the one the block itself sets, which is why the launcher env
    carries none of its own (see :func:`_reader_env`).
    """
    commands = _block_commands(_try_it_block())
    assert commands, "try-it block is empty"
    for argv in commands:
        words = _block_words(argv)
        if words == ("python3",):
            # A noni script: its clone-rooted path is validated where it is
            # launched (see ``_argv_for_run`` and
            # ``test_try_it_block_names_scripts_that_run``).
            continue
        assert words in _ALLOWED_SHELL, (
            f"try-it block runs a command the page may not name: {argv}"
        )
        if words == ("cd",):
            # The one step into the reader's own repository: the page cannot name
            # that directory, so it is a placeholder the test supplies.
            assert len(argv) == 2 and argv[1] == _READER_DIR_PLACEHOLDER, (
                f"the try-it block's cd must name the placeholder for the reader's "
                f"own repository ({_READER_DIR_PLACEHOLDER}): {argv}"
            )
        elif words == ("git", "clone"):
            # The page's first step, run outside the reader's repository: the test
            # materialises the clone, so the URL stays the placeholder and only the
            # target directory is compared.
            assert len(argv) == 4 and argv[3] == NONI_DIR, (
                f"git clone must name the placeholder URL and the {NONI_DIR} target "
                f"the paths run from: {argv}"
            )
            assert _CLONE_URL_PLACEHOLDER in argv[2], (
                f"git clone must use the page's placeholder URL: {argv}"
            )
        if words == ("git", "config"):
            # Exactly ``git config <key> <value>``, and only the identity keys.
            # argv[2] is the key position, so a value that happens to contain a
            # permitted key cannot satisfy this, and an arbitrary key fails.
            assert len(argv) == 4, (
                f"git config line must be the two-word form git config KEY VALUE: {argv}"
            )
            assert argv[2] in _ALLOWED_GIT_CONFIG_KEYS, (
                f"the try-it block sets git config {argv[2]!r}, which the page "
                "does not need and the test does not allow"
            )
    identity = [argv for argv in commands if _block_words(argv) == ("git", "config")]
    # The config key is argv[2] of ``git config <key> <value>``: checked at the
    # position rather than as a substring of every argument, so a value that
    # happens to contain the word cannot satisfy it.
    keys = {argv[2] for argv in identity if len(argv) > 2}
    for key in ("user.name", "user.email"):
        assert key in keys, (
            f"the try-it block does not set git config {key}, so the documented "
            "path would stop at decide.py's identity refusal or its commit"
        )
    return [argv for argv in commands if _block_words(argv) not in
            (("cd",), ("git", "clone"))]
