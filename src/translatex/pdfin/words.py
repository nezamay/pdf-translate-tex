"""Words, and the paragraphs they run on into.

Splitting a line into words needs no gap arithmetic here: pymupdf synthesises the spaces
these pages do not carry, so a word is simply a run between them. What does need deciding
is where a paragraph ends, because the page only knows about lines and the publisher's
own blocks, and both lie — a block breaks at a column edge, and a line break inside a
sentence looks exactly like the end of one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from translatex.pdfin.chars import Char
from translatex.pdfin.chars import Line
from translatex.pdfin.chars import spell_out
from translatex.pdfin.layout import column_of
from translatex.pdfin.layout import columns

#: A line whose left edge sits this much further right than its neighbours starts a
#: paragraph. Measured in fractions of the body size, so it survives a change of scale.
INDENT_EM = 0.8

#: Lines further apart than this, relative to the body size, belong to different
#: paragraphs even when nothing else says so.
LEADING_EM = 1.8

#: A line ending this far short of the column's right edge ends a paragraph: justified
#: text only leaves that much white at the end of something.
SHORT_LINE_EM = 2.0

#: An equation number set on a line of its own. It belongs to the equation beside it, not
#: to the sentence under it: grouped with the sentence, its line sits on the equation's
#: own line, and the equation then decides it is sharing a line with prose and refuses to
#: be cropped at all.
EQUATION_NUMBER_LINE = re.compile(r"^\(\d+[a-z]?\)$")


@dataclass(frozen=True)
class Word:
    """A run of characters between two spaces."""

    chars: tuple[Char, ...]

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

    @property
    def readable(self) -> bool:
        return all(c.readable for c in self.chars)

    @property
    def size(self) -> float:
        return max(c.size for c in self.chars)

    @property
    def italic(self) -> bool:
        return all(c.italic for c in self.chars)

    @property
    def bold(self) -> bool:
        return all(c.bold for c in self.chars)


def _spell(line: Line) -> tuple[str, list[Char | None]]:
    """A line's text with its ligatures spelled out, and the character behind each letter.

    A ligature is one mark standing for two letters, so both letters point back at it.
    """
    chars = list(line.chars)
    while chars and chars[0].text.isspace():
        chars.pop(0)
    while chars and chars[-1].text.isspace():
        chars.pop()

    text = ""
    owners: list[Char | None] = []
    for char in chars:
        spelled = spell_out(char.text)
        text += spelled
        owners += [char] * len(spelled)
    return text, owners


def split_words(line: Line) -> list[Word]:
    """The line's words, in order, with the spaces dropped."""
    words: list[Word] = []
    current: list[Char] = []
    for char in line.chars:
        if char.text.isspace():
            if current:
                words.append(Word(tuple(current)))
                current = []
            continue
        current.append(char)
    if current:
        words.append(Word(tuple(current)))
    return words


SOFT_HYPHEN = "­"

_WORD = re.compile(r"[^\W\d_][^\W\d_-]*(?:-[^\W\d_]+)*", re.UNICODE)
_LINE_END_HYPHEN = re.compile(rf"([^\W\d_-]+)[-{SOFT_HYPHEN}]$", re.UNICODE)
_LINE_START_WORD = re.compile(r"^([^\W\d_]+)", re.UNICODE)


def vocabulary(lines: list[Line]) -> frozenset[str]:
    """Every word the document spells out whole, lowercased.

    This is the only dictionary available and it is the right one: whether a line-final
    hyphen belongs to the word is a fact about this document's own typesetting.

    The halves of a broken word are excluded, and that exclusion is the whole point.
    Counting them made the dictionary answer its own question: "solute" and "passing"
    became words because "ab-solute" and "encom-passing" had been split, and the rule
    then kept the very hyphens it was meant to remove.
    """
    known: set[str] = set()
    for index, line in enumerate(lines):
        text = line.text.strip()
        broken_head = bool(_LINE_END_HYPHEN.search(text))
        previous = lines[index - 1].text.strip() if index else ""
        broken_tail = bool(_LINE_END_HYPHEN.search(previous)) and text[:1].islower()

        matches = list(_WORD.finditer(text))
        if broken_head and matches:
            matches.pop()
        if broken_tail and matches:
            matches.pop(0)
        for match in matches:
            word = match.group(0).lower()
            known.add(word)
            # The parts of a compound count as words in their own right. Without this
            # "weight" is unknown in a paper that only ever writes "thrust-to-weight",
            # so a break at its last hyphen looks like a broken word and closes up.
            if "-" in word:
                known.update(part for part in word.split("-") if part)
    return frozenset(known)


def join_hyphenated(head: str, tail: str, known: frozenset[str], mark: str = "-") -> str:
    """Whether a line-final hyphen survives the join, decided by the document itself.

    Unicode does distinguish the two cases — U+00AD is the typesetter's discretionary
    break and U+002D the hyphen someone wrote — but the distinction does not reach a PDF.
    The soft hyphen is an instruction to the typesetter, and once it has broken the line
    it draws the ordinary hyphen glyph; the font has only the one, and its ToUnicode maps
    it to U+002D. Measured across the corpus: 1450 line-final hyphens and 2735 inside
    lines, every one of them U+002D, and not a single U+00AD anywhere. So the mark is
    honoured when it is there and the document is asked when it is not.

    Asking the document works. It answers 1091 of 1439 breaks outright: 983 whose fused
    form it spells out elsewhere against 108 whose hyphenated form it does. For the rest
    the tail decides — "equipped" and "plane" are words, so "camera-equipped" and
    "two-plane" keep their hyphen, while "uously" and "passing" are not, so
    "continuously" and "encompassing" close up.

    Scored on the 869 corpus breaks a system word list can settle:

        rule                        accuracy   breaks    compounds   spurious hyphens
        fused / hyphenated / tail      98.5%   678/680     165/189                  2
        fused / hyphenated only        89.3%   680/680      96/189                  0
        always join                    78.3%   680/680       0/189                  0
        always keep                    21.7%     0/680     189/189                680

    A further 17 disagreements are not counted as errors: there the document spells the
    word fused somewhere of its own accord, and following the author beats following a
    word list. That is not a dodge — the corpus writes "nonsingular" in three papers and
    "non-singular" in two, "onboard" in seven and "on-board" in one. Both spellings are
    current, so there is no fact for the dictionary to be right about, only a house style.

    The tail step is worth having because of the last column, not the first: it buys 69
    compounds for two spurious hyphens. The asymmetry is the point — fusing a compound
    gives "multiagent", which any reader or translator still understands, while splitting
    a word gives "in-creasingly", which invites being read as a compound and translated
    as one. A fourth step, treating a head the document hyphenates elsewhere as a prefix,
    was measured and dropped: nine more compounds for two more spurious hyphens is four
    times the worse trade.
    """
    if mark == SOFT_HYPHEN:
        return head + tail
    if (head + tail).lower() in known:
        return head + tail
    if f"{head}-{tail}".lower() in known:
        return f"{head}-{tail}"
    return f"{head}-{tail}" if tail.lower() in known else head + tail


@dataclass(frozen=True)
class Paragraph:
    lines: tuple[Line, ...]
    known_words: frozenset[str] = frozenset()

    @property
    def text(self) -> str:
        """The paragraph as one string, with hyphenated line breaks healed."""
        return self.flatten()[0]

    def flatten(self) -> tuple[str, list[Char | None]]:
        """The paragraph's text, and the character each position came from.

        One place joins the lines, because anything reading the text and anything reading
        the characters have to agree about where the words are. Built separately, they
        did not: the joined text put a space at every line end and the raw run of
        characters did not, so masking saw "multicoptersequipped".

        A position with no character behind it — a space invented at a line break — is
        None, and so is a hyphen the healing removed.
        """
        out = ""
        owners: list[Char | None] = []

        for line in self.lines:
            piece, piece_owners = _spell(line)
            if not piece:
                continue

            head = _LINE_END_HYPHEN.search(out)
            tail = _LINE_START_WORD.match(piece)
            if head and tail and piece[:1].islower():
                joined = join_hyphenated(
                    head.group(1), tail.group(1), self.known_words, mark=out[head.end() - 1]
                )
                kept_mark = len(joined) > len(head.group(1)) + len(tail.group(1))
                mark_owner = owners[head.end() - 1]
                out = out[: head.start(1)] + joined + piece[tail.end() :]
                owners = (
                    owners[: head.start(1)]
                    + owners[head.start(1) : head.end(1)]
                    + ([mark_owner] if kept_mark else [])
                    + piece_owners[: tail.end()]
                    + piece_owners[tail.end() :]
                )
                continue

            if out:
                out += " "
                owners.append(None)
            out += piece
            owners += piece_owners
        return out, owners

    @property
    def words(self) -> list[Word]:
        return [w for line in self.lines for w in split_words(line)]

    @property
    def readable(self) -> bool:
        return all(w.readable for w in self.words)


def _body_size(lines: list[Line]) -> float:
    sizes = [c.size for line in lines for c in line.chars if c.size]
    return max(sizes) if sizes else 10.0


def _starts_paragraph(previous: Line, line: Line, right_edge: float,
                      column: tuple[float, float] | None,
                      previous_column: tuple[float, float] | None) -> bool:
    """Whether `line` opens a new paragraph rather than continuing `previous`.

    The column decides, not the publisher's block. A block is the publisher's own
    division: it cuts across lines as readily as along them, and once lines are stitched
    back together the block a stitched line carries is whichever fragment came first.
    Keying on it then started a new paragraph at almost every line.
    """
    if line.page != previous.page or column != previous_column:
        return True

    if (EQUATION_NUMBER_LINE.match(previous.text.strip())
            or EQUATION_NUMBER_LINE.match(line.text.strip())):
        return True

    # A word broken across the break has not finished, so nothing geometric can end the
    # paragraph here — least of all the short-line rule, since a line ending mid-word is
    # exactly the kind that comes up short.
    if _LINE_END_HYPHEN.search(previous.text.strip()) and line.text.strip()[:1].islower():
        return False

    size = max(_body_size([previous]), 1.0)
    prev_box, box = previous.bbox, line.bbox

    if box[1] - prev_box[3] > LEADING_EM * size:
        return True
    if box[0] - prev_box[0] > INDENT_EM * size:
        return True
    # A justified column fills every line but the last, so a short one ends the thought.
    return right_edge - prev_box[2] > SHORT_LINE_EM * size


def paragraphs(lines: list[Line], page_width: float = 0.0) -> list[Paragraph]:
    """Group lines into paragraphs, one column at a time."""
    if not lines:
        return []

    known = vocabulary(lines)

    bands: dict[int, list[tuple[float, float]]] = {}
    for page in {line.page for line in lines}:
        boxes = [line.bbox for line in lines if line.page == page]
        bands[page] = columns(boxes, page_width or max(box[2] for box in boxes) * 1.08)

    of_line = {
        id(line): column_of(line.bbox, bands[line.page]) for line in lines
    }

    # Into the order a reader meets them, before anything asks what follows what. The
    # order a PDF stores its lines in jumps between the columns constantly: left in file
    # order, "this line is in another column" fired 713 times on an eleven-page paper
    # with two columns, and every one of them started a paragraph.
    lines = sorted(
        lines,
        key=lambda line: (line.page, (of_line[id(line)] or (line.bbox[0], 0.0))[0],
                          line.bbox[1]),
    )

    # The column's own right edge, from the band. Taking the widest line in the column
    # instead let one full-measure line — a title, a spanning caption — stand in for the
    # measure: on the opening page it put the edge 262 points beyond where the text
    # actually ends, so every line of the abstract looked short and became a paragraph.
    def right_edge(line: Line) -> float:
        band = of_line[id(line)]
        if band is not None:
            return band[1]
        page_lines = [x.bbox[2] for x in lines if x.page == line.page]
        return max(page_lines) if page_lines else line.bbox[2]

    out: list[Paragraph] = []
    current: list[Line] = [lines[0]]
    for previous, line in zip(lines, lines[1:], strict=False):
        column = of_line[id(line)]
        if _starts_paragraph(previous, line, right_edge(line),
                             column, of_line[id(previous)]):
            out.append(Paragraph(tuple(current), known))
            current = [line]
        else:
            current.append(line)
    out.append(Paragraph(tuple(current), known))
    return out
