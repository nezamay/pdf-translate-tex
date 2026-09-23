"""Every character on a page, with the glyph corrections already applied.

This is the one place that turns a PDF's text layer into something the rest of the tool
can trust. Two things happen here that nothing downstream should have to repeat:

  * a font the width test convicted has its codes rewritten, so omega arrives as omega;
  * a glyph nobody could identify is marked unreadable rather than guessed at, and a
    fragment holding one is reproduced as a picture later instead of transcribed.

Marking is deliberately not the same as dropping. The character keeps its box and its
place in the line, because the crop that replaces it needs both.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from translatex.glyphs import decide_fonts
from translatex.glyphs.widths import FontVerdict
from translatex.pdfin.layout import column_of
from translatex.pdfin.layout import columns
from translatex.pdfin.fonts import bare_name
from translatex.pdfin.fonts import family
from translatex.pdfin.fonts import style_from_name

# pymupdf's span flags; only the two we cannot get anywhere else.
_FLAG_ITALIC = 1 << 1
_FLAG_BOLD = 1 << 4


@dataclass(frozen=True)
class Char:
    """One drawn character, after the font's claims have been checked."""

    text: str
    bbox: tuple[float, float, float, float]
    page: int
    font: str
    size: float
    bold: bool = False
    italic: bool = False
    readable: bool = True

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]


def _style(span: dict) -> tuple[bool, bool]:
    """Bold and italic, from the descriptor when it speaks and the name when it does not."""
    flags = span.get("flags", 0)
    bold = bool(flags & _FLAG_BOLD)
    italic = bool(flags & _FLAG_ITALIC)
    if bold or italic:
        return bold, italic
    return style_from_name(span["font"])


#: Typographic ligatures are one glyph but several letters. They have to be spelled out
#: before anything reads the text: "Identiﬁer" does not match "identifier", and a
#: translator handed "signiﬁcant" is being handed a word that is not in any dictionary.
#: The character keeps its single box, because on the page it really is one mark.
LIGATURES = str.maketrans({
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\ufb05": "st", "\ufb06": "st",
})


def spell_out(text: str) -> str:
    """The same text with its ligatures written as the letters they stand for."""
    return text.translate(LIGATURES)


@dataclass(frozen=True)
class Line:
    """One drawn line of text, as the page laid it out."""

    chars: tuple[Char, ...]
    page: int
    block: int
    index: int

    @property
    def text(self) -> str:
        return spell_out("".join(c.text for c in self.chars))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [c.bbox for c in self.chars]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )


def read_lines(
    doc: pymupdf.Document,
    verdicts: dict[str, FontVerdict] | None = None,
) -> list[Line]:
    """Every line in `doc`, corrected and marked, in the order the page draws it.

    Spaces come from pymupdf, which synthesises them from the inter-character gaps —
    these pages carry no space glyph of their own. That is worth stating because the
    obvious alternative, re-deriving a gap threshold, is a known source of silent damage:
    a threshold one step too wide turns "σ_yd cos" into "rydcos" and nothing complains.
    """
    if verdicts is None:
        verdicts = decide_fonts(doc)

    out: list[Line] = []
    for page in doc:
        for block_no, block in enumerate(page.get_text("rawdict")["blocks"]):
            for line_no, line in enumerate(block.get("lines", [])):
                chars: list[Char] = []
                for span in line["spans"]:
                    verdict = verdicts.get(bare_name(span["font"]))
                    bold, italic = _style(span)
                    for ch in span["chars"]:
                        text = ch["c"]
                        readable = True
                        if verdict is not None:
                            # A convicted font decoded to the raw code in the first
                            # place — that is what being unreadable means here — so the
                            # code point of what pymupdf returned is the key to use.
                            code = ord(text)
                            text = verdict.overrides.get(code, text)
                            readable = code not in verdict.unexplained
                        chars.append(
                            Char(
                                text=text,
                                bbox=tuple(ch["bbox"]),
                                page=page.number,
                                font=family(span["font"]),
                                size=span["size"],
                                bold=bold,
                                italic=italic,
                                readable=readable,
                            )
                        )
                if chars:
                    out.append(Line(tuple(chars), page.number, block_no, line_no))
    return stitch(out, doc[0].rect.width if len(doc) else 0.0)


#: Two fragments this close, measured in body sizes, are one line broken by the reader
#: rather than by the typesetter. A column gutter is several times wider.
FRAGMENT_GAP_EM = 3.0

#: Two fragments overlapping vertically by at least this much of the shorter one are on
#: the same line. Comparing the boxes' bottoms instead does not work: a fragment carrying
#: a superscript or a tall bracket is raised, so "[n_ty n_tz]^T" and the words beside it
#: differ by nine points though they are one line of one sentence.
LINE_OVERLAP = 0.5


def stitch(lines: list[Line], page_width: float) -> list[Line]:
    """Put back together the lines pymupdf cut at a wide word gap.

    A justified line stretched to fill its measure has word gaps wide enough that pymupdf
    reports each word as a line of its own: one line of this corpus came back as six,
    "inappropriate / guidance / strategies, / and / target / maneuvers.", all at the same
    baseline in the same block. Everything downstream then treats each word as a
    paragraph, because each one starts further right than the last and that is what an
    indent looks like.

    Fragments join when they share a page and a baseline and sit within a few body sizes
    of each other. The block they were filed under is deliberately not part of that: a
    block is the publisher's own division and it cuts across lines as readily as along
    them. "The LOS vector direction nt = ntx" and "nty ntz]T, which con-" are one line of
    one sentence, filed as two blocks because the subscripts ride higher, and keeping
    them apart made the second half look like a display equation standing on its own.

    The horizontal condition is what keeps the two columns apart, since a gutter is
    several times wider than any word gap.
    """
    # The columns have to be known here. A gutter can be narrower than a stretched word
    # gap — twelve points against a threshold of thirty on one paper — so a purely
    # horizontal test joins the two columns of a page into single lines.
    bands: dict[int, list[tuple[float, float]]] = {}
    for page in {line.page for line in lines}:
        bands[page] = columns(
            [line.bbox for line in lines if line.page == page], page_width
        )

    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda line: (line.page, line.bbox[1])):
        for row in reversed(rows):
            if (
                row[0].page == line.page
                and _shares_a_line(row, line)
                and column_of(row[0].bbox, bands[line.page])
                == column_of(line.bbox, bands[line.page])
            ):
                row.append(line)
                break
        else:
            rows.append([line])

    out: list[Line] = []
    for group in rows:
        row = sorted(group, key=lambda line: line.bbox[0])
        group = [row[0]]
        for line in row[1:]:
            size = max(c.size for c in group[-1].chars) or 10.0
            if line.bbox[0] - group[-1].bbox[2] <= FRAGMENT_GAP_EM * size:
                group.append(line)
            else:
                out.append(_merge(group))
                group = [line]
        out.append(_merge(group))
    return out


def _shares_a_line(row: list[Line], line: Line) -> bool:
    """Whether `line` sits on the same line of type as the fragments already in `row`."""
    top = min(existing.bbox[1] for existing in row)
    bottom = max(existing.bbox[3] for existing in row)
    overlap = min(bottom, line.bbox[3]) - max(top, line.bbox[1])
    shorter = min(bottom - top, line.bbox[3] - line.bbox[1])
    return shorter > 0 and overlap >= LINE_OVERLAP * shorter


def _merge(group: list[Line]) -> Line:
    """One line from fragments of it, with a space wherever a gap was."""
    if len(group) == 1:
        return group[0]
    chars: list[Char] = []
    for index, line in enumerate(group):
        if index:
            previous = chars[-1]
            chars.append(
                Char(
                    text=" ",
                    bbox=(previous.bbox[2], previous.bbox[1], line.bbox[0], previous.bbox[3]),
                    page=previous.page,
                    font=previous.font,
                    size=previous.size,
                )
            )
        chars.extend(line.chars)
    first = group[0]
    return Line(tuple(chars), first.page, first.block, first.index)


def read_chars(
    doc: pymupdf.Document,
    verdicts: dict[str, FontVerdict] | None = None,
) -> list[Char]:
    """Every character in `doc`, corrected and marked, in the order the page draws it."""
    return [c for line in read_lines(doc, verdicts) for c in line.chars]


def unreadable_runs(chars: list[Char]) -> list[list[Char]]:
    """Maximal stretches of unreadable characters, each a candidate for one crop.

    Neighbouring unreadable glyphs are grouped because they are almost always one broken
    construction — a radical, a bracket pair, a stacked fraction — and cropping it whole
    keeps it looking like itself.
    """
    runs: list[list[Char]] = []
    current: list[Char] = []
    for char in chars:
        if char.readable:
            if current:
                runs.append(current)
                current = []
            continue
        if current and (current[-1].page != char.page or not _adjacent(current[-1], char)):
            runs.append(current)
            current = []
        current.append(char)
    if current:
        runs.append(current)
    return runs


def _adjacent(left: Char, right: Char) -> bool:
    """Whether two characters sit close enough to belong to one construction."""
    gap = right.bbox[0] - left.bbox[2]
    baseline_shift = abs(right.bbox[3] - left.bbox[3])
    return gap < max(left.size, right.size) and baseline_shift < max(left.size, right.size)
