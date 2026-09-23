"""What each paragraph on the page is for, and whether it should be translated.

The question this answers is not typographic but practical: a paragraph is either prose
someone should read in their own language, or it is machinery — an author's name, a DOI,
an equation, a reference list — that must survive untouched. Getting it wrong in one
direction leaves English in the middle of the translation; in the other it translates a
surname or renumbers a citation.

Type size alone cannot decide it. In one paper the caption, the footnote, the affiliation
and the copyright notice are all set at 8pt, and only three of the four are prose. So the
size narrows the field and the text itself settles it.
"""

from __future__ import annotations

import enum
import re
from collections import Counter
from dataclasses import dataclass

from translatex.pdfin.chars import Line
from translatex.pdfin.words import Paragraph


class Role(enum.Enum):
    TITLE = "title"
    AUTHORS = "authors"
    ABSTRACT = "abstract"
    HEADING = "heading"
    BODY = "body"
    CAPTION = "caption"
    EQUATION = "equation"
    REFERENCE = "reference"
    FRONTMATTER = "frontmatter"
    RUNNING = "running"

    @property
    def translatable(self) -> bool:
        """Whether a reader wants this in their own language."""
        return self in _TRANSLATABLE


_TRANSLATABLE = frozenset(
    {Role.TITLE, Role.ABSTRACT, Role.HEADING, Role.BODY, Role.CAPTION}
)

# A caption names its figure or table before it says anything else.
CAPTION = re.compile(r"^(fig(?:ure)?|table|algorithm|alg)\.?\s*[\dIVXLC]+[.:]?", re.I)

# The abstract and the keyword list announce themselves, with an em dash or a colon.
ABSTRACT = re.compile(r"^(abstract|index\s+terms|keywords)\s*[—:-]", re.I)

# A numbered heading: "II.", "B.", "3.2", "4)", followed by its name. A bare digit and a
# space is deliberately not one — these journals number with roman numerals and letters,
# and accepting "\d+ " made "0 −1cptz cptz 1þe2y" a section head, set large and in English
# in the middle of a matrix.
HEADING_NUMBER = re.compile(r"^(?:[IVXLC]+\.|[A-Z]\.|\d+\)|\d+(?:\.\d+)+)(?:\s|$)")

REFERENCES_HEADING = re.compile(r"^references?$", re.I)

# The publisher's own furniture, none of it prose.
FRONTMATTER = re.compile(
    r"^(manuscript\s+received|received\s+\d|revised\s+\d|accepted\s+\d"
    r"|digital\s+object\s+identifier|doi\b|\d{4}-\d{3}[\dx]\s*©|©\s*\d{4}"
    r"|corresponding\s+author|this\s+work\s+was\s+supported"
    r"|personal\s+use\s+is\s+permitted|authorized\s+licensed\s+use)",
    re.I,
)
AFFILIATION = re.compile(r"\b(is|are)\s+with\s+the\b|@[\w.]+\.\w+", re.I)

# An equation carries its number at the right margin and nothing else after it.
EQUATION_NUMBER = re.compile(r"\(\d+[a-z]?\)\s*$")

#: A paragraph this much larger than the body, on the opening page, is the title.
TITLE_RATIO = 1.8

#: Below this share of letters, a paragraph is not prose in any language. Measured on one
#: paper: the body paragraphs average 80% letters, the display equations 0%. Nothing sits
#: between, because an equation that reads as a sentence is a sentence.
PROSE_LETTER_SHARE = 0.4

#: Fonts carrying this much of the document between them are its text faces; the rest is
#: display, maths and furniture. Keyed on the whole document rather than on the body size,
#: because a caption and a footnote are text too and are set smaller.
TEXT_FONT_COVERAGE = 0.9

#: Above this share of characters in faces the body never uses, a paragraph is an
#: expression however many letters it has. Measured on one paper: the stranded pieces of
#: display equations sit at a median of 0.50 and real body paragraphs at 0.00, topping out
#: at 0.09. Without it "¼ eat" and "e _pM ¼ evM" went to the translator as prose, came
#: back unchanged because there was nothing to translate, and were set as text.
MATHS_FONT_SHARE = 0.35

#: A paragraph shorter than this, with an equation on either side, is part of it. The
#: single letters a display equation leaves stranded — "r", "m", "e" — are set in the text
#: face and carry no other signal at all.
EQUATION_NEIGHBOUR_CHARS = 25

#: A folio is this short. Longer furniture — the journal's running head, a download
#: stamp — is caught by repeating on page after page, which is a far better signal than
#: position and does not depend on guessing where the text block begins.
RUNNING_MAX_CHARS = 12

#: And it stands clear of the text block by at least this much, in body sizes. Without a
#: gap the rule ate the first line of a column whenever it was short: "relative
#: relationship can be expressed as" sits a few points above the fifth percentile of line
#: tops, which is not a margin, and it took the equation under it along.
RUNNING_GAP_EM = 1.0

#: A text appearing verbatim on this many pages is furniture.
REPEATS_TO_BE_FURNITURE = 3

#: Too short to be worth comparing: a stray letter or a stub repeats by accident.
FURNITURE_MIN_CHARS = 12

#: A drop cap is set at least this much larger than the heading beside it.
DROP_CAP_RATIO = 1.5

#: Prose runs longer than this; a shorter paragraph that also looks like a heading is one.
HEADING_MAX_CHARS = 90


@dataclass(frozen=True)
class Layout:
    """What the document as a whole looks like, measured once."""

    body_size: float
    body_fonts: frozenset[str]
    top_margin: float
    bottom_margin: float

    @classmethod
    def measure(cls, lines: list[Line]) -> Layout:
        chars = [c for line in lines for c in line.chars if not c.text.isspace()]
        sizes = Counter(round(c.size, 1) for c in chars)
        body_size = sizes.most_common(1)[0][0] if sizes else 10.0

        # Text faces are the few that carry most of the document, at any size. Keying
        # this on the body size alone made the 8pt caption face and the 11pt byline face
        # look foreign, and every caption came out classified as an equation.
        fonts = Counter(c.font for c in chars)
        wanted = TEXT_FONT_COVERAGE * sum(fonts.values())
        running, body_fonts = 0, set()
        for font, count in fonts.most_common():
            if running >= wanted:
                break
            body_fonts.add(font)
            running += count

        # Where the body actually lives, as a band rather than as two extreme lines.
        # Taking the highest and lowest line of the document made those two lines a
        # running head and a folio by definition, whatever they said.
        body_lines = sorted(
            (
                line
                for line in lines
                if any(round(c.size, 1) == body_size for c in line.chars)
            ),
            key=lambda line: line.bbox[1],
        )
        if body_lines:
            # A short tail, not a fifth of a percent short of nothing: the text block
            # starts where the first column starts, and taking 5% of lines as "above the
            # body" put the boundary thirty points into the text, which made the opening
            # line of a column a running head whenever it was short.
            edge = max(1, len(body_lines) // 200)
            top = body_lines[edge - 1].bbox[1]
            bottom = sorted(body_lines, key=lambda line: line.bbox[3])[-edge].bbox[3]
        else:
            top, bottom = 0.0, 0.0
        return cls(
            body_size=body_size,
            body_fonts=frozenset(body_fonts),
            top_margin=top,
            bottom_margin=bottom,
        )


def _size(paragraph: Paragraph) -> float:
    sizes = Counter(
        round(c.size, 1) for line in paragraph.lines for c in line.chars if not c.text.isspace()
    )
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _foreign_share(paragraph: Paragraph, layout: Layout) -> float:
    """The share of a paragraph set in faces the body never uses, or unreadable."""
    chars = [c for line in paragraph.lines for c in line.chars if not c.text.isspace()]
    if not chars:
        return 0.0
    return sum(
        c.font not in layout.body_fonts or not c.readable for c in chars
    ) / len(chars)


def _letter_share(text: str) -> float:
    """How much of a paragraph is letters — the one clean line between prose and maths."""
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return sum(char.isalpha() for char in stripped) / len(stripped)


def _looks_like_heading(text: str, size: float, layout: Layout) -> bool:
    if len(text) > HEADING_MAX_CHARS:
        return False
    # The number test comes first: "II." is a heading and ends in a period, while a
    # sentence ending in one is not.
    if HEADING_NUMBER.match(text):
        return True
    if text.endswith("."):
        return False
    # Small capitals and full capitals are both how these journals set a section name.
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and (
        sum(c.isupper() for c in letters) / len(letters) > 0.8 or size > layout.body_size
    )


def _repeated(paragraphs: list[Paragraph]) -> set[str]:
    """Texts that appear on several pages, which makes them furniture and not content.

    A running head, a copyright line and a library's download stamp all repeat unchanged
    page after page, and nothing a paper actually says does. One rule covers the lot, and
    it covers them whatever they happen to say — which matters, because the stamp is a
    sentence, sits in the middle of a column and is set in the text face.

    Compared verbatim. Blanking the numbers first, so that a folio would match its
    neighbours, made every figure caption furniture instead: this runs before the pieces
    of a caption are stitched together, and "Fig. 1." and "Fig. 2." are the same line
    once their numbers are gone. Folios are caught by the margin rule anyway.
    """
    pages: dict[str, set[int]] = {}
    for paragraph in paragraphs:
        key = paragraph.text.strip().lower()
        if len(key) >= FURNITURE_MIN_CHARS:
            pages.setdefault(key, set()).add(paragraph.lines[0].page)
    return {key for key, seen in pages.items() if len(seen) >= REPEATS_TO_BE_FURNITURE}


def classify(paragraphs: list[Paragraph], layout: Layout) -> list[Role]:
    """A role for each paragraph, in order.

    The reference list is found by its heading rather than by the shape of its entries:
    "[12] A. Author, ..." is unmistakable, but so is a citation in running text, and the
    heading says which side of the document we are on.
    """
    furniture = _repeated(paragraphs)
    roles: list[Role] = []
    in_references = False
    first_page = paragraphs[0].lines[0].page if paragraphs else 0

    for paragraph in paragraphs:
        text = paragraph.text.strip()
        size = _size(paragraph)
        page = paragraph.lines[0].page
        box = paragraph.lines[0].bbox

        if REFERENCES_HEADING.match(text):
            in_references = True
            roles.append(Role.HEADING)
            continue
        if in_references:
            roles.append(Role.REFERENCE)
            continue

        if not text:
            roles.append(Role.RUNNING)
        elif text.lower() in furniture:
            roles.append(Role.RUNNING)
        elif page == first_page and size >= TITLE_RATIO * layout.body_size:
            # Before the running-head test, not after: a title is set above the band the
            # body occupies, which is exactly where a running head sits, and no running
            # head was ever set at twice the body size.
            roles.append(Role.TITLE)
        elif len(text) < RUNNING_MAX_CHARS and (
            box[3] < layout.top_margin - RUNNING_GAP_EM * layout.body_size
            or box[1] > layout.bottom_margin + RUNNING_GAP_EM * layout.body_size
        ):
            # A running head or a folio is short AND sits outside the band the body
            # occupies. Position alone is not enough: the first line of a section and the
            # last line of a column are at the edges too, and they are content.
            roles.append(Role.RUNNING)
        elif ABSTRACT.match(text):
            roles.append(Role.ABSTRACT)
        elif CAPTION.match(text):
            roles.append(Role.CAPTION)
        elif FRONTMATTER.match(text) or AFFILIATION.search(text):
            roles.append(Role.FRONTMATTER)
        elif _looks_like_heading(text, size, layout) and _letter_share(text) > PROSE_LETTER_SHARE:
            # Before the maths tests, not after: a subsection head is set in a display
            # face the body never uses, so the font share calls it an expression — and
            # then the equation beside it swallows it whole and sets it as a picture,
            # in English.
            roles.append(Role.HEADING)
        elif (
            _letter_share(text) < PROSE_LETTER_SHARE
            or _foreign_share(paragraph, layout) > MATHS_FONT_SHARE
        ):
            roles.append(Role.EQUATION)
        elif page == first_page and layout.body_size < size < TITLE_RATIO * layout.body_size:
            roles.append(Role.AUTHORS)
        elif _looks_like_heading(text, size, layout):
            roles.append(Role.HEADING)
        else:
            roles.append(Role.BODY)
    return _adopt_strays(paragraphs, roles)


def _adopt_strays(paragraphs: list[Paragraph], roles: list[Role]) -> list[Role]:
    """Give a short paragraph between two equations to the equation around it.

    A display equation set across several blocks leaves single letters stranded — "r",
    "m", "e" — in the text face, carrying no signal of their own. Their company is the
    only evidence there is, and it is good evidence: prose does not appear one letter at
    a time between two equations.
    """
    out = list(roles)
    for index in range(1, len(out) - 1):
        if out[index] is not Role.BODY:
            continue
        if out[index - 1] is Role.EQUATION and out[index + 1] is Role.EQUATION:
            if len(paragraphs[index].text.strip()) <= EQUATION_NEIGHBOUR_CHARS:
                out[index] = Role.EQUATION
    return out


# A section number set as its own block: "I.", "B.", "3.2".
BARE_NUMBER = re.compile(r"^(?:[IVXLC]+|[A-Z]|\d+(?:\.\d+)*)\.?$")

# A heading ending in a lone capital has swallowed the initial of the paragraph below —
# these journals set that letter large, and the page assigns it to the line above.
DROP_CAP = re.compile(r"\s([A-Z])$")


def _is_initial(paragraph: Paragraph) -> bool:
    """Whether a paragraph is nothing but one oversized capital — a drop cap."""
    if len(paragraph.lines) != 1:
        return False
    chars = [c for c in paragraph.lines[0].chars if not c.text.isspace()]
    return len(chars) == 1 and chars[0].text.isalpha() and chars[0].text.isupper()


def _joined(first: Paragraph, second: Paragraph) -> Paragraph:
    return Paragraph(first.lines + second.lines, first.known_words or second.known_words)


def _take_drop_cap(heading: Paragraph, body: Paragraph) -> tuple[Paragraph, Paragraph] | None:
    """Move a large initial back from the heading it was drawn beside to its paragraph.

    The letter is recognised by its size and nothing else. The tempting test — that the
    paragraph below begins in lower case — is wrong here, because these journals set the
    rest of the opening word in small capitals: the drop cap takes the T and "HE presence"
    is what remains.
    """
    *rest, last_line = heading.lines
    chars = list(last_line.chars)
    while chars and chars[-1].text.isspace():
        chars.pop()
    if not chars or not (chars[-1].text.isalpha() and chars[-1].text.isupper()):
        return None

    # The baseline is the whole heading, not the last line: the initial is often set on a
    # line of its own, and then there is nothing beside it to compare against.
    elsewhere = [
        c.size
        for line in heading.lines
        for c in line.chars
        if not c.text.isspace() and c is not chars[-1]
    ]
    if not elsewhere or chars[-1].size < DROP_CAP_RATIO * (sum(elsewhere) / len(elsewhere)):
        return None
    initial = chars.pop()

    kept = list(rest)
    if chars:
        kept.append(Line(tuple(chars), last_line.page, last_line.block, last_line.index))
    if not kept:
        return None

    first_line, *others = body.lines
    restored = Line(
        (initial, *first_line.chars), first_line.page, first_line.block, first_line.index
    )
    return (
        Paragraph(tuple(kept), heading.known_words),
        Paragraph((restored, *others), body.known_words),
    )


def merge(paragraphs: list[Paragraph], roles: list[Role]) -> tuple[list[Paragraph], list[Role]]:
    """Join the pieces the page split that the document never meant to separate.

    A title wraps onto a second line, a byline breaks at every comma, a section number is
    set apart from its name, and a caption's first sentence is a block of its own. None of
    those are two things.
    """
    out_paragraphs: list[Paragraph] = []
    out_roles: list[Role] = []

    for paragraph, role in zip(paragraphs, roles, strict=True):
        if not out_paragraphs:
            out_paragraphs.append(paragraph)
            out_roles.append(role)
            continue

        previous, previous_role = out_paragraphs[-1], out_roles[-1]
        same_page = previous.lines[-1].page == paragraph.lines[0].page

        if same_page and previous_role is role and role in _RUNS_ON:
            out_paragraphs[-1] = _joined(previous, paragraph)
            continue
        # A number alone is not a heading, and the words beside it are not a paragraph.
        if same_page and previous_role is Role.HEADING and BARE_NUMBER.match(previous.text.strip()):
            out_paragraphs[-1] = _joined(previous, paragraph)
            out_roles[-1] = Role.HEADING
            continue
        if same_page and previous_role is Role.CAPTION and role is Role.BODY:
            out_paragraphs[-1] = _joined(previous, paragraph)
            continue
        if role is Role.BODY and _is_initial(previous):
            # A drop cap stands alone: it is one letter, several times the body size, and
            # once the lines are stitched it is a paragraph of its own — classified by
            # its size as a title when it happens to fall on the opening page. Whatever
            # it was called, it belongs to the word beside it.
            out_paragraphs[-1] = Paragraph(
                (Line((*previous.lines[0].chars, *paragraph.lines[0].chars),
                      paragraph.lines[0].page, paragraph.lines[0].block,
                      paragraph.lines[0].index),
                 *paragraph.lines[1:]),
                paragraph.known_words,
            )
            out_roles[-1] = role
            continue
        if previous_role is Role.HEADING and role is Role.BODY:
            moved = _take_drop_cap(previous, paragraph)
            if moved is not None:
                out_paragraphs[-1], paragraph = moved

        out_paragraphs.append(paragraph)
        out_roles.append(role)

    return out_paragraphs, out_roles


#: Roles whose consecutive paragraphs are always one thing wrapped across blocks.
_RUNS_ON = frozenset({Role.TITLE, Role.AUTHORS})
