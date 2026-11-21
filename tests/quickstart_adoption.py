"""The standing paragraph the quickstart ships for a project to copy into its own
agent instructions file, and the shape the wire section owes around it.

The paragraph is the product's own words, not a page's prose: an agent pastes it
into the project's instructions file, so the text is the deliverable and a reword is
a different deliverable. That is why it is pinned as one exact string against the
constant below rather than as a set of phrases a paraphrase would keep.

Held in a helper module (never named ``test_*``, so pytest never collects it) the
way ``quickstart_golden.py`` holds the page's commands: the assertion that reads it
lives in ``tests/test_quickstart_adoption.py``, and the two cannot drift to two
different texts.
"""

from __future__ import annotations

from docs_commands import read
from docs_promises import QUICKSTART, README, REPO, section_body
from quickstart_golden import WIRE
from readme_support import README_LINE_LIMIT as _README_LINE_LIMIT

# The paragraph, exactly as the page ships it, and exactly as a project is meant to
# hold it. The page wraps it for its own column budget; the constant is the words a
# reader copies, so the assertion compares on collapsed whitespace.
STANDING_PARAGRAPH = (
    "This project keeps its direction in noni, at the state root `.noni-state`: the "
    "standing intent, the order of work and the operator's decisions. At session "
    "start run `noni brief --repo .noni-state` and work in its order. Do not invent "
    "direction. When something is undecided, ask the operator and record the answer "
    "with `noni decide`."
)

# The same paragraph as the page ships it: blockquote lines wrapped at the page's own
# columns. The verbatim test compares these bytes to the constant above, so a page that
# reworded or rewrapped the copy a reader pastes is caught either way.
STANDING_PARAGRAPH_PAGE = [
    "> This project keeps its direction in noni, at the state root `.noni-state`: the",
    "> standing intent, the order of work and the operator's decisions. At session start",
    "> run `noni brief --repo .noni-state` and work in its order. Do not invent direction.",
    "> When something is undecided, ask the operator and record the answer with",
    "> `noni decide`.",
]

# The cap the paragraph ships under: it is one paragraph of an agent's instructions
# file, not a document.
STANDING_PARAGRAPH_MAX = 400

# The quickstart's line cap. The gate that owns it is
# ``test_quickstart.test_the_quickstart_page_is_linked_and_within_its_size``, which
# holds 400 as an inline literal rather than a module-level constant, so there is
# nothing here to import it from and the literal stays. README's cap, by contrast,
# comes from its owner above: ``readme_support.README_LINE_LIMIT``, re-exported under
# the name the adoption test reads.
QUICKSTART_LINE_LIMIT = 400
README_LINE_LIMIT = _README_LINE_LIMIT

# The heading of the wire section, and the two pages that must name the release tag.
WIRE_HEADING = WIRE[0]

# The one link the README's first screen may carry to the adoption path.
ADOPTION_LINK = "[docs/QUICKSTART.md](docs/QUICKSTART.md)"


def wire_section() -> str:
    """The page's ``## Wire the project`` section, heading included."""
    return section_body(read(QUICKSTART), WIRE_HEADING)


def wire_section_flowed() -> str:
    """The wire section with its markdown line wrapping collapsed.

    The page wraps at its own column budget, so a locator that spans a sentence has
    to read the words a reader reads and not the bytes between them.
    """
    from quickstart_page import flowed_text

    return flowed_text(wire_section())


def standing_paragraph_as_shipped() -> str:
    """The quoted paragraph of the wire section, joined back to its shipped bytes.

    The page wraps the paragraph at its own column budget; a reader pastes it as one
    paragraph, so the join strips each line's blockquote marker and its leading space
    and puts one space back where the page broke the line. The lines are compared to
    :data:`STANDING_PARAGRAPH_PAGE` first, so a page that dropped a word, added one or
    changed a marker fails on the bytes rather than reading plausibly.
    """
    lines = [line for line in wire_section().splitlines()
             if line.lstrip().startswith(">")]
    assert lines, "the wire section quotes no paragraph"
    assert lines == STANDING_PARAGRAPH_PAGE, (
        f"the shipped paragraph's lines changed:\n{lines}")
    return " ".join(word for line in lines
                    for word in line.lstrip().lstrip(">").split())


def readme_first_screen() -> str:
    """Everything the README holds above its ``## The problem`` heading."""
    text = read(README)
    cut = text.find("## The problem")
    assert cut >= 0, "README.md has no '## The problem' heading"
    return text[:cut]


def ledger_page() -> str:
    """The steering-ledger skill page, the recording guidance an agent reads."""
    return read(REPO / "skills" / "steering-ledger" / "SKILL.md")
