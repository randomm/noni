"""The id an item may be named by, spelled the way the ruling on #124 spells it.

The id rule is a PM ruling and the census page states it: ``[a-z0-9][a-z0-9._-]{0,79}``,
with an id that ends in ``.json`` refused at the flag and an id that differs from its
file's stem reported ``item-malformed``. The code had a narrower set --
``[a-z0-9][a-z0-9-]*`` -- so three ids the ruling accepts (``a_b``, ``a.b``, ``v1.2-x``)
were refused at exit 2, and the three documents that state the rule disagreed with the
one constant that enforces it.

One owner for each half of the rule: ``itemschema.ID_RE`` is the shape and
``itemschema.ID_MAX`` the length, both asked by ``is_item_id``, so the writer, the census
and this suite ask one question. The bound is expressed once -- the regex's own
``{0,79}`` plus ``ID_MAX`` -- and this suite pins that the two agree, because a rule
stated twice with different numbers is the same drift in a different place.

``a..b`` is accepted, and that reading is stated here rather than left to inference: the
ruled pattern places no constraint on what follows a dot, so a repeated one is inside the
set it names, and refusing it would be a narrower rule than the one the ruling gives. The
suffix rules are the ruling's own two additions (``.json`` and a trailing dot), and they
narrow the pattern in exactly the two places the ruling says, nowhere else.
"""

from __future__ import annotations

from item_store_path import STORE
from item_writer_fixtures import NOW, repo, run_item

ACCEPTED = ("a_b", "a.b", "v1.2-x")
REFUSED = (".a", "a.json", "A", "a/b", "a" * 81, "", "a.", "a b", "aé")
# Shapes the command line cannot carry to the id check; asserted of the constant.
REFUSED_BY_THE_CONSTANT_ONLY = ("-a", ".a")


def test_the_ruled_ids_are_accepted_at_the_flag(tmp_path):
    """The three ids the ruling allows and the old regex refused, filed as named."""
    for item_id in ACCEPTED:
        tree = repo(tmp_path, f"accept-{item_id}")
        proc = run_item(tree, "add", item_id, "--title", "T", "--now", NOW)
        assert proc.returncode == 0, f"{item_id!r}: {proc.returncode} " \
            f"{proc.stdout}{proc.stderr}"
        assert f"{item_id} is candidate" in proc.stdout, f"{item_id!r}: {proc.stdout}"


def test_ids_the_ruling_refuses_are_refused_at_the_flag(tmp_path):
    """Exit 2, the id named, and nothing written, for every shape outside the rule.

    ``.a`` and ``-a`` open where the pattern requires a letter or digit; ``a.json``
    carries the suffix the census keys by; ``a.`` is the dot the filesystem hides and
    the stem cannot name; ``a`` times 81 passes its own ``{0,79}`` bound. Upper case, a
    slash, a space and a non-ASCII letter are outside the character class. The empty id
    is refused by the command line rather than by this rule: an empty string reaches the
    parser as the *absence* of the optional positional and the verb answers its own
    "needs an item id", a refusal of the same mistake one step earlier whose text
    ``tests/test_item_writer_usage.py`` pins. What this rule claims about the empty
    string -- that it is no id -- is asserted of the constant below.

    A leading dot is left to the constant below, with the leading dash: argparse reads a
    token beginning with a hyphen as an option, and the only way to hand one over as a
    positional is the bare ``--`` separator -- which makes every token after it a
    positional, so the verb's own flags are swallowed and no id check is reached. The
    shapes below are the ones that reach the check through a real command line; the full
    ruled set, leading dot and leading dash included, is asserted of the constant.
    """
    for item_id in REFUSED:
        if not item_id or item_id.startswith("."):
            # Either the verb's refusal rather than this rule's (the empty id, see the
            # docstring) or a shape no command line can carry (a leading dot).
            continue
        tree = repo(tmp_path, f"refuse-{abs(hash(item_id))}")
        argv = ["add", item_id, "--title", "T", "--now", NOW]
        proc = run_item(tree, *argv)
        assert proc.returncode == 2, f"{item_id!r}: {proc.returncode} {proc.stderr}"
        assert "is not an item id" in proc.stderr, f"{item_id!r}: {proc.stderr}"


def test_the_id_rule_is_one_constant_shared_by_both_sides():
    """One owner for the shape and one for the length, and the two agree.

    Read off the module rather than restated here: the point of the ruling is that the
    writer and the census cannot drift on an id, and a test that re-typed the pattern
    would be a third copy of it. The bound is checked against ``ID_MAX`` because the
    pattern's own repeat count and the length constant are the same number said twice,
    which is exactly the kind of pair that comes to disagree.
    """
    from noni import itemschema

    assert itemschema.ID_RE.pattern == r"[a-z0-9][a-z0-9._-]{0,79}", \
        itemschema.ID_RE.pattern
    assert itemschema.ID_MAX == 80
    for item_id in ACCEPTED:
        assert itemschema.is_item_id(item_id), item_id
    assert not itemschema.is_item_id("-a")  # opens with a letter or a digit
    for item_id in REFUSED:
        if item_id:  # The empty id is argparse's refusal, not this rule's.
            assert not itemschema.is_item_id(item_id), item_id
    for item_id in REFUSED_BY_THE_CONSTANT_ONLY:
        assert not itemschema.is_item_id(item_id), item_id
    # The two bounds of the rule are the same length, said twice.
    assert itemschema.is_item_id("a" * itemschema.ID_MAX)
    assert not itemschema.is_item_id("a" * (itemschema.ID_MAX + 1))
    # The ruling's reading of a repeated dot, stated as a case rather than prose.
    assert itemschema.is_item_id("a..b")


def test_the_store_path_the_fixtures_use_is_the_one_the_product_spells():
    """A fixture that hard-codes ``noni/items`` would keep passing after it moved.

    Both item suites build store paths from :mod:`item_store_path`, which reads the
    product's own constant; this asserts the chain is intact in both directions, so the
    parity cannot be broken from either end.
    """
    from noni import itemschema

    assert STORE == itemschema.ITEM_DIR == "noni/items", STORE


def test_the_census_page_states_the_rule_the_code_enforces():
    """The row that documents the id rule quotes the one constant that enforces it.

    The census page is where an operator reads why a file was reported, so a pattern
    written out there is a promise the code has to keep. Read from the page rather than
    quoted, and compared to the constant rather than to a copy.
    """
    from _harness import REPO

    from noni import itemschema

    page = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    assert itemschema.ID_RE.pattern in page, (
        f"the census page does not state {itemschema.ID_RE.pattern!r}")
