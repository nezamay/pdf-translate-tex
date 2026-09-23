"""Hiding the mathematics from the translator, and putting it back afterwards.

A translator handed "ka ¼ 2" will do something with it, and everything it can do is
wrong: translate the letter, respace the expression, decide the ¼ is a fraction. So the
maths comes out of the sentence before the sentence is sent, leaving a marker in its
place, and goes back in unchanged when the translation returns.

What counts as maths is settled by the page, not by the characters. These papers set
variables in a face the body never uses, so "the parameter ka was set" carries two
characters from another font and the rest from the text face. That is the whole test:
a character in a non-text face, or one nobody could identify, is maths.

The markers are `{v1}`, `{v2}`, … — the form the same translator has already been seen
to reproduce faithfully across a few hundred paragraphs, which is not a property worth
re-deriving with a prettier bracket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field

from translatex.pdfin.chars import Char

MARKER = re.compile(r"\{v(\d+)\}")

#: Characters that belong to an expression whenever they sit inside one, though they are
#: set in the text face: digits, the decimal point, and the operators a journal leaves in
#: roman type.
JOINS = set("0123456789.+-=<>/()[]|,")


@dataclass(frozen=True)
class Piece:
    """One stretch of maths, kept aside while its sentence is translated."""

    marker: str
    text: str
    chars: tuple[Char, ...]

    @property
    def readable(self) -> bool:
        return all(c.readable for c in self.chars)


@dataclass(frozen=True)
class Masked:
    """A sentence with its mathematics replaced by markers."""

    text: str
    pieces: tuple[Piece, ...] = field(default_factory=tuple)

    def restore(self, translated: str) -> str:
        """Put every piece back into a translation of `text`."""
        by_marker = {piece.marker: piece for piece in self.pieces}
        return MARKER.sub(
            lambda m: by_marker[m.group(0)].text if m.group(0) in by_marker else m.group(0),
            translated,
        )

    @property
    def markers_kept(self) -> bool:
        """Whether `text` still names every piece exactly once."""
        return sorted(MARKER.findall(self.text)) == sorted(
            MARKER.match(piece.marker).group(1) for piece in self.pieces
        )


#: A stretch of letters longer than this is prose set in an unusual face, not a variable.
#: Abstracts, keyword lists and pull quotes are all set in faces the body never uses, and
#: without this the whole abstract came back as one expression.
MAX_MATHS_LETTERS = 10

#: A letter this much larger than the text beside it is a drop cap, not a variable.
DROP_CAP_RATIO = 1.5


def is_maths(char: Char | None, text_fonts: frozenset[str]) -> bool:
    """Whether a character is a candidate for being part of an expression.

    A position with no character behind it — a space invented at a line break — belongs
    to the sentence, not to an expression.
    """
    if char is None:
        return False
    return not char.readable or char.font not in text_fonts


def _candidates(text: str, owners: list[Char | None], text_fonts: frozenset[str]) -> list[bool]:
    """Per position, whether it is maths after the two things the face alone gets wrong.

    A face that is not the body's is the first signal and a weak one on its own. Two
    corrections, both measured rather than guessed:

    Length. An abstract, a keyword list and a running head are all prose in a face the
    body never uses. Without a bound, a whole abstract came back as one expression. Ten
    letters is where a variable stops and a word begins.

    Size. A drop cap is set in a display face and is not maths either; it is the first
    letter of the word beside it. It is told apart by being far larger than the text it
    stands against, and by nothing else — the tempting test, that it touches a word, also
    catches every variable written hard against one, and "n denotes" would lose its n.
    """
    flags = [is_maths(owner, text_fonts) for owner in owners]
    body = [
        owner.size
        for owner, flag in zip(owners, flags, strict=True)
        if owner is not None and not flag
    ]
    ordinary = sorted(body)[len(body) // 2] if body else 0.0

    index = 0
    while index < len(flags):
        if not flags[index]:
            index += 1
            continue
        end = index
        while end < len(flags) and flags[end]:
            end += 1

        letters = sum(text[i].isalpha() for i in range(index, end))
        sizes = [owners[i].size for i in range(index, end) if owners[i] is not None]
        oversized = bool(ordinary) and sizes and min(sizes) >= DROP_CAP_RATIO * ordinary
        if letters > MAX_MATHS_LETTERS or oversized:
            for position in range(index, end):
                flags[position] = False
        index = end
    return flags


def _absorb_tails(text: str, runs: list[tuple[int, int]], known: frozenset[str]) -> list[tuple[int, int]]:
    """Take in letters written hard against a run, unless they spell a word.

    A subscript is set in the text face often enough that an expression ends mid-symbol:
    "oe −x" stops there and "eyeze" is left to be translated as if it were a word. It is
    not one, and the document itself says so — it spells no such word anywhere else.
    That is the guard, and it is the reason this can be done at all: "vector nt" wants
    the t, and a sentence running straight on from an expression does not want its word.
    """
    out: list[tuple[int, int]] = []
    for start, end in runs:
        cursor = end
        while cursor < len(text) and text[cursor].isalpha():
            cursor += 1
        tail = text[end:cursor]
        if tail and tail.lower() not in known:
            end = cursor
        out.append((start, end))
    return out


def _runs(text: str, owners: list[Char | None], text_fonts: frozenset[str],
          known: frozenset[str] = frozenset()) -> list[tuple[int, int]]:
    """Half-open ranges covering each stretch of mathematics.

    A run reaches across a space and over digits and operators, because "ka = 2" is one
    expression written with spaces in it, and cutting it at the spaces would hand the
    translator a stray "2" to make of what it will. It stops at the first letter set in
    the text face, which is where the sentence starts again.
    """
    flags = _candidates(text, owners, text_fonts)
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if not flags[index]:
            index += 1
            continue

        start = end = index
        cursor = index
        while cursor < len(text):
            if flags[cursor] or text[cursor] in JOINS:
                cursor += 1
                end = cursor
            elif text[cursor].isspace() and cursor + 1 < len(text) and (
                flags[cursor + 1] or text[cursor + 1] in JOINS
            ):
                cursor += 1
            else:
                break

        # A run must not end on the punctuation that closes the sentence around it.
        while end > start and text[end - 1] in ",.;:":
            end -= 1
        if end > start:
            runs.append((start, end))
        index = max(end, start + 1)
    return _bridge(text, _absorb_tails(text, runs, known))


#: Two stretches of maths this close, with no space between them, are one expression that
#: happens to have a character set in the text face in the middle of it — a subscript, a
#: comma inside a tuple. Left apart, "oe −x" and "eyeze" reach the translator as a word.
BRIDGE_GAP = 6


def _bridge(text: str, runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Join runs separated by a short gap holding no space."""
    if not runs:
        return runs
    merged = [runs[0]]
    for start, end in runs[1:]:
        last_start, last_end = merged[-1]
        gap = text[last_end:start]
        if len(gap) <= BRIDGE_GAP and not any(ch.isspace() for ch in gap):
            merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def mask(paragraph, text_fonts: frozenset[str]) -> Masked:
    """Replace every stretch of mathematics in a paragraph with a marker."""
    text, owners = paragraph.flatten()
    pieces: list[Piece] = []
    out: list[str] = []
    cut = 0
    for start, end in _runs(text, owners, text_fonts, paragraph.known_words):
        out.append(text[cut:start])
        marker = f"{{v{len(pieces) + 1}}}"
        seen: list[Char] = []
        for owner in owners[start:end]:
            if owner is not None and (not seen or seen[-1] is not owner):
                seen.append(owner)
        pieces.append(Piece(marker, text[start:end], tuple(seen)))
        out.append(marker)
        cut = end
    out.append(text[cut:])
    return Masked("".join(out), tuple(pieces))
