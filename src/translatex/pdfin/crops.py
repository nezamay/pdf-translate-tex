"""Cutting pieces of the original page out to be placed in the new one.

Three things get reproduced rather than rewritten: a figure, which was never text; a
display equation, whose fraction bars and matrix rules are drawn strokes that the text
layer does not contain; and a glyph nobody could identify, which has to appear as itself
because there is nothing to write instead.

A large region is not written out at all. It is a page and a rectangle, and the document
shows it with `\\includegraphics[page=N,trim=...,clip]{original.pdf}`, straight from the
source sitting in the same folder. That keeps it vector, costs no file, and cannot drift
out of step with what it came from. Extracting it instead was measured and rejected: every
extracted region carries a copy of its page's resources, a flat 56 kB whether it holds a
whole figure or one comma.

A glyph goes out as a picture, because the same accounting reverses at that size. See
`save_glyph` for the numbers; the short of it is that a mark costs a few hundred bytes as
a picture and 41 kB as a reference, and a figure the other way round.

Glyph regions are found once per distinct glyph, not once per occurrence. Measured across
twenty papers: 2322 unreadable characters are 124 distinct glyphs, fifteen to twenty-two
per paper, each reappearing nineteen times on average.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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

    Nothing is written out — the region is shown from the original, which stays vector and
    costs no file. Worth knowing before using this on something small: each inclusion
    embeds a copy of the source page, about 41 kB, and xdvipdfmx does not share it between
    inclusions even when they name the same page. See `save_glyph`.

    The y axis is flipped on the way: pymupdf counts down from the top, graphicx up from
    the bottom.
    """
    page = doc[crop.page].rect
    left, top, right, bottom = crop.rect
    return (left, page.height - bottom, page.width - right, top)


#: Resolution for a glyph picture. A mark a few points wide comes to a few hundred bytes
#: here and stays sharp well past what printing resolves.
GLYPH_DPI = 1200


def save_glyph(doc: pymupdf.Document, crop: Crop, directory: Path) -> Path:
    """Render one glyph to its own small picture and return where it landed.

    Small reproductions go out as pictures while large ones are shown from the original,
    and the split is not aesthetic. Measured on a paper with eighteen distinct glyphs,
    each included six times:

        108 inclusions by trim from the original   742 kB
        108 inclusions from one shared crop PDF    742 kB
        108 inclusions from a picture per glyph     42 kB

    xdvipdfmx embeds the source page once per inclusion and never shares it, even when
    every inclusion names the same page — but it does reuse an identical picture file, so
    a glyph appearing nineteen times costs what it costs once. The eighteen pictures come
    to 32 kB together. For a figure the accounting reverses: one inclusion, large area,
    and the vector original is both smaller and better.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{crop.name}.png"
    rect = pymupdf.Rect(*crop.rect) & doc[crop.page].rect
    doc[crop.page].get_pixmap(clip=rect, dpi=GLYPH_DPI, alpha=False).save(path)
    return path


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
