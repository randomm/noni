"""The ``git config`` grammar the page's config lines are read against.

This module owns the half of the launcher's decisions that is about *one verb*: which
token ``git`` reads as the key once its options have been walked, and which tokens may
not appear at all. It sits apart from :mod:`quickstart_gates` for the same reason the
gates sit apart from the launcher -- a reader who wants to know what the config gate
will and will not exec should read one file that says only that, and a test can call
these parts on one argv without the allow-list or the push guard being in scope.

Nothing here runs a command. Every rule is a decision on tokens, and the one entry
point (:func:`screen_config_key`) returns the key it accepted so the caller can gate
on it.
"""

from __future__ import annotations

import re

# The keys the page may set, read from the README's own reader: the two pages make one
# promise about these commands, so the list has one owner rather than two copies that
# can drift.
from readme_support import _ALLOWED_GIT_CONFIG_KEYS

# ``git config`` options that are not value-taking options: they change how the key is
# read or written, never what the next word means. Kept as data rather than inferred
# ("does it carry a ``=``"), because the gate has to tell a read-only query from a
# write, and the only way it can is by knowing which flags are booleans.
_CONFIG_BOOLEAN_OPTIONS: frozenset[str] = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list",
    "--null", "--fixed-regex", "--long", "--replace-all", "--includes",
    "--name-only",
})

# The read-only ``git config`` query forms. A page that *reads* a key is not the same
# command as one that writes it: the second is what redirects the run, so the two are
# told apart here rather than gated on the key word alone.
_CONFIG_QUERY_OPTIONS: frozenset[str] = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch",
})

# One value-taking ``git config`` option the gate knows about, with the flag that
# rejects it when a page prints it: ``-f/--file`` redirects the write to a file other
# than the clone's own config, ``--fixed-regex`` and ``--get-regexp`` take a pattern
# rather than a key, and ``--default`` reports a value the reader never wrote.
# Anything else is refused as an unknown option: a flag the walk does not know is a
# flag whose value-taking behaviour it cannot model, and guessing "not an option" is
# how ``git config -f <file> <evil-key>`` would come to be screened by a key git never
# read. A token carrying ``=`` consumes nothing: git splits it itself.
_CONFIG_VALUE_OPTIONS: dict[str, str] = {
    "-f": "--file/--f", "--file": "--file/--f",
    "--includes": "--includes/--no-includes",
    "--type": "--type",
    "--default": "--default",
    "--fixed-regex": "--fixed-regex/--no-fixed-regex",
    "--get-regexp": "--get-regexp/--no-get-regexp",
}

# The rejection above, as one message, so an unknown flag and a forbidden one fail the
# same way: the page is not a line this harness will exec.
_CONFIG_OPTION_REFUSAL = (
    "the page's git config carries the option {token!r}, which this harness will not "
    "exec {why}: it either writes somewhere other than the clone's own config or "
    "takes a value that is not a key, and a gate that cannot model the option cannot "
    "tell what the next word means: {argv}")

# The parts of a key that decide what git does with it. A section and a key name are
# each one dotted-word, so the two words of ``remote.origin.pushurl`` are section
# ``remote`` and key ``origin.pushurl``, and the rewrite key is section ``url`` with
# any subsection. Spelled as data so the screen says what it screens for.
_CONFIG_KEY_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_CONFIG_TRANSPORT_SECTIONS: frozenset[str] = frozenset({"pushurl", "url"})

# Where a token can point at a tree or a transport outside this run. Two shapes, both
# reachable by a page line that never names ``pushurl``: a value that is a path or a
# command line rather than a key (whitespace, a URL scheme, or any token carrying a
# path separator), which is what ``core.sshCommand``, an ``insteadOf`` target and a
# ``-f`` value all carry; and a value that names the fixture's own state clone
# (``.noni-state`` anywhere in it), which is how one permitted config line can
# address the private tree. Screened on every token the walk consumes, because the
# position of a word does not decide whether git reads it. The transport *key names*
# are screened separately on the folded spelling, because git matches config keys
# case-insensitively and ``remote.origin.pushURL`` is the same rewrite as the
# lower-case spelling. An ``@`` is deliberately not in this set: the page's own
# ``user.email`` value carries one.
_CONFIG_TRANSPORT_VALUE = re.compile(
    r"\s|[a-zA-Z][a-zA-Z0-9+.-]*://|/|\\|\.noni-state")


def _config_key_parts(key: str) -> tuple[str, str]:
    """The ``(section, rest)`` of a config key, the way git folds and splits it.

    git matches config keys case-insensitively, so both halves come back lowered:
    comparing the printed spelling instead would let ``remote.origin.pushURL`` or
    ``URL.x.INSTEADOF`` past a screen that only looked at the exact text. The
    subsection of a ``url.<base>.insteadOf`` key lives inside ``rest``, which is why
    the screen tests the whole remainder and not just a final segment.
    """
    section, _, rest = key.partition(".")
    return section.lower(), rest.lower()


def _assert_key_free(value: str, argv: list[str], where: str) -> None:
    """Refuse a token whose *content* points at a tree or a transport outside this run.

    The transport key names (``pushurl``, ``insteadOf``, a ``url`` section) are
    compared on the folded spelling, so case and a subsection name cannot hide them;
    the rest (:data:`_CONFIG_TRANSPORT_VALUE`) is matched on the printed spelling,
    which is what a path or a URL is. The page's own values contain none of them:
    ``Casey``, ``casey@example.invalid``, ``origin``, ``main``, ``user.name``,
    ``user.email``.
    """
    section, rest = _config_key_parts(value)
    transport = (section in _CONFIG_TRANSPORT_SECTIONS
                 or "pushurl" in rest or "insteadof" in rest
                 or bool(_CONFIG_TRANSPORT_VALUE.search(value)))
    assert not transport, (
        f"the page's git config names the transport {value!r} as its {where}, which "
        f"rewrites where these commits and pushes go, so this harness will not run "
        f"it: {argv}")


def _is_config_option(token: str) -> bool:
    """Whether one ``git config`` token is an option rather than a key or value.

    ``-`` alone is not an option, and a token whose first character after the dashes
    is not a letter is not one either -- a quoted value that happens to begin with a
    dash stays a value, and treating it as a flag is how an option's value would come
    to be read as the key.
    """
    if not token.startswith("-") or len(token) < 2:
        return False
    body = token.lstrip("-")
    return bool(body) and body[0].isalpha()


def _is_config_key(token: str) -> bool:
    """Whether one token has the shape of a git config key at all.

    A key is a section and a name, each one dotted-word of ascii letters, digits,
    dots, dashes and underscores -- ``user.name``, ``remote.origin.pushurl``,
    ``url.<base>.insteadOf``. A path (``/tmp/other``), a value carrying a space, or a
    bare word with no dot is not a key, so a walk that stopped at one of those would
    be about to compare a non-key against the identity list. Requiring the shape first
    is what makes that comparison mean "this is the key" rather than "this token was
    not on a deny-list".
    """
    section, _, rest = token.partition(".")
    return bool(_CONFIG_KEY_PART.fullmatch(section)
                and rest and _CONFIG_KEY_PART.fullmatch(rest))


def _reject_option(token: str, name: str, argv: list[str]) -> None:
    """Refuse an option the gate cannot model, or one it knows it must not exec.

    Known value-taking options are refused for the reason recorded beside them;
    anything else is refused because the walk cannot tell whether it consumes the next
    word, and "treat it as a value" and "treat it as the key" are both guesses.
    """
    why = _CONFIG_VALUE_OPTIONS.get(name)
    if why is None:
        why = ("because it is not an option this harness models (known: "
               f"{sorted([*_CONFIG_BOOLEAN_OPTIONS, *_CONFIG_VALUE_OPTIONS])})")
    raise AssertionError(_CONFIG_OPTION_REFUSAL.format(
        token=token, why=why, argv=argv))


def _assert_not_push_write(token: str, argv: list[str]) -> None:
    """Refuse ``git config --push``, the one option that changes what the line does.

    ``git config`` takes one option that changes the operation itself rather than how a
    key is read: ``--push`` writes the push end of a remote, which is the rewrite this
    harness exists to stop. git honours it only in the form that takes no value at all,
    so a line that carries a word after it (``--push origin``) is not the command git
    documents, and a token carrying ``=`` (``--push=<elsewhere>``) is a value smuggled
    past a screen that only looked at the visible key. All three are refused: the page
    reads and writes identity keys, never a remote's push end.
    """
    if token != "--push":
        return
    raise AssertionError(
        f"the page's git config carries --push, which writes the push end of a "
        f"remote -- the one thing this harness must never exec: {argv}")


def _assert_query_takes_a_key(token: str, argv: list[str], index: int) -> None:
    """Refuse a query that took its key with ``=``, leaving git no key to read.

    ``--get=<key>`` is a real git invocation, but it consumed the key slot: the next
    word is a value git never reads as a key, and the transport name hidden inside the
    flag is the only key this line has.
    """
    name = token.split("=", 1)[0]
    if "=" not in token or name not in _CONFIG_QUERY_OPTIONS:
        return
    assert any(not _is_config_option(word) for word in argv[index + 1:]), (
        f"the page's git config query {token!r} carries its key inside the flag, so "
        f"git reads no key at all from this line, which is not a command the page "
        f"prints: {argv}")


def _walk_options(argv: list[str], start: int, where: str, *,
                  key_is_due: bool = False) -> None:
    """Walk every token from ``start``, screening each as the word git is being given.

    The option grammar of ``git config`` is positional, so this walk does not stop at
    the first bare word: a word ends one run of options and starts another, and
    ``user.name Casey --push`` is git's own remote-writing command with an identity key
    in front of it to satisfy a gate that stopped at the key.

    Two tokens are special. A query that took its key with ``=`` (``--get=<key>``) is a
    real git command that then reads no key at all, so a gate that screened only the
    first word after the verb would bless a line whose real key sat inside the flag; it
    is refused, and only where a key is due -- at the head of the whole walk, the one
    place git reads a key from. A second run of options after the key takes the key as
    a given, which is why the walk is told where it started. ``--push`` is refused at
    any position: it is the one option that changes what the line *does* -- it writes a
    remote's push end -- and git honours it only as a bare token, so any other spelling
    is a value smuggled past a key screen.

    Otherwise a ``--flag=value`` or a boolean option consumes nothing, a known
    value-taking option consumes the token after it (and that token is screened as a
    value), and any other option token is refused as one the walk cannot model: "it is
    a value" and "it is the key" are both guesses about a flag this harness has never
    read the manual for.
    """
    index = start
    run_head = key_is_due
    while index < len(argv):
        token = argv[index]
        if not _is_config_option(token):
            _assert_key_free(token, argv, where)
            # A bare word ends this run of options; the next option opens a new one.
            # Whether a *key* is due in it is not re-decided here -- the caller says by
            # starting the walk before or after the key git reads.
            run_head = key_is_due
            index += 1
            continue
        if run_head:
            _assert_query_takes_a_key(token, argv, index)
        run_head = False
        name = token.split("=", 1)[0]
        _assert_not_push_write(token, argv)
        _assert_key_free(token if "=" in token else name.lstrip("-"), argv, where)
        if "=" in token or name in _CONFIG_BOOLEAN_OPTIONS:
            index += 1
            continue
        _reject_option(token, name, argv)
        assert index + 1 < len(argv), (
            f"the page's git config option {token!r} carries no value: {argv}")
        _assert_key_free(argv[index + 1], argv, f"{where} value")
        index += 2


def screen_config_key(argv: list[str], config_index: int) -> str:
    """The key of one page ``git config`` line, past its option tokens, or a failure.

    Walks forward from the verb and stops at the first token git would read as the key:
    a ``--flag=value`` carries its own value, a boolean option
    (:data:`_CONFIG_BOOLEAN_OPTIONS`) consumes nothing, a known value-taking option
    consumes the token after it, and any other option token is refused outright. What
    the walk saw then has to satisfy five things:

    - every token it walked over, and the value any option consumed, is screened for a
      transport, a path or a state path (:func:`_assert_key_free`), so neither an
      option position nor a consumed value can smuggle a ``pushurl``, an ``insteadOf``
      or an ``-f`` target past a gate that only examined the visible key;
    - no option is one that redirects the write (``-f``) or supplies a non-key value
      (``--default``, a pattern), and none is a flag the walk cannot model;
    - the key has the shape of a key (:func:`_is_config_key`), so a path or a spaced
      value is never compared against the identity list and blessed;
    - the key itself is transport-free, in either spelling;
    - unless the line is a read-only query, the key is one of the identity pair --
      setting anything else is the thing that redirects the run.

    Everything after the key is walked by the same function, which is what refuses a
    ``--push`` or an ``-f`` that a gate stopping at the key never saw.
    """
    index = config_index + 1
    queries: list[str] = []
    _walk_options(argv, index, "option", key_is_due=True)
    while index < len(argv):
        token = argv[index]
        if not _is_config_option(token):
            break
        name = token.split("=", 1)[0]
        if name in _CONFIG_QUERY_OPTIONS:
            queries.append(name)
        if "=" in token or name in _CONFIG_BOOLEAN_OPTIONS:
            index += 1
        elif name in _CONFIG_VALUE_OPTIONS:
            index += 2
        else:
            index += 1
    assert index < len(argv), f"the page's git config names no key: {argv}"
    key = argv[index]
    _assert_key_free(key, argv, "key")
    assert _is_config_key(key), (
        f"the page's git config has no key at the position git reads one: "
        f"{key!r} in {argv}")
    # A read-only query is only a query if git still reads a key after it: a value the
    # query took with ``=`` left no slot for one, and such a line does nothing at all
    # -- it is not the command the page prints, so it is refused rather than passed as
    # "reading a key the harness would not let it set".
    assert queries or key in _ALLOWED_GIT_CONFIG_KEYS, (
        f"the page sets git config {key!r}, which is not an identity key "
        f"({sorted(_ALLOWED_GIT_CONFIG_KEYS)}), so this harness will not run "
        f"it: {argv}")
    _walk_options(argv, index + 1, "word after the key")
    return key
