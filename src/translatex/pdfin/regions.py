"""Columns, and the figures standing in them.

A figure is found from its caption rather than from its contents. Contents vary wildly —
one paper in the corpus draws its figures as 36 363 vector paths and another embeds them
as sixteen raster images — and clustering either into "a figure" means guessing where one
ends. The caption does not vary: every figure in a journal paper has one, it names itself,
and it sits directly against the thing it describes.

So the region is the gap between the caption and the nearest text above it, within the
caption's own column, shrunk to whatever ink turns out to be in there. A table works the
same way upside down: its caption is set above it, so the gap to look in is below.
"""

from __future__ import annotations

import re

import pymupdf

from translatex.pdfin.chars import Line
from translatex.pdfin.crops import Crop
from translatex.pdfin.crops import ink_box
from translatex.pdfin.layout import column_of as _column_of
from translatex.pdfin.layout import columns as _bands
from translatex.pdfin.roles import Role
from translatex.pdfin.words import Paragraph

#: A figure has to be at least this tall to be one; anything less is a rule or a stray
#: mark left between two paragraphs.
MIN_FIGURE_HEIGHT = 12.0

#: Room left around a figure so its outermost stroke is not shaved off.
FIGURE_PAD = 2.0

#: A line counts as bounding a span when it covers at least this much of it.
OVERLAP_SHARE = 0.2

#: A picture overlapping the found region by at least this much of itself belongs to the
#: figure and is taken whole; anything less is a logo standing beside it.
IMAGE_OVERLAP = 0.3

#: Captions beginning with this describe something set above them, not below.
CAPTION_ABOVE = re.compile(r"^\s*table\b", re.I)


def columns(lines: list[Line], page_width: float) -> list[tuple[float, float]]:
    """The columns of a page, from its lines."""
    return _bands([line.bbox for line in lines], page_width)


def reading_order(
    paragraphs: list[Paragraph], page_width: float, lines: list[Line]
) -> list[Paragraph]:
    """The paragraphs in the order a reader meets them: page, column, then down.

    The order a PDF stores blocks in is not the order anyone reads them. On one page of
    this corpus a prose paragraph at y=148 is stored before an equation at y=140, and the
    pieces of one equation are scattered among paragraphs that belong to the text around
    it. Every rule that says "the paragraph before this one" — a stray letter between two
    equations, a run of equation blocks, a caption and the sentence set apart from it —
    is about the page, not about the file, and needs the page's own order to work.
    """
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    def where(paragraph: Paragraph) -> tuple[int, float, float]:
        box = paragraph.lines[0].bbox
        page = paragraph.lines[0].page
        bands = columns(by_page.get(page, []), page_width)
        band = _column_of(box, bands)
        return (page, band[0] if band else box[0], box[1])

    return sorted(paragraphs, key=where)


def figure_regions(
    doc: pymupdf.Document,
    lines: list[Line],
    paragraphs: list[Paragraph],
    roles: list[Role],
) -> dict[int, Crop]:
    """The region each captioned figure or table occupies, keyed by its paragraph index.

    A caption with nothing but text against it yields nothing — some captions belong to a
    listing or an algorithm typeset as text, and those need no picture.
    """
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    found: dict[int, Crop] = {}
    # Claimed ground, page by page. Two figures cannot occupy the same space, and saying
    # so is the only thing that separates a figure from the one above it when no text runs
    # between them: a full-measure figure at the top of a page leaves the column beneath
    # it with nothing textual overhead, so the search ran to the top of the sheet and took
    # its neighbour whole.
    claimed: dict[int, list[tuple[float, float, float, float]]] = {}

    captions = sorted(
        (i for i, role in enumerate(roles) if role is Role.CAPTION),
        key=lambda i: (paragraphs[i].lines[0].page, paragraphs[i].lines[0].bbox[1]),
    )
    for index in captions:
        paragraph = paragraphs[index]
        page_number = paragraph.lines[0].page
        page_lines = by_page.get(page_number, [])
        page_rect = doc[page_number].rect
        bands = columns(page_lines, page_rect.width)
        caption = paragraph.lines[0].bbox
        band = _column_of(caption, bands) or (page_rect.x0, page_rect.x1)

        caption_box = paragraph.lines[0].bbox
        for line in paragraph.lines:
            caption_box = (
                min(caption_box[0], line.bbox[0]),
                min(caption_box[1], line.bbox[1]),
                max(caption_box[2], line.bbox[2]),
                max(caption_box[3], line.bbox[3]),
            )

        own = set(paragraph.lines)
        # A figure may be set across the whole measure rather than in one column, and
        # then the column it is looked for in holds nothing but white. So the column is
        # tried first and the full width second — the other way round would swallow the
        # neighbouring column's text into every single-column figure.
        full = (bands[0][0], bands[-1][1]) if bands else (page_rect.x0, page_rect.x1)
        taken = claimed.setdefault(page_number, [])
        for span in (band, full):
            box = _between(caption_box, span, page_lines, own, page_rect, taken,
                           above=bool(CAPTION_ABOVE.match(paragraph.text)))
            if box is None:
                continue
            ink = ink_box(doc, page_number, box)
            if ink is None or ink[3] - ink[1] < MIN_FIGURE_HEIGHT:
                continue
            grown = _with_images(doc, page_number, ink, band=(box[1], box[3]), reach=full)
            rect = (grown[0] - FIGURE_PAD, grown[1] - FIGURE_PAD,
                    grown[2] + FIGURE_PAD, grown[3] + FIGURE_PAD)
            found[index] = Crop(f"figure_{page_number + 1}_{index}", page_number, rect)
            taken.append(rect)
            taken.append(caption_box)
            break
    return found


#: A line has to carry this much text before a crop through it matters. The leftovers a
#: display leaves at the start of the sentence after it — "Þ", "T =", "dt" — are lines of
#: a prose paragraph but they are not prose, and protecting them refused eleven real
#: equations.
PROSE_LINE_MIN_CHARS = 12

#: Another line counts as sharing the equation's line when it overlaps the equation's
#: span by this much of its own height. A mere touch does not: the descenders of the line
#: above reach into the ascenders of the equation on nearly every display, and treating
#: that as sharing threw away two thirds of the real equations.
SHARE_A_LINE = 0.5


def _shares_a_line_with(other: tuple[float, float, float, float],
                        box: tuple[float, float, float, float]) -> bool:
    overlap = min(other[3], box[3]) - max(other[1], box[1])
    height = other[3] - other[1]
    return height > 0 and overlap >= SHARE_A_LINE * height


#: Words that only appear in prose. A region holding this many of them is showing a
#: sentence, whatever the geometry concluded.
FUNCTION_WORDS = re.compile(
    r"\b(?:the|and|are|is|of|in|with|for|from|this|that|where|which|as|by|to|be|can|"
    r"represents|denotes|shown|using|model|method|between|respectively)\b",
    re.I,
)
PROSE_WORDS_ALLOWED = 2


def _holds_a_sentence(doc: pymupdf.Document, page: int,
                      rect: tuple[float, float, float, float]) -> bool:
    """Whether a candidate region is showing prose rather than an equation.

    The last word on the matter, and deliberately not a geometric one. Every rule above
    reasons about boxes, and boxes are what the publisher chose; this reads what would
    actually be in the picture. A display equation carries symbols and a number. A
    sentence carries "the", "of", "is" — and if those are in there, the crop is a
    sentence cut out of the page and set beside its own translation.
    """
    text = doc[page].get_text(clip=pymupdf.Rect(*rect)).replace("\n", " ")
    return len(FUNCTION_WORDS.findall(text)) > PROSE_WORDS_ALLOWED


def _with_images(
    doc: pymupdf.Document,
    page_number: int,
    box: tuple[float, float, float, float],
    *,
    band: tuple[float, float],
    reach: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Widen a region to hold whole any embedded picture it has caught part of.

    A PDF says nothing about where a figure begins and ends — it is a page of marks — but
    it does say exactly where an embedded picture sits, and that is worth using when there
    is one. It settles the case the ink alone gets wrong: a picture set across the whole
    measure leaves ink in the column being searched, so the search stops there satisfied
    and crops a slice of it. Measured against the declared rectangles, that case agreed
    only 39%, and 81% once the picture was taken whole.

    Only sideways, and only as far as the text measure. The vertical bounds come from the
    text above and the caption below and are the reliable part; letting a picture push
    them outwards carried one region straight past its own caption and into the tops of
    the two figures beneath it.

    A picture barely touched is left alone; a logo beside a figure is not part of it.
    """
    page = doc[page_number]
    region = pymupdf.Rect(*box)
    left, right = region.x0, region.x1
    for image in page.get_images(full=True):
        for rect in page.get_image_rects(image[0]):
            if not rect.get_area():
                continue
            if (rect & region).get_area() / rect.get_area() >= IMAGE_OVERLAP:
                left, right = min(left, rect.x0), max(right, rect.x1)
    return (
        max(left, reach[0]),
        max(region.y0, band[0]),
        min(right, reach[1]),
        min(region.y1, band[1]),
    )


def _between(
    caption: tuple[float, float, float, float],
    span: tuple[float, float],
    page_lines: list[Line],
    own: set[Line],
    page_rect: pymupdf.Rect,
    taken: list[tuple[float, float, float, float]],
    *,
    above: bool,
) -> tuple[float, float, float, float] | None:
    """The empty band next to a caption, bounded by the nearest text on the other side.

    Any line overlapping the span counts as a bound, not only one whose own column this
    is. A running head spans the whole measure and belongs to neither column, and leaving
    it out let the search run past it and up to the top of the sheet.
    """
    width = span[1] - span[0]
    others = [
        box
        for box in ([line.bbox for line in page_lines if line not in own] + taken)
        if min(box[2], span[1]) - max(box[0], span[0]) > OVERLAP_SHARE * width
    ]
    if above:
        below = [b[1] for b in others if b[1] >= caption[3]]
        top, bottom = caption[3], min(below) if below else page_rect.y1
    else:
        higher = [b[3] for b in others if b[3] <= caption[1]]
        top, bottom = max(higher) if higher else page_rect.y0, caption[1]

    if bottom - top < MIN_FIGURE_HEIGHT:
        return None
    return (span[0], top, span[1], bottom)


#: Room around a display equation, so no stroke is shaved by rounding.
EQUATION_PAD = 1.0

#: Roles that end an equation's band. Everything between two of them belongs to the
#: equation, whatever it was classified as on its own.
PROSE = frozenset({Role.BODY, Role.HEADING, Role.CAPTION, Role.ABSTRACT,
                   Role.TITLE, Role.AUTHORS, Role.REFERENCE, Role.FRONTMATTER})


def equation_regions(
    doc: pymupdf.Document,
    lines: list[Line],
    paragraphs: list[Paragraph],
    roles: list[Role],
) -> tuple[dict[int, Crop], set[int]]:
    """One region per display equation, and the paragraph indices it swallowed.

    A display equation is not a paragraph. The publisher lays it out as a row of separate
    blocks — a numerator here, a radical there, a lone subscript — so taking each block as
    its own region cut one equation into a dozen slivers, each set as a picture of almost
    nothing, with the pieces that happened to look like prose printed as text between them.

    The region is therefore the band between the prose above and the prose below, in the
    equation's own column, exactly as a figure's is. And everything standing in that band
    belongs to the equation, whatever it was classified as: a fragment that reads like a
    sentence is still part of the display it sits inside.
    """
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    found: dict[int, Crop] = {}
    absorbed: set[int] = set()

    index = 0
    while index < len(roles):
        if roles[index] is not Role.EQUATION or index in absorbed:
            index += 1
            continue

        page = paragraphs[index].lines[0].page
        page_lines = by_page.get(page, [])
        page_rect = doc[page].rect
        bands = columns(page_lines, page_rect.width)

        run = [index]
        while (
            run[-1] + 1 < len(roles)
            and roles[run[-1] + 1] is Role.EQUATION
            and paragraphs[run[-1] + 1].lines[0].page == page
        ):
            run.append(run[-1] + 1)

        boxes = [line.bbox for i in run for line in paragraphs[i].lines]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        band = _column_of(box, bands) or (page_rect.x0, page_rect.x1)

        # The equation's own extent, widened a little for the strokes the text layer does
        # not hold — but never past a line that is not part of it. Reaching out to the
        # prose above and below instead swallowed the sentences the publisher sets among
        # the blocks of a display; widening blindly clipped the neighbouring line in half
        # and printed the half inside the crop.
        # Only prose can be cut by a crop. Counting every other line made the rows of one
        # display equation cut each other, and equations (1), (3) and (5) came out as
        # text: a run covers the blocks that happened to be consecutive, and its own
        # remaining rows then looked like neighbours to keep clear of.
        mine = {id(line) for i in run for line in paragraphs[i].lines}
        others = [
            line.bbox
            for i, other in enumerate(paragraphs)
            if roles[i] in PROSE and other.lines[0].page == page
            for line in other.lines
            if id(line) not in mine
            and len(line.text.strip()) >= PROSE_LINE_MIN_CHARS
            and _column_of(line.bbox, bands) == band
        ]
        # A run that shares a line with text is not a display equation at all — it is
        # inline maths, and there is no way to crop it without cutting that line through
        # the middle, which is exactly what the page showed: "camera modeled using the
        # pinhole model" sliced in half and set as a picture. Leave it to be masked and
        # set in the line where it belongs.
        if any(_shares_a_line_with(b, box) for b in others):
            index = run[-1] + 1
            continue

        top = max(
            [box[1] - EQUATION_PAD]
            + [b[3] for b in others if b[3] <= box[1]]
        )
        bottom = min(
            [box[3] + EQUATION_PAD]
            + [b[1] for b in others if b[1] >= box[3]]
        )
        ink = ink_box(doc, page, (band[0], top, band[1], bottom))
        if ink is not None:
            rect = (ink[0] - EQUATION_PAD, ink[1] - EQUATION_PAD,
                    ink[2] + EQUATION_PAD, ink[3] + EQUATION_PAD)
            # Checked on the finished rectangle, not on the ink: the padding is what
            # reaches back into the line above.
            if _holds_a_sentence(doc, page, rect):
                index = run[-1] + 1
                continue
            found[index] = Crop(f"eq_{index}", page, rect)
            for i, other in enumerate(paragraphs):
                if i == index or other.lines[0].page != page:
                    continue
                # The WHOLE paragraph has to be inside, not just its first line. An
                # equation number sits on the equation's own line and the sentence that
                # follows it begins on the next, and the two are one paragraph: judging
                # by the first line alone swallowed "(3) where ipc = u0,v0 is the
                # geometric centroid of the image" into the picture.
                boxes = [line.bbox for line in other.lines]
                whole = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                         max(b[2] for b in boxes), max(b[3] for b in boxes))
                if top <= whole[1] and whole[3] <= bottom and _column_of(whole, bands) == band:
                    absorbed.add(i)
        index = run[-1] + 1
    return found, absorbed
