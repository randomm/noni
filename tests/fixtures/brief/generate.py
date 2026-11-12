#!/usr/bin/env python3
"""Write the ``noni brief`` fixture tar from the state root the brief reads.

This is the builder of ``tests/fixtures/brief.tar``, the committed repository that
``tests/test_brief_readonly.py``, ``tests/test_brief_now.py``, ``tests/test_brief_page.py`` and
``tests/test_brief_limits.py`` unpack. The tar is the artifact and this script is its specification;
``tests/test_brief_fixture.py`` regenerates the archive and compares it member by member against the
committed one, so the two cannot drift apart while the suite still passes.

The repository is built from nothing rather than shelled out to ``git``. A real ``git init`` plus a
sequence of commits would have been the obvious way to get a fixture with history, and it would have
made this file a quarter its size. It was rejected because every step of that recipe reads the host:
``git init`` drops ``.git/hooks`` samples, ``git commit`` refuses without ``user.name``/``user.email``
or takes them from whichever config the building machine happens to have, and the resulting object
ids and index bytes depend on the version of git that ran. The brief is the one surface of noni that
must render identically wherever the suite runs, and a fixture whose bytes are a function of the host
that built it is a source of flakes wearing a fixture's clothes. So the objects -- blobs, trees, the
commit chain, the index, the refs -- are constructed here with ``hashlib`` and ``zlib`` alone, and the
only host state that reaches the archive is what the caller hands in.

What the state root holds is the fixture's whole reason to exist, and it is shared with the tests
rather than repeated. The content -- the eleven order entries, the intent
file and the one decided record, and the instant
the suite briefs the tree at -- all of it comes from ``tests/brief_fixtures.py``, the module the brief
cases already read. The builder and the assertions therefore answer to one table: a change to a title,
a stamp or the citation is visible to both at once, which is the drift that would otherwise let a
green run be about a fixture nobody described.

Run it with no argument to print a description of the tree, or with an output path to write it::

    python tests/fixtures/brief/generate.py
    python tests/fixtures/brief/generate.py tests/fixtures/brief.tar

The git plumbing -- objects, trees, commits, the reflog and the index -- lives in ``git_bytes.py``
beside this file; this module answers only what the fixture contains.
"""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

# The builder is run as a script, so ``sys.path`` starts at its own directory rather than at the repo
# root the brief cases import from. The tests directory is added rather than assumed: it holds the
# module whose constants the fixture's content is defined in, and the builder is useless without it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import git_bytes
from brief_fixtures import (
    CONFIRMED,
    NOW,
    OPEN_RECORD_ID,
    ORDER_WHY,
    PURPOSE_LINES,
    RECORD_ID,
    SUPERSEDED_ID,
)

from noni import ledger_schema, orderschema

# The instant every file and tar member of the fixture carries. A fixed stamp, not the building
# clock: a tar whose mtimes moved with each run could not be compared member by member against the
# committed copy, which is the check that keeps this script and ``brief.tar`` from drifting.
TAR_MTIME = 1_793_000_000             # 2026-10-27T00:00:00Z, the same instant the suite briefs at

# The three commit subjects, in the order they are committed. Deliberately narrow: what the census's
# ``intent`` class reads is the subject of the last commit that touched the intent file, and the brief's
# citation column reports the record that commit cites. A history built from commits the census cannot
# classify -- a merge, or a commit whose subject names no record -- would let the fixture report a
# citation the tool cannot see, and the case would be about the fixture instead of about the tool.
COMMIT_SUBJECTS = [
    "noni: seed the direction layer",
    "noni: order the eleven queued issues",
    f"intent: {RECORD_ID}",
]

# Modes as git's own octal constants, written as numbers rather than literals scattered through the
# builders: the same 0o100644 has to appear in a tree entry, in an index entry and on every tar member,
# and a mode that disagreed between two of the three is a repository git reads as corrupt.
FILE_MODE = 0o100644                  # a regular file, as a tree entry records it
TREE_DIR_MODE = "040000"              # a directory, as a tree entry spells it in ASCII octal
TAR_DIR_MODE = 0o755                  # a directory, as a tar member records it
TAR_FILE_MODE = 0o644                 # a plain file, with no execute bit anywhere

# Directories the tar must carry even when no file sits inside them. The empty ones are what ``git
# init`` creates and what several of git's own write paths expect: ``git commit`` from a case needs
# ``refs/heads``, and a repository that reads perfectly well and then cannot take a commit is a
# fixture defect, not a product one.
REQUIRED_DIRS = (".git", ".git/branches", ".git/hooks", ".git/info", ".git/objects",
                 ".git/objects/info", ".git/objects/pack", ".git/refs", ".git/refs/heads",
                 ".git/refs/tags")


# -----------------------------------------------------------------------------------------------
# The fixture's content, as one answer the brief cases and the builder both read
# -----------------------------------------------------------------------------------------------

def _epoch(iso_utc: str) -> int:
    """The ``Z``-suffixed instant as whole seconds since the Unix epoch.

    ``datetime.fromisoformat`` gains the ``Z`` suffix in 3.11 and this suite runs on 3.10, so the
    suffix is cut and the offset stated instead of relying on the parser's tolerance. Whole seconds
    only, because every stamp in the fixture is minute-rounded.
    """
    from datetime import datetime, timezone

    return int(datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc).timestamp())


def _identity() -> str:
    """The one author/committer line every commit of the fixture carries.

    A fixed identity rather than a host one: the fixture is byte-comparable against the committed tar,
    and git writes the ident straight into every commit object.
    """
    return f"noni fixture <fixture@noni.invalid> {_epoch(NOW)} +0000"


# The instant the decided record was decided, on the record's own date so the id's prefix and the
# field agree: the ledger class compares them, and a record whose date contradicts its id is a row.
RECORD_STAMP = f"{RECORD_ID[:10]}T00:00:00Z"

# How many entries the order holds, one per issue, in the order the operator set them.
# The ``top 10`` block shows the first ten and drops the eleventh: the count sits just past
# the cap on purpose, so the committed tree exercises the budget's truncation as well as a
# list that fits.
ORDER_ENTRIES = 11


def order_document() -> dict:
    """``noni/direction/order.json``: eleven issue positions, none of them stale.

    Built from the entry shape :mod:`noni.orderschema` documents -- ``{issue, decision,
    confirmed}``, and ``why`` on the head of the queue -- rather than from invented keys. The
    brief renders this file through :func:`noni.orderstate.read_order`, which refuses a document
    carrying a field the artifact never declared, so a fixture that wrote ``ref`` and a
    top-level ``confirmed`` printed ``not readable`` and turned ten page cases into a fixture
    investigation.

    Every entry cites the one committed record and carries
    :data:`tests.brief_fixtures.CONFIRMED`, a stamp inside the census's staleness window
    of the brief instant: an entry citing nothing, or confirmed too long ago, is a census
    row the verdict line would then have to report.

    The head of the queue carries :data:`tests.brief_fixtures.ORDER_WHY` and nothing else does,
    which is what puts both shapes of the ``top 10`` row in the committed tree: the position,
    the issue and the record that set it, and the same row with the operator's reason after a
    mark. A fixture whose every entry carried a reason, or none at all, would leave half the
    row's arms to a planted variant no other case reads.

    The count is one past the block's ten-row cap, which is what makes the committed tree
    hold both halves of the budget: ten rows that print and one the page withholds.
    """
    entries = [{"issue": number, "decision": RECORD_ID, "confirmed": CONFIRMED}
               for number in range(1, ORDER_ENTRIES + 1)]
    entries[0][orderschema.WHY_FIELD] = ORDER_WHY
    return {"schema": orderschema.ORDER_SCHEMA, "entries": entries}


# The two extra records the ledger holds beside the committed one live in
# :mod:`tests.brief_fixtures` beside :data:`~tests.brief_fixtures.RECORD_ID`: the builder reads
# their ids and the page cases read the same two names, so a rename cannot leave the committed
# tar and the assertions about it describing different files.


def record_documents() -> dict[str, dict]:
    """Every record file of the ledger, as ``{record id: document}``.

    The committed record beside the pair that exercises the block's two filters. The
    brief's ``recent decisions`` block prints the records whose own ``status`` is ``decided``
    and nothing else, so a fixture holding one decided record proves only that a row can be
    built: the superseded record is the case that a closed chain stays off the screen, and the
    open one is the case that a question the operator has not answered is not printed as an
    answer either.

    The three are one timeline: the superseded record is decided, then superseded by the
    committed one, so the chain the census's ``ledger-chain`` class walks is intact and no new
    census row joins the verdict line the read-only cases assert byte for byte. An ``open``
    record is what :func:`noni.ledger_schema.status_for` makes of a question carrying a
    ``null`` answer, so its ``status`` is written with the writer's own rule rather than typed.
    """
    records = {RECORD_ID: record_document()}
    records[SUPERSEDED_ID] = _superseded_document()
    records[OPEN_RECORD_ID] = _open_document()
    return records


def record_document() -> dict:
    """``noni/decisions/<record-id>.json``: the one decided record the fixture commits.

    The eight fields :mod:`noni.ledger_schema` requires, with :data:`~noni.ledger_schema.STATUS_DECIDED`
    and no successor. The status is what makes the record live to the ledger class: a record left
    ``open`` or marked ``superseded`` is invisible to the citation check, and the fixture's cited entry
    would come back uncited with a ``ledger-record`` row beside it. ``supersedes`` is ``None`` because a
    fixture holding one record has no chain, and the ledger census walks.

    ``questions`` carries one answered question: an unanswered question makes the record ``open`` by
    the ledger's own rule (:func:`noni.ledger_schema.status_for`), which is the difference between a
    record the census counts and one it reports.
    """
    return {"id": RECORD_ID, "date": RECORD_STAMP,
            "asked_by": "developer",
            "questions": [{"id": "q1", "text": "What should the run brief first?",
                           "options": ["the three newest", "the oldest"], "answer": "the three newest"}],
            "by": "Replay", "scope": "the brief surface",
            "status": ledger_schema.STATUS_DECIDED, "supersedes": None}


# The ids of the two records the block must never print are declared in
# :mod:`tests.brief_fixtures` beside :data:`~tests.brief_fixtures.RECORD_ID`, and this builder
# writes them from there: one record the committed one closed, and one whose question no operator
# answered. Named there rather than here because the page cases read the same two names off the
# same module, so a rename cannot leave the committed tar and the assertions about it describing
# different files.


def _superseded_document() -> dict:
    """A decided record the committed one supersedes: the closed end of one chain.

    Dated before :data:`~tests.brief_fixtures.RECORD_ID` and marked
    :data:`~noni.ledger_schema.STATUS_SUPERSEDED` with its ``supersedes`` naming the record that
    closed it, which is the shape the ledger's own chain rules expect of a superseded record and
    the reason no ``ledger-chain`` row arrives. Being the older record it is also the one a
    newest-first block would print had it stayed live, which is what makes its absence the
    assertion it is.
    """
    return {"id": SUPERSEDED_ID, "date": f"{SUPERSEDED_ID[:10]}T00:00:00Z",
            "asked_by": "developer",
            "questions": [{"id": "q1", "text": "Brief the oldest decisions first?",
                           "options": ["yes", "no"], "answer": "yes"}],
            "by": "Replay", "scope": "the brief surface",
            "status": ledger_schema.STATUS_SUPERSEDED, "supersedes": None}


def _open_document() -> dict:
    """A chain-root record whose question carries no answer, so its status is ``open``.

    The status is derived by :func:`noni.ledger_schema.status_for` from the unanswered id rather
    than written as a word: an ``open`` record is exactly what the writer produces for a question
    nobody answered, and a fixture that typed the status by hand could state a combination no
    writer can build.
    """
    questions = [{"id": "q1", "text": "Which instant does the suite brief at?",
                  "options": ["the fixture's", "the clock"], "answer": None}]
    return {"id": OPEN_RECORD_ID, "date": f"{OPEN_RECORD_ID[:10]}T00:00:00Z",
            "asked_by": "developer", "questions": questions,
            "by": "Replay", "scope": "the brief surface",
            "status": ledger_schema.status_for(["q1"]), "supersedes": None}


def intent_text() -> str:
    """``noni/direction/intent.md``: the four required sections, the ``## Purpose`` body clip-long.

    The sections are ``intentschema.REQUIRED_SECTIONS`` in the order that schema requires, with the one
    ``Last-confirmed:`` line it demands. An intent missing a section, or its stamp, is refused by the
    writer and reported by the census, and the brief's purpose block then prints ``not readable`` -- so
    an fixture that invented its own headings (a ``## Now``, a ``## Boundaries``) was testing the
    refusal path while looking like it tested the page.

    The ``## Purpose`` body runs past the brief's twenty-line clip so the clipped case and the
    un-clipped one differ in the ellipsis row alone, which is the pair that pins the budget down. The
    lines are the shared :data:`tests.brief_fixtures.PURPOSE_LINES`, the table the page test's clip
    arithmetic reads too, and each is a sentence rather than filler: a body of filler would survive the
    clip being wrong by a line.
    """
    tail: list[str] = []
    for name, filler in (("Principles", "- the census is the arbiter"),
                         ("Never", "- no daemon, no database"),
                         ("Ask first", "- anything that costs money")):
        tail += [f"## {name}", filler]
    return "\n".join(["# Intent", f"Last-confirmed: {RECORD_ID[:10]}",
                      "## Purpose", *PURPOSE_LINES, *tail]) + "\n"


def documents() -> dict[str, bytes]:
    """Every file of the work tree, as ``{repository-relative path: bytes}``.

    The one answer to what the fixture holds: the tar is written from this and the test reads it, so a
    file present in one and not the other is a bug in this file rather than a disagreement between two
    lists.

    No session register. The stall cases need to *make* the commit that carries a register file, at an
    instant they choose, so the file has to be absent from the committed state: a fixture that held it
    would leave :func:`tests.brief_fixtures.commit_at` with nothing to stage and the case would assert
    about a history it never moved. The bytes the cases write are the ones
    :func:`tests.brief_fixtures.session_body` states, and that function is where the shape the sessions
    census reads lives.

    The documents are serialised by the writers that own their format --
    :func:`noni.orderschema.order_bytes` -- because the reader insists on its own
    canonical bytes: a hand-formatted order is refused as non-canonical, and the page then
    reports ``not readable`` where it should report the fixture. Going through the writer is also what
    keeps the fixture honest about itself: were a field to be renamed in the schema, the builder would
    stop compiling rather than quietly write a file the tool refuses.
    """
    tree: dict[str, object] = {
        "noni/decisions": {f"{record_id}.json": document
                           for record_id, document in record_documents().items()},
        "noni/direction": {"intent.md": intent_text(), "order.json": order_document()},
    }
    files: dict[str, bytes] = {}
    for directory, entries in tree.items():
        for name, payload in entries.items():
            files[f"{directory}/{name}"] = _serialise(f"{directory}/{name}", payload)
    return files


def _serialise(rel: str, payload: object) -> bytes:
    """One document as the bytes the state root holds, rendered by whoever owns its format.

    ``rel`` selects the writer: the order goes to :func:`noni.orderschema.order_bytes`,
    and anything else (the ledger record, the intent's prose)
    takes the documented canonical form -- two-space indent and one trailing newline for JSON, the text
    as written for Markdown. The dispatch is by path rather than by sniffing the document's keys so a
    renamed field cannot route a document to the wrong writer and have it come back well-formed.
    """
    if isinstance(payload, str):
        return payload.encode("utf-8")
    if rel.endswith(orderschema.ORDER_REL):
        return orderschema.order_bytes(payload)
    import json

    return (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


# -----------------------------------------------------------------------------------------------
# The tar: the committed artifact, written from the content above and the plumbing beside it
# -----------------------------------------------------------------------------------------------

def _reflog(rows: list[tuple[str, bytes]]) -> bytes:
    """The reflog of the one branch: one line per commit, the transaction log git keeps.

    ``rows`` is the commit list from :func:`git_bytes.commits`, which is the only caller that has it --
    passing the commits in rather than taking the whole object list is what keeps the positional link to
    :data:`COMMIT_SUBJECTS` honest, since a reflog line states its commit's subject. Carried because a
    reader of the fixture's history (``git log -g``, or a tool checking that a commit was made rather
    than faked) should find the same three commits in the order the refs name them.
    """
    previous = "0" * 40
    lines = []
    for index, (object_id, _payload) in enumerate(rows):
        action = "commit (initial)" if index == 0 else "commit"
        lines.append(f"{previous} {object_id} {_identity()}\t"
                     f"{action}: {COMMIT_SUBJECTS[index]}\n")
        previous = object_id
    return "".join(lines).encode("ascii")


def _config() -> bytes:
    """The repository's ``.git/config``: the four core settings, and nothing host-specific.

    No ``user.*`` (the builder supplies identity in the object itself), no remotes, no hooks path:
    a config naming anything about the building machine is the thing this fixture exists not to carry.
    """
    return ("[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n"
            "\tbare = false\n\tlogallrefupdates = true\n").encode("ascii")


def members() -> list[tuple[str, int, bytes]]:
    """Every member of the tar as ``(name, mode, bytes)``, directories included.

    The one list the archive is written from. Both forms of the ref are carried -- ``packed-refs`` and
    ``info/refs`` -- because the fixture's refs are packed rather than loose and a git reads either;
    the ``HEAD`` file is the loose half, pointing at the branch the two listings resolve. The empty
    ``refs/heads`` and ``refs/tags`` directories are carried because a real ``git init`` creates them
    and several of git's own write paths expect them to exist: a repository that reads perfectly well
    and then fails to ``git commit`` the first time a case tries one is a fixture defect, not a
    product one.
    """
    objects, blob_ids = git_bytes.git_objects(documents(), FILE_MODE, _identity, COMMIT_SUBJECTS)
    commits_rows = git_bytes.commits(documents(), FILE_MODE, _identity, COMMIT_SUBJECTS)
    branch = git_bytes.BRANCH
    head_commit = commits_rows[-1][0]
    log = _reflog(commits_rows)
    rows: list[tuple[str, int, bytes]] = [
        (".git/HEAD", TAR_FILE_MODE, f"ref: {branch}\n".encode("ascii")),
        (".git/config", TAR_FILE_MODE, _config()),
        (".git/description", TAR_FILE_MODE, b"Unnamed repository\n"),
        (".git/packed-refs", TAR_FILE_MODE,
         ("# pack-refs with: peeled fully-peeled sorted \n"
          f"{head_commit} {branch}\n").encode("ascii")),
        (".git/info/refs", TAR_FILE_MODE, f"{head_commit}\t{branch}\n".encode("ascii")),
        (".git/logs/HEAD", TAR_FILE_MODE, log),
        (f".git/logs/{branch}", TAR_FILE_MODE, log),
        (".git/index", TAR_FILE_MODE, git_bytes.index(blob_ids, FILE_MODE)),
    ]
    rows += [(f".git/objects/{object_id[:2]}/{object_id[2:]}", TAR_FILE_MODE, payload)
             for object_id, payload in objects]
    rows += [(rel, TAR_FILE_MODE, data) for rel, data in sorted(documents().items())]
    return _with_directories(rows)


def _with_directories(rows: list[tuple[str, int, bytes]]) -> list[tuple[str, int, bytes]]:
    """The member list plus one directory entry for every prefix of every name.

    Directories first, then the files in the order they were given. A tar says "directory" with an
    entry of its own; ``tarfile.extractall`` would create the parents regardless, and carrying them is
    what lets ``tar -tvf`` show the shape of the repository without unpacking it. :data:`REQUIRED_DIRS`
    is added to the set, since an empty directory is a prefix of nothing.
    """
    prefixes = {"/".join(name.split("/")[:index + 1])
                for name, _mode, _payload in rows
                for index in range(len(name.split("/")) - 1)}
    directories = [(prefix, TAR_DIR_MODE, b"") for prefix in sorted(prefixes | set(REQUIRED_DIRS))]
    return directories + rows


def build_tar(target: Path) -> dict[str, int]:
    """Write the fixture tar at ``target`` and report what it holds.

    The tar is the committed artifact: ``tests/fixtures/brief.tar``, unpacked into a case's
    ``tmp_path`` by :func:`tests.brief_fixtures.plant_brief_tree`. It carries a working repository
    rather than a bare work tree because the census answers questions about history -- whether the
    intent cites a record, whether a session has gone stale -- and answers them through
    ``git -C <top>``. It cannot travel as a directory for the same reason: an index or a pack is binary
    and the purity suites read every file under ``tests/fixtures/`` as UTF-8.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    rows = members()
    with tarfile.open(target, "w") as archive:
        for name, mode, payload in rows:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = mode
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = TAR_MTIME
            info.type = tarfile.DIRTYPE if mode == TAR_DIR_MODE else tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(payload))
    return {"members": len(rows), "files": len(documents()),
            "objects": len(git_bytes.git_objects(documents(), FILE_MODE, _identity,
                                                 COMMIT_SUBJECTS)[0])}


def main(argv: list[str]) -> int:
    """Build the fixture at the given path, or describe the tree when given no path.

    ``generate.py`` alone prints the shape of what it would build -- the counts -- so a
    reader can see the fixture without unpacking a tar. ``generate.py OUT/brief.tar``
    writes it.
    """
    if len(argv) > 1:
        counts = build_tar(Path(argv[1]))
        print(f"wrote {argv[1]}: {counts['files']} files, {counts['objects']} git objects, "
              f"{counts['members']} tar members")
        return 0
    print(f"{len(documents())} files, {len(COMMIT_SUBJECTS)} commits, briefed at {NOW}")
    print(f"{ORDER_ENTRIES} order entries citing {RECORD_ID}")
    print(f"{len(record_documents())} decision records, 1 of them live to the brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
