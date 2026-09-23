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

#: A line whose left edge sits this much further right than its neighbours starts a
#: paragraph. Measured in fractions of the body size, so it survives a change of scale.
INDENT_EM = 0.8

#: Lines further apart than this, relative to the body size, belong to different
#: paragraphs even when nothing else says so.
LEADING_EM = 1.8

#: A line ending this far short of the column's right edge ends a paragraph: justified
#: text only leaves that much white at the end of something.
SHORT_LINE_EM = 2.0


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
        out = ""
        for line in self.lines:
            piece = line.text.strip()
            head = _LINE_END_HYPHEN.search(out)
            tail = _LINE_START_WORD.match(piece)
            if head and tail and piece[:1].islower():
                joined = join_hyphenated(
                    head.group(1), tail.group(1), self.known_words, mark=out[head.end() - 1]
                )
                out = out[: head.start()] + joined + piece[tail.end() :]
            elif out:
                out = f"{out} {piece}"
            else:
                out = piece
        return out

    @property
    def words(self) -> list[Word]:
        return [w for line in self.lines for w in split_words(line)]

    @property
    def readable(self) -> bool:
        return all(w.readable for w in self.words)


def _body_size(lines: list[Line]) -> float:
    sizes = [c.size for line in lines for c in line.chars if c.size]
    return max(sizes) if sizes else 10.0


def _starts_paragraph(previous: Line, line: Line, right_edge: float) -> bool:
    """Whether `line` opens a new paragraph rather than continuing `previous`."""
    if line.page != previous.page or line.block != previous.block:
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


def paragraphs(lines: list[Line]) -> list[Paragraph]:
    """Group lines into paragraphs, one publisher block at a time."""
    if not lines:
        return []

    known = vocabulary(lines)

    # The column edge is the widest line of the block, not of the page: measuring against
    # the page would make every line of a two-column layout look like the end of a
    # paragraph. Collected once, because a paper runs to a few thousand lines.
    right_edges: dict[tuple[int, int], float] = {}
    for line in lines:
        key = (line.page, line.block)
        right_edges[key] = max(right_edges.get(key, 0.0), line.bbox[2])

    out: list[Paragraph] = []
    current: list[Line] = [lines[0]]
    for previous, line in zip(lines, lines[1:], strict=False):
        if _starts_paragraph(previous, line, right_edges[(line.page, line.block)]):
            out.append(Paragraph(tuple(current), known))
            current = [line]
        else:
            current.append(line)
    out.append(Paragraph(tuple(current), known))
    return out
