"""The verb list is one constant, and both refusals of the verb slot print it.

Two refusals answer the same mistake -- a command line whose verb is missing or is not
one of the four -- and they live in different modules: the parser's
``VerbedParser.error`` (``item_cli.py``) names the verbs when the slot is empty, and the
writer's unknown-verb refusal (``item.py``) names them when it holds a word that is not
one. Each once spelled its own list from ``VERBS``, which is exactly the pair that drifts
-- a fifth verb added to ``VERBS`` would appear in one refusal and not the other, and the
operator's fix line would then be a sentence about a set the parser does not accept.

So one constant (``item_cli.VERBS_JOINED``) is read by both, and this suite pins that
the two runs name the same four words and that the constant is those words, read from the
product rather than copied here.
"""

from __future__ import annotations

from item_writer_fixtures import repo, run_item

VERBS = ("add", "list", "drop", "promote")


def _joined_from_the_product() -> str:
    """The one list the product owns, read from the module rather than retyped."""
    from noni import item_cli

    assert item_cli.VERBS_JOINED == ", ".join(VERBS), item_cli.VERBS_JOINED
    assert ", ".join(item_cli.VERBS) == item_cli.VERBS_JOINED
    return item_cli.VERBS_JOINED


def test_the_missing_verb_refusal_names_the_one_verb_list(tmp_path):
    """``item.py --repo R`` with no verb prints the shared list, not a copy of it."""
    _joined_from_the_product()
    tree = repo(tmp_path)
    proc = run_item(tree)
    assert proc.returncode == 2, proc.stderr
    joined = proc.stdout + proc.stderr
    assert ", ".join(VERBS) in joined, joined
    for verb in VERBS:
        assert verb in joined, f"{verb} is not named: {joined}"


def test_the_unknown_verb_refusal_names_the_same_list(tmp_path):
    """Both refusals of the verb slot answer with one set, or this case fails."""
    joined_expected = _joined_from_the_product()
    tree = repo(tmp_path)
    missing = run_item(tree)
    unknown = run_item(tree, "delete", "idea-0001")
    assert missing.returncode == 2 and unknown.returncode == 2
    for name, proc in (("missing", missing), ("unknown", unknown)):
        joined = proc.stdout + proc.stderr
        assert joined_expected in joined, f"{name}: {joined}"
    # One set, not two: whatever each refusal spells, the two spell the same thing.
    for verb in VERBS:
        assert verb in (missing.stdout + missing.stderr), verb
        assert verb in (unknown.stdout + unknown.stderr), verb
