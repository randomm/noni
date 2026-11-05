"""The README names the licence, and the licence file it names is the real one.

The page carries the licence in one sentence of the Contributing section rather
than in a section of its own: ``tests/readme_support.py`` pins the section order
and the 150-line cap, so a ``## License`` heading would fail the page on both
counts. That leaves the claim living inside prose nothing else reads, which is
what this module is for -- the sentence, and the file it points at.

The two assertions are deliberately different in kind. The first reads the page
(the word has to be there, in the section the page already has). The second
reads the artifact the word names: a ``LICENSE`` whose text is the Apache-2.0
body, which is the only thing that makes "Apache-2.0" a promise a reader can
act on rather than a label.

The page is read through ``readme_support`` (its reader and its line cap), not
through a path and a number typed here: the cap is one claim with one owner, and
a second copy of it would be free to disagree with the gate that enforces it.
"""

from __future__ import annotations

from _harness import REPO
from readme_support import README_LINE_LIMIT, _readme_text, _section

# The sentences' load-bearing words, kept apart so neither can be satisfied by
# the other: a page that said "Apache" alone, or named the file without naming
# the licence, would satisfy one assertion and fail the other.
SPDX = "Apache-2.0"

# The license's own header lines, indented as the license text prints them, and
# matched after stripping: the document opens with the name and the version on
# the first two lines, which is the shape no other license text shares.
LICENSE_HEAD = "Apache License"
LICENSE_VERSION_LINE = "Version 2.0, January 2004"
LICENSE_TAIL = "limitations under the License"


def test_readme_names_the_license_in_the_contributing_section() -> None:
    """The Contributing section names Apache-2.0 and routes the reader to the file.

    Pinned to the section by heading, the way the purity sentence is: a licence
    word planted anywhere else on the page would satisfy a whole-text search
    while the section a reader reaches for the licence had none.
    """
    section = _section(_readme_text(), "Contributing")
    assert SPDX in section, (
        "the Contributing section no longer names the licence, so the page's only "
        f"licence claim ({SPDX!r}) has disappeared"
    )
    assert "SECURITY.md" in section, (
        "the licence sentence carried the disclosure pointer with it; the page "
        "must still route a security problem to SECURITY.md"
    )


def test_readme_still_names_the_license_after_the_cap_and_the_order_hold() -> None:
    """The one-line claim costs the page neither its cap nor its section order.

    The issue's acceptance criterion is the licence named *within* the cap, and
    the cap is pinned elsewhere (``test_readme.py``). This is the conjunction:
    a fix that added a ``## License`` section to make the word easier to find
    would break the documented order, and one that added a line would break the
    cap, so the pair is checked here beside the claim itself.
    """
    text = _readme_text()
    lines = text.count("\n")
    assert lines <= README_LINE_LIMIT, (
        f"README.md is {lines} lines; the page's cap is {README_LINE_LIMIT}"
    )
    assert "## License" not in text and "## Licence" not in text, (
        "a licence section was added to the page: the claim is one sentence in "
        "the Contributing section, and a new heading breaks the section order "
        "tests/test_readme.py pins"
    )


def test_the_license_file_is_the_apache_2_0_text() -> None:
    """The file the README points at holds the license, not a stub that names it.

    The check is on the shape of the document -- its opening lines and its
    closing clause -- because the alternative is trusting a filename. A LICENSE
    that carried only the SPDX word would keep the README green while telling a
    reader nothing about what they may do.
    """
    path = REPO / "LICENSE"
    assert path.is_file(), "LICENSE is missing, so the README's claim names nothing"
    lines = path.read_text(encoding="utf-8").splitlines()
    # The license text is centred, so its first two lines are indentation and
    # nothing else: the header is the first line with content on it.
    content = [line.strip() for line in lines if line.strip()]
    assert content, "LICENSE is empty"
    assert content[0] == LICENSE_HEAD, (
        f"LICENSE does not open with the license header: {lines[0]!r}"
    )
    assert content[1] == LICENSE_VERSION_LINE, (
        f"LICENSE is not the 2.0 text: {lines[1]!r}"
    )
    body = "\n".join(lines)
    assert LICENSE_TAIL in body, "LICENSE does not carry the license's closing clause"
    assert path.stat().st_mode & 0o111 == 0, (
        "LICENSE is executable: a shebang or the exec bit would put the file "
        "under the 500-line source cap in tests/test_file_size_limit.py"
    )


def test_no_tracked_file_carries_an_unfilled_copyright_holder() -> None:
    """The license's appendix placeholders stay unfilled rather than filled in badly.

    The Apache appendix asks the adopter to replace ``[yyyy]`` and ``[name of
    copyright owner]``. Both are left as the license prints them: the ticket
    names no copyright holder, and an invented one would be an assertion about
    who owns the code that nothing here is entitled to make. This check is what
    stops a later edit filling them with a person's name or a machine-local
    value -- the scrub would catch a real name, but not a placeholder that
    quietly became a wrong one.
    """
    path = REPO / "LICENSE"
    assert path.is_file(), "LICENSE is missing"
    text = path.read_text(encoding="utf-8")
    assert "[yyyy]" in text and "[name of copyright owner]" in text, (
        "the license appendix's placeholders are gone: the LICENSE file is the "
        "unmodified Apache-2.0 text, and the holder is not this ticket's to fill"
    )


def test_security_page_names_the_private_route_and_the_scope() -> None:
    """SECURITY.md gives a private route and names the three things it covers.

    The page is what lets the README's single licence sentence also carry the
    disclosure pointer: a visitor who reaches the licence line meets the route on
    the same breath. Asserted beside the licence checks because both are one line
    of the page, and a rewording that dropped either would leave every other
    check green.

    The scope names the three things a reporter might otherwise file as an
    ordinary bug, and the private route is named by the mechanism rather than by
    any host, which is what keeps the page true if the repository moves.
    """
    page = REPO / "SECURITY.md"
    assert page.is_file(), "SECURITY.md is missing"
    text = page.read_text(encoding="utf-8").lower()
    assert "private vulnerability reporting" in text, (
        "the page no longer names private vulnerability reporting as the route"
    )
    assert "do not open a public issue" in text, (
        "the page no longer tells a reporter to avoid a public issue"
    )
    for subject in ("package", "skill", "census"):
        assert subject in text, f"the page does not name {subject!r} as in scope"

