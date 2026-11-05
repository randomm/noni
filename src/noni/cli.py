"""The ``noni`` console command: dispatch only.

One command, one subcommand per shipped tool: ``census``, ``register``,
``claim``, ``close``, ``release``, ``decide`` (a supersede is ``decide``'s
``--supersedes`` flag), ``order`` and ``intent``. The argv after the subcommand
is handed to that tool's own ``main`` verbatim, so flags, output, exit codes and
``--help`` bytes are exactly what the in-place script produces — which is what
the paired wrapper-vs-console test asserts.

This module holds no behaviour of its own: adding a tool means a row in
``TOOLS`` and nothing else.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

# subcommand -> (module, entry point). Every entry's module owns its own
# docstring, parser and exit-code table; nothing is re-declared here.
TOOLS: dict[str, tuple[str, str]] = {
    "census": ("noni.census", "main"),
    "register": ("noni.register", "main"),
    "claim": ("noni.claim", "main"),
    "close": ("noni.close", "main"),
    "release": ("noni.release", "main"),
    "decide": ("noni.decide", "main"),
    "order": ("noni.order", "main"),
    "intent": ("noni.intent", "main"),
}

# One line per subcommand, for this command's own --help. Each tool's flags and
# exit codes are its own --help's business, not a second copy here.
SUMMARIES: dict[str, str] = {
    "census": "read-only checks over the ledger, register and ordering artifact",
    "register": "allocate a session-id and write its register file",
    "claim": "append a claim row to a session's register file",
    "close": "set a session's status to closed",
    "release": "remove one claim row from a session's register file",
    "decide": "write one dated steering decision record (supersede with --supersedes)",
    "order": "write the ordered list of issues to work next",
    "intent": "write the standing intent file the agents read first",
}


def _tool_main(name: str) -> Callable[[list[str] | None], int]:
    """The ``main`` of the tool's own module, imported only when asked for.

    The import is deferred so ``noni --help`` does not pay for the census's
    module body, and so a broken optional tool cannot stop the command from
    listing the others.
    """
    import importlib

    try:
        module_name, entry = TOOLS[name]
    except KeyError:  # pragma: no cover - argparse rejects unknown names first
        raise SystemExit(f"noni: unknown subcommand {name!r}") from None
    return getattr(importlib.import_module(module_name), entry)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one tool. Returns the tool's own exit code, unchanged."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="noni",
        description="The noni direction layer: one command, one subcommand per tool.",
    )
    sub = parser.add_subparsers(dest="tool", metavar="TOOL")
    for name in TOOLS:
        sub.add_parser(name, help=SUMMARIES[name], add_help=False)
    args, rest = parser.parse_known_args(argv)
    if args.tool is None:
        parser.print_help(sys.stderr)
        return 2
    return _tool_main(args.tool)(rest)


if __name__ == "__main__":
    raise SystemExit(main())
