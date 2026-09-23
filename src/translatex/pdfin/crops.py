"""Cutting pieces of the original page out to be placed in the new one.

Three things get reproduced rather than rewritten: a figure, which was never text; a
display equation, whose fraction bars and matrix rules are drawn strokes that the text
layer does not contain; and a glyph nobody could identify, which has to appear as itself
because there is nothing to write instead.

Nothing here writes a file. A crop is a region — a page and a rectangle — and the document
shows it with `\\includegraphics[page=N,trim=...,clip]{original.pdf}`, straight from the
source that is sitting in the same folder anyway. That keeps it vector, costs no bytes,
and cannot drift out of step with the file it came from.

Writing crops out was tried first and measured: every extracted region carries a copy of
its page's resources, a flat 56 kB whether the region is a whole figure or one comma, so
eighteen glyphs came to two megabytes. Rastering instead is small for a glyph and ruinous
for a figure — 359 bytes for one mark at 1200 dpi, 1.6 MB for a half-page. Referring to
the original is better than both and simpler than either.

Glyph regions are found once per distinct glyph, not once per occurrence. Measured across
twenty papers: 2322 unreadable characters are 124 distinct glyphs, fifteen to twenty-two
per paper, each reappearing nineteen times on average.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from translatex.pdfin.chars import Char

#: Room left around a crop so nothing is shaved off by rounding.
PAD = 1.0

#: A glyph crop is padded more tightly than a figure; the mark is small to begin with.
GLYPH_PAD = 0.3

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Crop:
    """One region of the original document, and the name it will be filed under."""

    name: str
    page: int
    rect: tuple[float, float, float, float]

    @property
    def width(self) -> float:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> float:
        return self.rect[3] - self.rect[1]


def _safe(name: str) -> str:
    return _UNSAFE.sub("_", name).strip("_") or "glyph"


def bounds(chars: list[Char], pad: float = PAD) -> tuple[float, float, float, float]:
    """The box holding every character given, with a little air around it."""
    boxes = [c.bbox for c in chars]
    return (
        min(b[0] for b in boxes) - pad,
        min(b[1] for b in boxes) - pad,
        max(b[2] for b in boxes) + pad,
        max(b[3] for b in boxes) + pad,
    )


#: Resolution used to find where the ink actually is. High enough that a hairline rule
#: survives, low enough that the scan costs nothing.
INK_DPI = 300

#: Anything lighter than this counts as paper rather than ink.
INK_THRESHOLD = 250


def tighten(doc: pymupdf.Document, crop: Crop, pad: float = GLYPH_PAD) -> Crop:
    """Shrink a crop to the ink inside it, leaving `pad` of paper around it.

    A character's box is the height of its line, not of its mark, so a crop taken at face
    value carries a band of empty paper above and below it. Finding the ink is a matter of
    looking: the region is rendered once and scanned for pixels darker than paper. A box
    with no ink at all is returned unchanged, because there is nothing to shrink to.
    """
    page = doc[crop.page]
    rect = pymupdf.Rect(*crop.rect) & page.rect
    if rect.is_empty:
        return crop

    pix = page.get_pixmap(clip=rect, dpi=INK_DPI, alpha=False, colorspace=pymupdf.csGRAY)
    if not pix.width or not pix.height:
        return crop

    samples = pix.samples
    rows = [
        y
        for y in range(pix.height)
        if min(samples[y * pix.stride : y * pix.stride + pix.width]) < INK_THRESHOLD
    ]
    if not rows:
        return crop
    columns = [
        x
        for x in range(pix.width)
        if any(samples[y * pix.stride + x] < INK_THRESHOLD for y in rows)
    ]
    if not columns:
        return crop

    scale_x = rect.width / pix.width
    scale_y = rect.height / pix.height
    return Crop(
        crop.name,
        crop.page,
        (
            rect.x0 + columns[0] * scale_x - pad,
            rect.y0 + rows[0] * scale_y - pad,
            rect.x0 + (columns[-1] + 1) * scale_x + pad,
            rect.y0 + (rows[-1] + 1) * scale_y + pad,
        ),
    )


def trim(doc: pymupdf.Document, crop: Crop) -> tuple[float, float, float, float]:
    """The graphicx `trim` for this region: how much to cut off left, bottom, right, top.

    Nothing is written out. `\\includegraphics[page=N,trim=...,clip]{original.pdf}` shows
    the region straight from the source, which keeps it vector, costs no bytes and cannot
    drift out of step with the file it came from. Cropping to separate PDFs was measured
    first and rejected: every crop carries a copy of its page's resources, a flat 56 kB
    whatever its size, so eighteen glyphs came to two megabytes.

    The y axis is flipped on the way: pymupdf counts down from the top, graphicx up from
    the bottom.
    """
    page = doc[crop.page].rect
    left, top, right, bottom = crop.rect
    return (left, page.height - bottom, page.width - right, top)


def glyph_crops(chars: list[Char]) -> dict[tuple[str, str], Crop]:
    """One crop per distinct unreadable glyph, keyed by the font and code it came from.

    The widest occurrence is chosen rather than the first: a glyph clipped by a column
    edge or overlapped by a neighbour would otherwise be the one copy everything uses.
    """
    best: dict[tuple[str, str], Char] = {}
    for char in chars:
        if char.readable:
            continue
        key = (char.font, char.text)
        if key not in best or char.width > best[key].width:
            best[key] = char

    return {
        key: Crop(
            name=f"glyph_{_safe(font)}_{ord(text):04x}",
            page=char.page,
            rect=bounds([char], GLYPH_PAD),
        )
        for key, char in best.items()
        for font, text in (key,)
    }
