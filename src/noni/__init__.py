"""The shipped tools as one installable package.

This package is the whole product: the steering ledger's writer and its schema,
the session register's writer, the claim writer, the ordering artifact's writer
and its readers, and the unified census that arbitrates them. Program names the
tools print come from :mod:`noni.labels`, not from a file's location, so the
in-place wrappers under ``skills/<skill>/scripts/``, the ``noni`` console command
and a wheel-installed copy all print the same bytes.

The tools reached as subprocesses by a wrapper are the same modules this package
imports, so a seam a test puts on one is visible to the other route too.
"""

__all__ = ["__version__"]

# One owner for the version: pyproject.toml reads it from this attribute, so a
# release bumps one line and the wheel's metadata cannot disagree with the
# package.
__version__ = "0.1.0"
