"""What the two shell census entry points run: the unified census, one group.

``skills/steering-ledger/scripts/census.sh`` and
``skills/sessions-claims/scripts/census-sessions.sh`` are bash wrappers that
carry no rules of their own. Each takes the one directory its caller names,
resolves it, and hands it here; this module turns that (directory, options)
pair into the argv of a unified-census run restricted to the group the entry
point belongs to, and calls ``census.main`` with it. The wrapper's exit code is
therefore the census's own, and the classes it runs are the ones the check
contract declares — not a list a shell script keeps a copy of.

``--repo`` is set to the *parent* of the named directory, never to the directory
itself. Every path the census reports is rooted into the tree ``--repo`` names,
and a ledger or register the caller passed from outside that tree — an absolute
path, or a relative walk out of the cwd — has no root-relative name to take, so
the census falls back to the path's last segment. Naming the directory itself as
the repo would put every row of a run the docs tell people to type into that
fallback: the single word ``decisions`` where a reader expects a path. Naming the
parent keeps an in-tree ledger spelled the way a census over the whole repo
spells it, and leaves the genuinely out-of-tree case to the census's own naming
rule.

The one-directory rule, and the refusal of a register that is not there, are
enforced here, before the census is called. Both belong to the wrapper because
the census cannot see them: the unified census takes its state paths as flags and
audits the tree ``--repo`` names, so an unnamed directory, a second directory, or
a path that is not a directory at all is invisible to a run over the tree that
contains it -- and a census that reads nothing has no verdict to give. Everything
every other argument is passed through untouched, so ``--json``, ``--strict``,
``--now`` and the rest stay the census's flags with the census's refusals -- this
module re-implements none of them.

Nothing here opens a path, evaluates a class, or invents an exit code. The three
refusals below return the census's usage code and name the path they refused, in
the census's own style.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .census import LEDGER_CHECKS, SESSION_CHECKS, main
from .census_report import CLASS_CODE, EXIT_USAGE


def _build_parser():
    """The census's own argument parser, resolved through ``census`` at the call.

    The flag surface is ``census_cli``'s and this wrapper re-implements none of it,
    so every question about a token -- is it a flag, does it take a value, is the
    prefix rule on -- is asked of that parser. It is reached through the census
    module rather than bound at import because the census is the module the
    wrappers' tests put their seams on (the same rule ``census_run`` follows for
    every census name it uses): a parser a census test replaces, or a census that
    fails to load at all, is seen here the way it is seen by ``census.main``,
    instead of against a copy bound when this module was imported.
    """
    return importlib.import_module("noni.census")._build_parser()

# Whether the census's parser resolves an option by prefix for this process. Read
# from that parser at call time -- never captured at import: the flag surface is
# ``census_cli``'s, the prefix rule is part of it, and a value read once at import
# is a copy that can disagree with the parser the census is about to build.
_ABBREVIATIONS_ATTR = "allow_abbrev"


def _abbreviations() -> bool:
    """The census's own prefix setting, asked of the census's parser now.

    argparse consults ``allow_abbrev`` at the moment it matches a token, so the
    wrapper asks the same parser the census will use, at the moment it asks about
    a token: a token is never called a bare flag here when the census is about to
    read it as one, and never called a flag when the census is about to refuse it.
    """
    return bool(getattr(_build_parser(), _ABBREVIATIONS_ATTR, True))

# The noun each entry point's directory is called, in the usage line and in its
# refusals: the word a reader has to match against the tree they are standing in.
_ENTRY_POINTS: dict[str, tuple[str, frozenset[str]]] = {
    "census.sh": ("decisions", LEDGER_CHECKS),
    "census-sessions.sh": ("sessions", SESSION_CHECKS),
}

# The flag each group's directory reaches the census through, keyed by the
# group's own class set rather than by a name a caller could mistype.
_GROUP_FLAG: dict[frozenset[str], str] = {
    LEDGER_CHECKS: "ledger",
    SESSION_CHECKS: "sessions",
}


def _takes_a_separate_value(option: str, group: frozenset[str] | None = None) -> bool:
    """Whether the census's own parser reads a following token as ``option``'s value.

    Asked of the parser the census builds -- never of a list kept here: the flag
    surface is ``census_cli``'s and this module re-implements none of it. The
    wrapper must know which tokens are values and not candidate directories, and
    the parser is the only authority on that. argparse's own arity spelling is
    read, not a copy of it: ``None`` is one value, ``0`` is none (`--strict`,
    `--json`), and an explicit number or `*`/`+`/`?` takes at least one.

    ``group`` is the entry point's own class set, and it decides what a
    **retired** flag does to the token after it. A flag that names the *other*
    register (`--sessions` at the ledger entry point, `--ledger` at the sessions
    one) is the old cross-group dispatch issue #99 removed: the census still
    defines the flag, so it parses, and if its value were consumed here the
    caller would be refused for a missing directory instead of for the option
    they typed. It is therefore answered ``False`` -- the value stays a
    positional, the run proceeds, and the census refuses it (see
    :func:`_refuse_retired_group_option`). Only the entry point's own group flags
    (`--ledger` for the ledger census) keep their value.

    A name argparse resolves to several flags, or to none, is not answered here at
    all: it is left for the census to refuse in its own words, with the token after
    it judged on its own.
    """
    if "=" in option:
        # `--opt=value` names its own value, so no token after it belongs to it.
        # Answered without the parser: a token carrying `=` is never matched by
        # prefix, whether or not the census defines the flag -- an unknown
        # `--nope=x` is refused by the census and its `=value` half is not the
        # wrapper's to call a directory.
        return False
    if group is not None and _is_a_retired_group_option(option, group):
        return False
    return _value_arity(option) is True


def _positionals(argv: list[str], group: frozenset[str] | None = None) -> list[str]:
    """The bare tokens of one command line: the arguments the census parses as
    positionals, which for a census run is at most the state directory.

    ``not a.startswith("-")`` is not that set: the value of a value-taking
    option (`--only ledger-record`, `--skip hygiene`, `--now 2026-01-01T00:00:00`)
    is a bare token the census never sees as an argument, and counting it is a
    wrapper that refuses the options the docs promise. A flag that consumes the
    next token is skipped with it; `--opt=value` carries its own value, so it
    swallows nothing. ``group`` makes the walk entry-point aware, so a retired
    cross-group flag leaves its value standing (see
    :func:`_takes_a_separate_value`).
    """
    positional: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if not arg.startswith("-"):
            positional.append(arg)
        elif arg != "-" and _takes_a_separate_value(arg, group):
            skip_next = True
    return positional


def _census_options(argv: list[str], group: frozenset[str] | None = None) -> list[str]:
    """The caller's own options, each value kept glued to the flag that takes it.

    ``_positionals`` already knows which bare tokens belong to a value-taking
    option; the same walk has to build the tail, because a filter on
    ``startswith("-")`` hands the census a value with its flag missing -- the
    census's ``--only`` is repeatable, so a stray class name is accepted there and
    quietly changes which rows print, and a state-path flag whose value was left
    behind reads to the census like a directory the caller never typed.

    A token is a flag when the census's parser matches it as one: an exact option,
    or a prefix of one while the parser is resolving prefixes. Everything else --
    `--nope`, an ambiguous prefix once prefix matching is off -- is the caller's
    token, passed unchanged with the token after it so the census refuses it in its
    own ``unrecognized arguments`` words. A value-taking flag left standing last by
    an interrupted command line keeps its flag alone, where the census answers its
    own missing-argument error.
    """
    options: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg != "-" and _is_a_known_option(arg):
            options.append(arg)
            if _takes_a_separate_value(arg, group) and index + 1 < len(argv):
                options.append(argv[index + 1])
                index += 1
        elif arg.startswith("-") and arg != "-":
            # Not a flag the census defines: an unknown token, and the token after
            # it is the caller's to have refused, not the wrapper's to swallow.
            options.append(arg)
        index += 1
    return options


def _is_a_known_option(option: str) -> bool:
    """Whether ``option`` is a flag the census defines, spelled as the caller typed
    it: an exact option string, or `--name=value` for one of those.

    Used where an unknown token must keep the token after it (see
    :func:`_census_options`). A `--name=value` whose name is not a census flag is
    unknown as a whole -- the name before the `=` is what the parser knows -- so it
    is not answered by :func:`_is_an_option`, which lets a token carrying `=`
    through as the caller's own so an unknown one is refused whole, flag and value.
    """
    name = option.partition("=")[0]
    return name in _build_parser()._option_string_actions


def _is_an_option(option: str) -> bool:
    """Whether the census's parser matches ``option`` as one of its own flags.

    The parser answers, in the state the census will use it: exact names always,
    and prefixes only while the census has prefix matching on. An ambiguous prefix
    is a flag the census will itself refuse as ambiguous, so it counts as one here
    and its value is kept with it, reaching the census as the pair the caller
    typed.
    """
    parser = _build_parser()
    if option in parser._option_string_actions:
        return True
    # Only a token the parser can read as a flag is put to it: argparse raises on
    # a bare word handed to its matcher, and a bare word is not a flag anyway.
    return option.startswith("--") and "=" not in option \
        and bool(parser._get_option_tuples(option))


def _value_arity(option: str):
    """``True``/``False`` for a flag that does/does not consume the next token, or
    ``None`` when the parser cannot say: no match, or an ambiguous prefix.

    Asked of the census's parser as it stands, so a flag the census's parser does
    not define is ``None`` -- no answer -- and the census is the one that refuses
    it.
    """
    parser = _build_parser()
    if not option.startswith("--"):
        # Not something the parser can match; argparse raises on a bare word put
        # to its matcher, and this module is not the place that answer is made.
        return None
    matches = parser._get_option_tuples(option)
    if not matches and not _abbreviations():
        action = parser._option_string_actions.get(option)
        return action is not None and action.nargs != 0
    if len(matches) != 1:
        return None
    return matches[0][0].nargs != 0


def _only(checks: frozenset[str]) -> list[str]:
    """Repeated ``--only`` flags for one group, in the check contract's own order.

    The order comes from ``CHECKS`` and not from the frozenset, so the bytes of a
    wrapper's command line do not depend on a hash.
    """
    args: list[str] = []
    for name in CLASS_CODE:
        if name in checks:
            args += ["--only", name]
    return args


def argv_for(target: str, options: list[str], checks: frozenset[str]) -> list[str]:
    """The unified census's argv for one group's census of ``target``.

    ``target`` reaches ``--ledger`` / ``--sessions`` exactly as the caller
    spelled it — including the empty string, which the census names in its own
    refusal — while ``--repo`` is built from the resolved path, the only form
    whose parent reliably means the directory above it.
    """
    resolved = Path(target).resolve()
    return ["--repo", str(resolved.parent), "--" + _GROUP_FLAG[checks], target,
            *_only(checks), *options]


def _is_a_retired_group_option(option: str, group: frozenset[str]) -> bool:
    """Whether ``option`` names a register this entry point does not census.

    The census owns one flag per register (`--ledger`, `--sessions`) and each entry
    point names its own directory with its own. A caller who types the *other*
    one's flag at an entry point is typing the form the retired dispatch had: the
    census parses it, so the wrapper must not spend the token after it on a value
    it is about to refuse. `--name=value` carries its own value and is never one.

    The register flag is taken from :data:`_GROUP_FLAG` by identity, never by
    literal, so this stays true when a register is added or renamed.
    """
    name = option.partition("=")[0]
    if "=" in option:
        # `--name=value` carries its own value, so it never strands a token after it.
        return False
    own = _GROUP_FLAG.get(group)
    # The register flags are spelled with their `--`, as the parser knows them.
    registers = ["--" + flag for flag in _GROUP_FLAG.values()]
    if own is None or name == "--" + own:
        return False
    return any(name == flag for flag in registers) \
        and name in _build_parser()._option_string_actions


def _refuse_retired_group_option(label: str, noun: str, argv: list[str],
                                group: frozenset[str]) -> int | None:
    """The refusal of a retired cross-group dispatch, or ``None`` for a clean line.

    The census defines both register flags, so an old `census.sh --sessions DIR`
    would otherwise be answered as a census of the sessions tree through the
    ledger entry point -- the silent wrong-group census issue #99 was written
    against. Refused here, in the entry point's own words, naming the option the
    caller typed and pointing at the entry point that does run that group. It runs
    before the directory checks so the option, not a missing path, is what the
    caller is told about.
    """
    for arg in argv:
        name = arg.partition("=")[0]
        if arg != "-" and _is_a_retired_group_option(name, group):
            other = _sibling_entry_point(group)
            return _refuse(label, noun, f"{name} is not a {label} option "
                                        f"(run {other} over the register that "
                                        f"{name} names)")
    return None


def _sibling_entry_point(group: frozenset[str]) -> str:
    """The other entry point's name, for the refusal that points a caller at it."""
    for label, (_noun, checks) in _ENTRY_POINTS.items():
        if checks != group:
            return label
    return "the entry point for that register"


def _refuse(label: str, noun: str, detail: str) -> int:
    """One usage refusal, in the census's style, returning the census's code.

    The line names the entry point the caller typed, the fault, and the path they
    named -- the three things a reader needs to fix a command line -- and the code
    is ``EXIT_USAGE``, the code the census's own argparse refusals carry.
    """
    print(f"{label}: error: {detail} (usage: {label} [--help] [census options] "
          f"<state-root>/noni/{noun})", file=sys.stderr)
    return EXIT_USAGE


def run(label: str, noun: str, argv: list[str] | None,
        checks: frozenset[str]) -> int:
    """One entry point's whole run: check the shape, then hand the census its argv.

    ``--help`` is the package's own text (see ``shim_help``). Anything else has to
    be exactly one directory that exists and is a directory, plus whatever census
    options the caller named. Each refusal is the census's usage code and names the
    path the caller gave: a census of nothing -- or of one of two registers --
    would print a verdict the caller never pointed at, and whoever scripts the run
    reads an exit 0 as a clean census.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 1 and argv[0] in ("--help", "-h"):
        from . import shim_help

        return shim_help.print_help(label)
    retired = _refuse_retired_group_option(label, noun, argv, checks)
    if retired is not None:
        return retired
    positional = _positionals(argv, checks)
    # An empty argument is a positional argparse would hand on, and ``Path("")``
    # is the cwd: a caller who left the directory empty in a script would have its
    # census run over whatever `noni/decisions` sat beside, and read the verdict as
    # the one they asked for. Refused with the other no-directory answer.
    if not positional or positional[0] == "":
        return _refuse(label, noun, f"no {noun} directory given")
    if len(positional) > 1:
        listed = " ".join(positional)
        return _refuse(label, noun, f"one directory at most, got {len(positional)}: {listed}")
    target = Path(positional[0])
    if not target.is_dir():
        reason = "is not a directory" if target.exists() else "does not exist"
        return _refuse(label, noun, f"the {noun} path {positional[0]} {reason}")
    return main(argv_for(positional[0], _census_options(argv, checks), checks))


def run_entry(label: str, argv: list[str] | None = None) -> int:
    """The run of one named entry point, its group and noun from one table.

    The thin wrapper under ``skills/`` calls this rather than naming a group of
    its own, so the class set a wrapper runs is decided here and nowhere else.
    A label the table does not name is a bug in the caller, not input to accept:
    it raises rather than quietly running the census over every group.
    """
    if label not in _ENTRY_POINTS:
        raise KeyError(f"no census entry point is named {label!r}")
    noun, checks = _ENTRY_POINTS[label]
    return run(label, noun, argv, checks)


def run_ledger(argv: list[str] | None = None) -> int:
    """The steering-ledger entry point: the unified census over one named ledger."""
    return run_entry("census.sh", argv)


def run_sessions(argv: list[str] | None = None) -> int:
    """The sessions entry point: the unified census over one named register."""
    return run_entry("census-sessions.sh", argv)
