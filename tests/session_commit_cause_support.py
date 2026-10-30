"""The git-seam doubles the commit-failure classifier's suites drive.

The classifier in ``_commit_cause`` asks every question through one function,
``_commit_cause._git``, which is the seam these two suites replace: a test hangs
one class of git call, refuses one verb, or records every argv, while every other
call keeps running for real through the hardened helper. Capturing that helper
before any monkeypatch is what lets a wrapper call it without recursing into
itself. Both suites build real trees and assert on what the probes actually did,
so the doubles live here rather than being copied between the two files.
"""

from __future__ import annotations

import subprocess

from noni import _session_git

_HARDENED_GIT = _session_git.git


def _verb_of(argv):
    """The git verb of an argv the hardened helper built, or "" when it has none.

    ``git.git`` puts a ``-C``/``-c`` preamble in front of the verb, so the verb
    is the first word after that preamble which does not start with a dash.
    """
    skip_next = False
    for part in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if part in ("-C", "-c"):
            skip_next = True
            continue
        if part.startswith("-"):
            continue
        return part
    return ""


def _hung_probe_git(hung_verbs):
    """A ``subprocess.run`` replacement that times out the named git verbs only.

    ``git.git`` passes the argv it built (with the ``-C``/``-c`` preamble in
    front), so :func:`_verb_of` is how a test drives the timeout sentinel for one
    class of call (a transport call that cannot finish, or one plumbing verb)
    while every other call keeps answering for real. Every call is recorded, so
    a test can say which probes this run actually asked.
    """
    real_run = subprocess.run

    def _run(cmd, *args, **kwargs):
        argv = [str(part) for part in cmd]
        verb = _verb_of(argv)
        _run.asked.append(verb)
        if verb in hung_verbs:
            raise subprocess.TimeoutExpired(list(cmd), _session_git.GIT_TIMEOUT)
        return real_run(cmd, *args, **kwargs)
    _run.asked = []
    return _run


def _git_refusing(verb, said):
    """Adapt a refusal of one git verb to ``git``'s own signature.

    The refusal has the shape git's own rejection has (non-zero exit, text on
    stderr) and only the named verb is refused: every other call runs for real
    through the hardened helper, so the classifier still has to measure the
    upstream, the index and the work tree of this tree before it can name the
    fault. Forcing it at this seam, rather than by arranging a state git happens
    to refuse, is what makes it independent of whatever identity the checkout's
    ambient config supplies (see the test that uses it). Same seam
    :func:`_git_via` uses, for the reason that docstring gives.
    """
    refused = subprocess.CompletedProcess(["git", verb], 128, "", said)

    def _call(repo, *args, _run=subprocess.run, **kwargs):
        if args and str(args[0]) == verb:
            return refused
        return _HARDENED_GIT(repo, *args, _run=_run, **kwargs)
    return _call


def _git_via(run):
    """Adapt a ``subprocess.run`` double to ``git``'s own signature.

    Replacing the seam (rather than ``subprocess.run`` itself, which the hardened
    helper reaches through its own module) is what lets a test hang one class of
    git call and leave the rest answering for real. The helper is captured before
    the monkeypatch, so the wrapper cannot recurse into itself. (The helper
    resolves ``subprocess.run`` once, at its own definition, so patching
    ``subprocess.run`` would reach neither the hung call nor the others.)
    """
    def _call(repo, *args, _run=run, **kwargs):
        return _HARDENED_GIT(repo, *args, _run=_run, **kwargs)
    return _call
