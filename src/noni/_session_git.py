"""The git mechanics the four session writers build their commit with.

register.py, claim.py, close.py and release.py all write one file under
``noni/sessions/`` and commit exactly that file. The three steps they need are
here, once, so no writer keeps its own copy of a git call:

  atomic_write(path, text)              -- same-directory temp file, os.replace
  writer_name(sid)                      -- the one repo-relative name a writer
                                       commits: ``noni/sessions/<sid>.md``, or
                                       ``""`` for an id it will not accept
  stage_and_commit(repo, name, msg)     -- three steps, in this order:
      1. ``git -C <abspath(repo)> reset -q -- <name>``
                                      the writer's own index entry back to HEAD
                                       (a no-op for an untracked path)
      2. ``git -C <abspath(repo)> add -- <name>``
                                      gives an untracked or never-committed
                                       path its index entry
      3. ``git -C <abspath(repo)> commit -q -m <msg> --only -- <name>``
                                      commits exactly that path — a brand-new
                                      one included, because step 2 gave it an
                                      index entry
     Every other staged entry is never touched: it stays staged and
     uncommitted. A whole-tree commit is never used.

``<name>`` is a path *inside* the state root -- ``noni/sessions/<sid>.md``, not a
path the caller spells from wherever it happens to be standing. That is a contract
rather than a guess: the primitive never resolves a caller's path against the process
working directory, so no reading of a relative ``--repo`` can survive into the
pathspec. :func:`writer_name` is the one validated derivation of that name -- it asks
the session id the questions a name cannot answer for itself -- and
:func:`relative_name` is the guard :func:`stage_and_commit` runs on whatever name it is
handed, including one a caller built by hand. The writers take the refusal before they
write a byte. The push loop is not here: :mod:`noni._session_push` imports these
primitives, and a re-export would be a cycle, so the writers import it for ``--push``.

The reason a commit failed is named in noni's own words rather than handed through
as git's. That half lives in :mod:`noni._commit_cause`, which classifies the four
states a writer can be left in (no upstream, the upstream gone, nothing to commit,
some other git fault). :func:`stage_and_commit` asks it for that line only when a
commit is refused, importing it there rather than at module scope, so no compile-time
cycle exists between the two. Caller-supplied text in a printed refusal (a name, an
argument, a path) goes through :func:`safe_text` first, so no escape sequence reaches
the terminal, and a path goes through :func:`safe_path` on top of it, so one path can
never print more lines than the refusal has. The commit also refuses a link it would have followed, asking the
state root, the session file and its directory first (noni._session_paths).

The set of statuses that end a session lives here too, as
:data:`TERMINAL_STATUSES`, so the four writers agree on what "already closed" means,
and :func:`session_status` reads the field that set is decided from, so no writer
keeps its own copy of the '- status:' scan. A test asserts it equals the census's own
two inactive sets (``census_sessions._INACTIVE_STATUSES`` and
``census.INACTIVE_STATUSES``); the census sources are not changed and import nothing
from here.

Like the package's other git helpers, every call is bounded, never signs, runs no
repository hooks and refuses the external transports a remote could name. This module is
mechanics only: it owns no exit-code contract and prints the caller's label on every
message, so a fault reads in the voice of the command the operator ran.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from . import _session_paths, gitenv
from ._safe_text import CONTROL_CHARS, safe_text
from ._safe_text import TEXT_LIMIT as GIT_OUTPUT_LIMIT  # re-export: the limit names

# Statuses that end a session. A claim from a session in one of these states
# no longer counts toward the double-claim check, and close.py calls a session
# already in one of them terminal: it has nothing left to do. The status is
# stripped and lower-cased before it is compared. The census owns the same set
# twice over (its own two modules), and a test pins the two copies together;
# a status added on one side without the other is that test's failure.
TERMINAL_STATUSES: frozenset[str] = frozenset({"closed", "done", "superseded", "ended"})

# Where the session files live, as a name inside the state root. The four
# writers and the census read this one directory; a writer's file is always
# ``<this>/<session-id>.md``, so :func:`writer_name` is the only place the
# spelling is written. The suffix is part of the shape a name must have: every
# caller of :func:`relative_name` stages one session file.
SESSIONS_REL = "noni/sessions"
SESSION_SUFFIX = ".md"

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124
# Attempts the push loop makes before it reports failure.
MAX_PUSH_ATTEMPTS = 3

# A session id or a task reference is one token of a commit message, so it is
# validated before it reaches git: no whitespace, no path separator. Every
# writer here builds its message as a fixed prefix plus one such token, which
# is what keeps free text out of ``git commit -m``. fullmatch, not match: '$'
# also matches before a trailing newline.
TOKEN_RE = re.compile(r"^[^\s/\\]+$")

# The one wording for a refused name: the sentence :func:`stage_and_commit`
# returns and every writer prints, and the fix line that goes under it. Both
# live here so the primitive's backstop and the four writers cannot say two
# different things about the same refusal. ``{name}`` is the offender as the
# caller spelled it; ``{arg}`` names the argument the operator typed.
NAME_REFUSAL = ("cannot commit {name}: the session writers commit only a path "
                "inside the state root (never an absolute path, never one that "
                "leaves it, never a path outside {directory}, and never a name "
                "carrying a control character)")
NAME_REFUSAL_HINT = ("pass {arg} as one file name under {directory}, without "
                     "its .md suffix and with no path separator in it")


def name_refusal(name: object, *, arg: str = "--session-id",
                 directory: str = SESSIONS_REL) -> tuple[str, str]:
    """The ``(headline, hint)`` pair for one refused name, from the one pair.

    Four writers and the primitive each print this refusal, and a caller that composed
    its own sentence would be the drift this helper exists to prevent. ``arg`` names
    the argument the operator actually typed, so the hint says which argument to fix
    instead of pointing at a state root that was fine.

    Both fields carry caller-supplied text -- a name from a command line or a
    working-copy marker, or an argument name -- and this pair goes to stderr, so
    each is rendered through :func:`safe_text`.
    """
    return (safe_text(NAME_REFUSAL.format(name=name, directory=directory)),
            safe_text(NAME_REFUSAL_HINT.format(arg=arg, directory=directory)))


def git(repo: Path, *args: str, _run=subprocess.run) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo``, hardened, under the tree's identity.

    ``_run`` is the call this helper makes, and nothing else: a test that must hand
    this module scripted git answers replaces it and reaches every git call the
    session writers make through here. It is not a knob a caller turns -- the
    writers never pass it.

    Hardening, per call: ``commit.gpgsign=false`` (no signing promise),
    ``core.hooksPath=`` at the null device (no repository hooks),
    ``protocol.ext.allow=never`` (no external transports a remote could name),
    ``core.fsmonitor=false`` (no file-system monitor helper). Global config is NOT
    neutralised: the commit runs under whoever's git config applies to the tree.

    The caller's working directory is removed from the picture, not consulted:
    ``repo`` and every ``args`` entry that names a path are made absolute where they
    are used, so a relative ``--repo`` resolves against the tree named on the command
    line, not wherever the process started. A tree that holds its own ``noni/``
    directory turns a cwd-relative name into a path in a *different* repository, and
    a commit made there is a write nobody asked for.

    A hang is answered, not propagated: the call that cannot finish comes back as
    ``GIT_TIMEOUT_RC``, so every caller classifies it the same way.

    The environment is ``gitenv.child_env()``: every ``GIT_*`` variable is removed
    except the identity, config and transport names on
    ``gitenv.CHILD_ENV_GIT_ALLOWLIST``, so an inherited one cannot send this commit
    to another repository, stage it through a stray index, write its objects to
    another object store or trace itself into a file the caller names. ``--repo``
    alone decides the tree, which is the state-root contract.
    """
    cmd = ["git", "-C", os.path.abspath(str(repo)), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
           "-c", "core.fsmonitor=false", *args]
    try:
        return _run(cmd, capture_output=True, text=True, errors="replace",
                    timeout=GIT_TIMEOUT, env=gitenv.child_env())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


def in_git_worktree(repo: Path) -> bool:
    """True when git can commit in ``repo``: it resolves a git directory.

    The question that decides whether a commit is possible at all, asked with a call
    whose answer is absolute (``--absolute-git-dir``, not ``--git-dir``: the latter
    prints a path relative to the *current* directory once inside the work tree, which
    answers a different question). A tree with no git directory answers no, and the
    caller then behaves as --no-commit: the file is written, the run says so, and
    nothing is claimed as committed.
    """
    return git(repo, "rev-parse", "--absolute-git-dir").returncode == 0


def is_terminal_status(status: str) -> bool:
    """True when ``status`` names a session that has ended (see the set)."""
    return status.strip().lower() in TERMINAL_STATUSES


# The field a session's lifecycle reads. register.py writes it, close.py sets it
# and the census parses it; the writers that read it read it here, so a file whose
# status lines disagree cannot answer 'active' to one writer and 'closed' to another
# (register's empty-value refusal depends on it: see register._read_marked_name).
STATUS_FIELD = "- status:"


def session_status(body: str) -> str | None:
    """The last '- status:' value of ``body``; None when there is none to read.

    No readable value is no answer: an empty one must not be guessed at by a writer
    that acts on the status (register's reuse, claim's terminal refusal). Last
    occurrence wins, the way the census's own parser reads a repeated field: a writer
    needs the one answer a census run on the same bytes would act on, and the same
    bytes handed to two writers must give one verdict.
    """
    for line in reversed(body.splitlines()):
        stripped = line.strip()
        if stripped.startswith(STATUS_FIELD):
            value = stripped[len(STATUS_FIELD):].strip()
            if value:
                return value
    return None


def valid_token(token: str) -> bool:
    """True when ``token`` is safe to put in a commit message after a prefix."""
    return bool(token) and TOKEN_RE.fullmatch(token) is not None


def session_id_rel(session_id: str) -> str:
    """The path a session's file sits at, relative to the state root.

    :func:`writer_name` is the answer a writer commits (and the one it refuses a bad
    id with); this is the same path a caller uses for its write location, its
    ``mkdir`` and its path guards. One spelling, so the directory a writer creates
    and the directory the guard inspects cannot be two different directories.
    """
    return f"{SESSIONS_REL}/{session_id}{SESSION_SUFFIX}"


def file_mode(path: Path) -> int:
    """The mode a file this writer creates should carry: ``path``'s own when it exists
    (replacing a file is no reason to change who can read it), else world-readable as
    the umask allows. mkstemp's 0600 is never written: a session file the census
    cannot read is a broken register."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    umask = os.umask(0o022)
    os.umask(umask)
    return 0o644 & ~umask


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` via a same-directory temp file and os.replace: a crash
    mid-write leaves the old bytes, never a truncated session file. The temp file's
    mode is set before the replace, so what lands is the mode the file should carry,
    not mkstemp's owner-only default."""
    mode = file_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def writer_name(session_id: str) -> str:
    """The name a session's own file carries inside the state root, or ``""``.

    One validated derivation for the four writers, and the strict superset of
    :func:`relative_name`: the id must be a single token (see :func:`valid_token`) and
    must not begin with a ``.`` (a hidden file the census's listing would not report),
    and the name built from it must then answer as a session file to
    :func:`relative_name` itself. A token may still carry a control character, and
    such a name is one this module will not commit (``subprocess`` refuses the argv
    element), so the id step refuses it rather than leaving it to the commit step.

    One function because four writers must stage, print and probe the same string:
    the file write location (``repo / name``), the pathspec, the failure wording and
    the hint are all derived from this one call. A name is what the commit primitive
    takes -- never a path the caller spelled from its own cwd (see
    :func:`stage_and_commit`).
    """
    if not valid_token(session_id) or session_id.startswith("."):
        return ""
    return relative_name(session_id_rel(session_id)) or ""


def relative_name(name: str | PurePosixPath) -> str:
    """``name`` normalised, or ``""`` when it is not a session file inside the root.

    The contract :func:`stage_and_commit` relies on, written down where a caller can
    check it before it writes anything: the name it hands the commit primitive is a
    path *inside* the state root, so it is never absolute and never walks out of the
    root with a ``..`` component. Normalisation is what makes
    ``noni/sessions/../other.md`` and ``./noni/sessions/x.md`` the same judgement as
    a bare ``..``: the name is normalised first, so a ``..`` that lands back inside
    the root is just the file it names, and one that walks out of it arrives at a
    path whose first component is ``..`` -- refused whatever the rest spells.

    Six shapes are refused: an absolute path (git accepts one from outside the
    ``-C`` tree, exits 0 and stages nothing -- the silent nothing-landed the
    primitive must not produce); a ``..`` that walks out of the root; the empty
    name or the root itself; a control character (any Unicode category-C code
    point, :data:`CONTROL_CHARS`) or a lone surrogate, neither of which
    ``subprocess`` can carry as an argument; and a name that is not one ``.md``
    file under :data:`SESSIONS_REL`, because every caller here stages that.

    A backslash is a character of a POSIX file name, not a separator: ``a\\b`` is one
    bizarre filename on this platform and two components on Windows, and the judgement
    made here is the POSIX one. A writer's own id cannot carry one (:func:`valid_token`
    refuses it), so the only name this admits with a backslash is one somebody spelled
    by hand -- and it is refused as an ordinary file name under the root rather than
    silently re-read as a path into a subdirectory.

    Returns ``""`` rather than raising: the caller's one ``if not rel`` has to
    cover every way a path can be wrong, including the refusal this module makes
    on the caller's behalf for a state root it has not looked at yet.
    """
    text = str(name)
    if any(ch in CONTROL_CHARS for ch in text):
        return ""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate is not a name any writer can commit: no argv element
        # and no file write carries it, so the never-raises promise is kept here
        # rather than by whatever ``subprocess`` or ``open`` would have raised.
        return ""
    if text.startswith("/"):
        return ""
    # ``os.path.normpath`` is the collapse: it resolves every ``.`` and ``..``
    # component against the growing path, so a name that walks out of the root
    # arrives at one whose first component is ``..`` and is refused. (A
    # ``PurePosixPath`` does *not* do this -- it keeps ``..`` as a component --
    # and a pathspec that still carries one is a path git refuses as outside the
    # tree, which is a different fault with a different message.) The leading
    # ``/`` test above is not redundant with normpath, which preserves it.
    normalised = PurePosixPath(os.path.normpath(text))
    if not normalised.parts or normalised.parts[0] == "..":
        # '' and '.' both answer with no parts: neither names a file.
        return ""
    posix = normalised.as_posix()
    # ``normpath('noni/sessions/.md')`` is 'noni/sessions/.md' and a name that
    # is the root itself normalises to 'noni/sessions': both are caught here
    # rather than by a comparison against the root.
    if not posix.startswith(f"{SESSIONS_REL}/") or not posix.endswith(SESSION_SUFFIX):
        return ""
    return posix


def stage_and_commit(repo: Path, name: str | PurePosixPath, message: str) -> tuple[bool, str]:
    """Commit exactly ``name`` under ``message``; ``(True, "")`` or ``(False, why)``.

    ``name`` is a path inside the state root -- what :func:`writer_name`
    returns -- and the three steps are the primitive (see the module docstring):
    reset the path's own index entry, add it, then ``commit --only`` that path.
    A file nobody had committed before is committed by these same three steps,
    and a path somebody else had staged is left staged and uncommitted.

    The caller's working directory is not consulted, on either side: the name is
    never resolved against it (which is why it is a name and not a path), and
    ``git -C`` carries an absolute path, so a relative ``--repo`` names the tree
    it named on the command line. The two together are what make ``--repo`` the
    only thing that decides the target repository.

    Three refusals, all ``(False, one noni-worded line)`` rather than a raised
    ``ValueError``, so the caller's one ``if not ok`` covers every way this can fail
    and no writer guards a git call with its own except: the name is not one the
    primitive will commit (:func:`relative_name`'s verdict, in noni's words from
    :data:`NAME_REFUSAL`), the state root is itself a symlink
    (:func:`linked_state_root`'s), or the session file or its directory is no path
    this writer may follow (:mod:`noni._session_paths`). The name half is a
    backstop, and it keeps the never-raises promise ``subprocess`` would break on an
    argv element carrying a NUL or a surrogate.

    Any git refusal also comes back as ``(False, one noni-worded line)``: this
    helper owns no exit code, so the caller names the class of failure and prints
    the hint. The line leads with the cause in noni's own words and ends with what
    git said, sanitised and bounded (see
    :func:`noni._commit_cause.commit_failed`): a writer that stops here has
    already written its file, and the operator who aborts the run reads one
    sentence, not git's status block.
    """
    rel = relative_name(name)
    if not rel:
        # ``safe_text`` again: the name is refused precisely because its bytes
        # are not fit for a terminal or an argv element, so the words about it
        # may not carry them either.
        return False, safe_text(name_refusal(name)[0])
    linked, why = linked_state_root(repo)
    if linked is not None:
        return False, f"cannot commit {rel}: {why}"
    # The writers ask these two before they write; asking them here too means a
    # caller that skipped its own guard cannot drive a link through the primitive.
    if (refused := _session_paths.write_refusal(repo, rel)) is not None:
        return False, f"cannot commit {rel}: {refused[0]}"
    reset = git(repo, "reset", "-q", "--", rel)
    if reset.returncode != 0:
        return False, _detail(reset, f"git reset failed for {rel}")
    added = git(repo, "add", "--", rel)
    if added.returncode != 0:
        return False, _detail(added, f"git add failed for {rel}")
    committed = git(repo, "commit", "-q", "-m", message, "--only", "--", rel)
    if committed.returncode != 0:
        return False, _failure_line(repo, committed, rel)
    return True, ""


def linked_state_root(repo: Path) -> tuple[Path | None, str]:
    """``(link, why)`` when ``repo`` is itself a symlink, else ``(None, "")``.

    The one place the rule is written, so the refusal a caller makes before it
    touches the tree and the one the commit primitive makes cannot drift apart. The
    answer is rendered through :func:`safe_text`: the path is operator-supplied text
    and the pair is printed to stderr.

    ``git`` works on the resolved path of the tree ``-C`` names, while a writer's own
    path arithmetic stays unresolved -- it joins the state root to a name inside it
    rather than resolving a file it has not created yet. A state root that is itself
    a link is where the two readings disagree: the resolved path is where
    :mod:`noni._marker` would keep the working-copy marker, and what anyone auditing
    the commit later has to match against a path nobody named. So the writer refuses
    and names the real path rather than following the link. A project directory
    *reached through* a link is not this state: only the ``--repo`` component itself
    is examined, never the cwd it is read against.
    """
    absolute = os.path.abspath(str(repo))
    if not (Path(absolute).is_symlink() or os.path.islink(str(repo))):
        return None, ""
    return Path(absolute), safe_text(
        f"--repo {repo} is a symlink to {os.path.realpath(absolute)}: "
        "the session writers refuse a state root that is a symlink")


def _failure_line(repo: Path,
                  result: subprocess.CompletedProcess[str],
                  rel: str) -> str:
    """The default commit-failure namer: the classifier's line, imported when asked.

    Deferred to the call rather than bound at import: ``_commit_cause`` asks git
    through :func:`git` here, so a module-level reference would be taken mid-import.
    """
    from . import _commit_cause
    return _commit_cause.commit_failed(repo, result, rel)


def _detail(result: subprocess.CompletedProcess[str], headline: str) -> str:
    """One headline naming what git said about a failed call, sanitised."""
    return f"{headline}: {_said(result) or 'no reason given'}"


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """What git said about a failed call, sanitised, bounded, on one line.

    The same flattening :mod:`noni._commit_cause` applies to a commit failure's
    quotation: these bytes are the tail of one report line, and a multi-line echo
    reads as a raw status dump rather than as a quotation in a sentence.
    """
    said = _safe(result.stderr) or _safe(result.stdout) or ""
    return " ".join(said.split())


def _safe(text: str, limit: int = GIT_OUTPUT_LIMIT) -> str:
    """git's words, sanitised, or ``""`` when nothing legible remains.

    ``limit`` is the module's own rendering bound, and the one reason the constant is
    re-exported from :mod:`noni._safe_text` rather than referenced there: the push
    loop and the classifier echo bounded shares of git's output through here.
    """
    cleaned = safe_text((text or "").strip(), limit)
    return "" if cleaned.strip() == "" else cleaned


# :mod:`noni._session_push` (the push loop) and :mod:`noni._session_rebase_state`
# (the rebase probe) import these primitives from here. A re-export would be a
# cycle, so callers import those modules directly.

