"""``python -m noni``: the console command reached through the package itself.

The console script ``noni`` is what an installed copy offers, and it is not
always what a reader has: a clone with ``src/`` on ``PYTHONPATH`` has the
package and no script on ``PATH``, which is the state docs/QUICKSTART.md tells
a reader to build when they would rather not install anything. That route had
no runnable command at all -- ``python -m noni`` died with
``No module named noni.__main__`` (issue #98).

So this file is one line of dispatch and nothing else. The console module owns
the dispatch table, the argument surface, the exit codes and ``--help``, and a
second copy of any of them here would be a second thing to keep in step; the
same command name is printed from either route because it comes from
:func:`noni.cli.main` and not from this file's name.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
