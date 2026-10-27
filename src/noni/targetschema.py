"""The supersede target's field types, as census.py types them.

The schema, not the mechanics: which fields a committed record must carry, and in
what type, so a status flip that copies a target's bytes verbatim can promise it
moved nothing but the status. ``gitwrite.load_committed_target`` asks this module
before any path is opened, so no caller can reach a write by checking only part of
the target. The rules and their wording are census.py's own: a ledger holding any
of these was never clean, so a writer that rewrote such a record would be repairing
the ledger by accident.
"""

from __future__ import annotations

# census.py types these as non-empty strings ("id must be a non-empty string", and
# the same for the others). The tests reject ``bool`` by name because Python calls
# ``True`` an ``int``: json's ``true`` is neither a number nor a string, so it is
# refused wherever the census wants a string.
_NON_EMPTY_STRINGS = ("id", "by", "asked_by", "scope", "date")


def _refusal(record: dict, target_id: str, field: str, want: str) -> tuple[str, str]:
    """One refusal for ``field``: what it holds, and the type the census wants.

    ``want`` is census.py's own wording, so this headline and the census's row for
    the same record read as one rule.
    """
    return (f"supersede target {target_id} carries a "
            f"{type(record[field]).__name__} in its {field} field where the census "
            f"requires {want}",
            "repair the record and commit it, then re-run decide")


def refuse_target_fields(record: dict, target_id: str,
                         statuses: tuple[str, ...]) -> tuple[str, str] | None:
    """Why ``record``'s own field types cannot be carried through a status flip, or
    None.

    A supersede copies the target and changes one value, so the helper that rewrites
    it must describe every byte it moves: every field the census types is asked here,
    not just the two the flip reads directly.

    ``date`` is sliced to its first ten characters to compare against the run's
    --date, so a value that is not a string would either raise TypeError mid-run or
    slice a null to ``''`` and be reported as "dated another day" -- which tells the
    operator to pass a date the record does not carry in the form the census
    requires. ``questions`` is what the record answers, and a flip that copied
    anything other than a non-empty list of objects each with a string ``id`` and an
    ``answer`` that is a string or null would be repairing the ledger by accident.

    ``statuses`` is the closed set the census allows and the writer can produce, for
    the same reason ``superseded`` arrives at ``refuse_live_record``: a list kept
    here could drift from the constants the writer flips between and quietly stop
    refusing what it should. The census's own wording is kept so its row and this
    headline read as one rule, and a non-string status is refused by the membership
    test like any other unknown value.
    """
    for field in _NON_EMPTY_STRINGS:
        value = record.get(field)
        if field in record and (not isinstance(value, str) or not value):
            return _refusal(record, target_id, field, "a non-empty string")
    if "status" in record and record["status"] not in statuses:
        return (f"supersede target {target_id} has a status the census refuses: "
                f"status not one of {'|'.join(statuses)}",
                "repair the record and commit it, then re-run decide")
    supersedes = record.get("supersedes")
    if "supersedes" in record and supersedes is not None \
            and (not isinstance(supersedes, str) or not supersedes):
        return _refusal(record, target_id, "supersedes", "null or a non-empty string")
    questions = record.get("questions")
    if not isinstance(questions, list) or not questions:
        return (f"supersede target {target_id} carries no questions: "
                f"{type(questions).__name__} where a non-empty list is required",
                "name a record the census accepts (census.py: questions must be an "
                "array of 1-4 entries)")
    for entry in questions:
        if not isinstance(entry, dict):
            return (f"supersede target {target_id} has a {type(entry).__name__} among "
                    "its questions where an object is required",
                    "repair the record so every question is an object with id, text, "
                    "options and an answer, then re-run decide")
        if not isinstance(entry.get("id"), str):
            return (f"supersede target {target_id} has a question whose id is "
                    f"{type(entry.get('id')).__name__}, not a string",
                    "repair the record so every question names itself with a string id, "
                    "then re-run decide")
        if "answer" in entry and not isinstance(entry["answer"], (str, type(None))):
            return (f"supersede target {target_id} has a question whose answer is "
                    f"{type(entry['answer']).__name__}, not a string or null",
                    "repair the record so every answer is a string or null, then "
                    "re-run decide")
    return None
