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
from translatex.pdfin.roles import Role
from translatex.pdfin.words import Paragraph

#: A position carrying fewer than this share of what a column typically carries is in a
#: gutter. Measured against the median rather than the maximum: see `columns`.
GUTTER_DEPTH = 0.5

#: A band narrower than this share of the page is a sidebar or a stamp, not a column.
MIN_COLUMN_SHARE = 0.1

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
    """The horizontal bands the text of one page occupies, left to right.

    Found from how MANY lines cover each position, not from whether any does. A single
    full-width line — a spanning caption, a wide equation, a footer rule — bridges the
    gutter, and a rule that cuts wherever coverage reaches zero then reports one column
    across the whole page. Counting instead, the gutter stays a valley: a hundred lines
    stop at it and one crosses.
    """
    if not lines or page_width <= 0:
        return []

    width = int(page_width) + 1
    cover = [0] * width
    for line in lines:
        left = max(0, int(line.bbox[0]))
        right = min(width, int(line.bbox[2]) + 1)
        for x in range(left, right):
            cover[x] += 1

    covered = sorted(value for value in cover if value)
    if not covered:
        return []
    # Against the typical column, not against the busiest position. A page whose title
    # and abstract run the full measure has eight lines crossing the gutter, which cleared
    # a threshold set at a fraction of the maximum by a hair — and the whole opening page
    # came out as one column. The gutter is a valley beside the columns either side of it,
    # so the reference is what a column normally carries.
    typical = covered[len(covered) // 2]
    threshold = GUTTER_DEPTH * typical

    bands: list[tuple[float, float]] = []
    start = None
    for x in range(width):
        if cover[x] > threshold:
            if start is None:
                start = x
        elif start is not None:
            bands.append((float(start), float(x)))
            start = None
    if start is not None:
        bands.append((float(start), float(width)))

    # Sidebars and rotated stamps leave slivers that are not columns of anything.
    smallest = MIN_COLUMN_SHARE * page_width
    return [band for band in bands if band[1] - band[0] >= smallest]


def _column_of(box: tuple[float, float, float, float],
               bands: list[tuple[float, float]]) -> tuple[float, float] | None:
    """The band a box sits in, by the largest overlap."""
    best, overlap = None, 0.0
    for band in bands:
        shared = min(box[2], band[1]) - max(box[0], band[0])
        if shared > overlap:
            best, overlap = band, shared
    return best


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
