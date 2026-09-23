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

#: A position covered by fewer than this share of the busiest position's lines is in a
#: gutter, not in a column.
GUTTER_DEPTH = 0.15

#: A band narrower than this share of the page is a sidebar or a stamp, not a column.
MIN_COLUMN_SHARE = 0.1

#: A figure has to be at least this tall to be one; anything less is a rule or a stray
#: mark left between two paragraphs.
MIN_FIGURE_HEIGHT = 12.0

#: Room left around a figure so its outermost stroke is not shaved off.
FIGURE_PAD = 2.0

#: A line counts as bounding a span when it covers at least this much of it.
OVERLAP_SHARE = 0.2

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

    busiest = max(cover)
    if not busiest:
        return []
    threshold = GUTTER_DEPTH * busiest

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
    for index, (paragraph, role) in enumerate(zip(paragraphs, roles, strict=True)):
        if role is not Role.CAPTION:
            continue

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
        for span in (band, full):
            box = _between(caption_box, span, page_lines, own, page_rect,
                           above=bool(CAPTION_ABOVE.match(paragraph.text)))
            if box is None:
                continue
            ink = ink_box(doc, page_number, box)
            if ink is None or ink[3] - ink[1] < MIN_FIGURE_HEIGHT:
                continue
            found[index] = Crop(
                f"figure_{page_number + 1}_{index}",
                page_number,
                (ink[0] - FIGURE_PAD, ink[1] - FIGURE_PAD,
                 ink[2] + FIGURE_PAD, ink[3] + FIGURE_PAD),
            )
            break
    return found


def _between(
    caption: tuple[float, float, float, float],
    span: tuple[float, float],
    page_lines: list[Line],
    own: set[Line],
    page_rect: pymupdf.Rect,
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
        line.bbox
        for line in page_lines
        if line not in own
        and min(line.bbox[2], span[1]) - max(line.bbox[0], span[0]) > OVERLAP_SHARE * width
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
