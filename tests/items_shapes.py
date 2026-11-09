"""The shared malformed-shape table: the shapes the census reports and the writer refuses.

``item.py`` refuses an artifact it would have to overwrite (exit 4) and the census
reports the same artifact as ``item-malformed`` (exit 52). The two rule sets are
written twice on purpose, one reader in the writer and one in the arbiter, which is
exactly how they drift: a shape one side accepts and the other refuses is a file
nobody notices has rotted, because the writer will not touch it and the census says
nothing.

So the table lives here and both suites read it:
``tests/test_item_writer_artifact.py`` drives every shape through the writer and the
census, and ``tests/test_census_items_group.py`` drives every shape through the
census. Adding a rule to one side without the other fails here, not in the field.

Each row carries a ``needle``: a fragment that must appear in the refusal or the
row's message. The two sides word the same defect differently, so a needle is a word
the two share rather than a full sentence.

The builders are not here. ``tests/items_fixtures.py`` owns the repo, the store
writes and the census runner, and this module only composes bodies, so there is one
way to put a file in the store and both suites see it.
"""

from __future__ import annotations

import json

# The documented field order, read from the product's own declaration: the fixture's
# one permitted reach into the module under test, because a fixture that restated the
# order would keep passing when the schema's order changed.
from noni.itemschema import ITEM_FIELDS

# A created stamp inside the default 30-day window of the harness's NOW, and one well
# outside it, so a shape that is otherwise well formed is never also reported stale.
FRESH = "2026-10-26T00:00:00Z"
OLD = "2026-01-01T00:00:00Z"

# A live record id every shape can cite: a dropped item must cite a decision, so a
# shape under test needs a value that is not itself the defect. The fixtures' repo
# holds a committed record of this name.
BASELINE_ID = "2026-10-01-baseline"


def item_body(item_id: str = "idea-0001", title: str = "Say hello first",
              status: str = "candidate", issue=None, decision=None, why=None,
              created: str = FRESH, schema: str = "noni.item/1") -> dict:
    """One well-formed item, with only the fields that status owes.

    Optional fields are left out rather than set to null, which is the other half of
    the shape: an absent ``why`` and a ``why`` of null are different documents and the
    schema permits only the first.
    """
    body: dict = {"schema": schema, "id": item_id, "title": title,
                  "status": status, "created": created}
    if issue is not None:
        body["issue"] = issue
    if decision is not None:
        body["decision"] = decision
    if why is not None:
        body["why"] = why
    return body


def canonical(body: dict) -> str:
    """The canonical bytes for one item: documented key order, two-space indent, one newline.

    Hand-written here rather than taken from the product's renderer: this module is
    imported by the suites that test that renderer, and a shape table that could not
    be built without it would make every row of the table depend on the thing it is
    checking.

    The key order is the schema's declared order, **not** ``sort_keys``: a table that
    sorted would hand every well-formed body bytes the writer refuses as
    non-canonical, and each case would pass for the wrong reason (a refusal whose
    message names the indent rather than the field it was planted to test).
    """
    document = {field: body[field] for field in ITEM_FIELDS if field in body}
    return json.dumps(document, indent=2) + "\n"


def malformed_shapes() -> list[tuple[str, dict, str]]:
    """The shapes both sides must refuse, as ``(name, body, needle)`` triples.

    One row per rule of ``itemschema.problems``, plus the rules the schema and the
    census share (a ``schema`` that is not this one's, and an ``id`` that is not the
    file's own name). Built by mutation from one clean document, so a row tests the
    field it names and nothing else: a row that hand-wrote its own body could quietly
    carry a second defect and be reported by the wrong rule.
    """
    rows: list[tuple[str, dict, str]] = []

    def bad(name: str, mutate, needle: str) -> None:
        body = item_body()
        mutate(body)
        rows.append((name, body, needle))

    def drop(key: str):
        def mutate(body: dict) -> None:
            del body[key]
        return mutate

    def set_fields(**fields):
        def mutate(body: dict) -> None:
            body.update(fields)
        return mutate

    def dropped(body: dict) -> None:
        """Make the document a well-formed dropped item, the base of its own rows."""
        body["status"] = "dropped"
        body["decision"] = BASELINE_ID
        body["why"] = "out of scope for the release"

    bad("schema missing", drop("schema"), "schema")
    rows.append(("schema is a foreign schema", item_body(schema="noni.item/2"),
                 "schema"))
    rows.append(("schema is not a string", item_body(schema=1), "schema"))
    rows.append(("id is not a slug", item_body(item_id="Idea One"), "id"))
    rows.append(("id is empty", item_body(item_id=""), "id"))
    rows.append(("id ends in .json", item_body(item_id="idea-0001.json"), "id"))
    rows.append(("id ends in a dot", item_body(item_id="idea-0001."), "id"))
    rows.append(("id opens with a dash", item_body(item_id="-idea"), "id"))
    rows.append(("id is too long", item_body(item_id="i" * 81), "id"))
    bad("title missing", drop("title"), "title")
    rows.append(("title is not a string", item_body(title=7), "title"))
    rows.append(("title is blank", item_body(title="   "), "title"))
    rows.append(("title is multi-line", item_body(title="a\nb"), "title"))
    rows.append(("title is a CRLF break", item_body(title="a\r\nb"), "title"))
    rows.append(("title is a lone CR", item_body(title="a\rb"), "title"))
    rows.append(("title is past its bound", item_body(title="x" * 201), "title"))
    bad("status missing", drop("status"), "status")
    rows.append(("status is unknown", item_body(status="open"), "status"))
    bad("created missing", drop("created"), "created")
    rows.append(("created has no timezone",
                 item_body(created="2026-10-26T00:00:00"), "created"))
    rows.append(("created is local time with an offset",
                 item_body(created="2026-10-26T00:00:00+02:00"), "created"))
    rows.append(("created is a bare date", item_body(created="2026-10-26"),
                 "created"))
    rows.append(("created is a lowercase z",
                 item_body(created="2026-10-26T00:00:00z"), "created"))

    bad("every optional field on a candidate",
        set_fields(issue=7, decision=BASELINE_ID, why="because"), "issue")
    bad("issue on a candidate", set_fields(issue=7), "issue")

    bad("dropped without a decision",
        lambda body: (dropped(body), body.pop("decision")), "decision")
    bad("dropped with a null decision",
        lambda body: (dropped(body), body.update({"decision": None})),
        "decision")
    bad("dropped without a why",
        lambda body: (dropped(body), body.pop("why")), "why")
    bad("dropped with a null why",
        lambda body: (dropped(body), body.update({"why": None})), "why")
    bad("dropped with a blank why",
        lambda body: (dropped(body), body.update({"why": "   "})), "why")
    bad("dropped with a multi-line why",
        lambda body: (dropped(body), body.update({"why": "a\nb"})), "why")
    bad("dropped with a why past its bound",
        lambda body: (dropped(body),
                      body.update({"why": "x" * 281})), "why")
    bad("dropped still naming an issue",
        lambda body: (dropped(body), body.update({"issue": 7})), "issue")

    # ``promoted`` with no issue at all is NOT a row here: the schema cannot refuse
    # it (the field's absence is a well-formed document, and the census's own class
    # reports it), so this table -- which lists what the *reader* refuses -- would
    # promise a row neither side writes. The null form is the reader's to refuse.
    bad("promoted with a null issue",
        lambda body: body.update({"status": "promoted", "issue": None}),
        "promoted")
    bad("promoted with a string issue",
        lambda body: body.update({"status": "promoted", "issue": "7"}), "issue")
    bad("promoted with a bool issue",
        lambda body: body.update({"status": "promoted", "issue": True}), "issue")
    bad("promoted with a zero issue",
        lambda body: body.update({"status": "promoted", "issue": 0}), "issue")
    bad("promoted with a negative issue",
        lambda body: body.update({"status": "promoted", "issue": -3}), "issue")
    bad("promoted carrying a why",
        lambda body: body.update({"status": "promoted", "issue": 7,
                                  "why": "because"}), "why")
    bad("why on a candidate", set_fields(why="because"), "why")
    return rows


def not_a_json_object_shapes() -> list[tuple[str, str]]:
    """Raw bodies that are not an item document at all, as ``(name, text)`` pairs."""
    return [
        ("not json at all", "this is not json\n"),
        ("empty", ""),
        ("a json array", "[1, 2, 3]\n"),
        ("a json string", '"idea"\n'),
        ("a json number", "42\n"),
        ("a json null", "null\n"),
    ]
