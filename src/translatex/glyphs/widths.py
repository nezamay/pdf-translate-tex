"""Decide what a subset font really draws, from the advances the PDF declares for it.

A subsetter can rename glyphs and rewrite the encoding, but it cannot change the advance
widths: the page would stop lining up. So the widths are evidence the font's own claims
cannot contradict, and they are stated per code right in the font dictionary.

The test fits one free scale factor — the reference is a face of the same broad design,
not the original — and asks which reading agrees. Two references are used and both have to
reach the same verdict by a clear margin; anything less is a tie, and a tie leaves the
declared reading alone. Nothing here overrides a font that was telling the truth.

Every reading is scored on the SAME codes. Scoring each on whatever codes it happens to
cover compares medians drawn from different samples, which decides nothing — an early
version of this did exactly that and produced verdicts that swapped when the reference
changed.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from dataclasses import field

import pymupdf

from translatex.glyphs.readings import DECLARED
from translatex.glyphs.readings import readings

#: Base-14 faces shipped with pymupdf, so the test needs no system fonts. Serif and sans
#: are far enough apart in design that agreeing on a verdict means something.
REFERENCE_FONTS = ("tiro", "helv")

#: Below this many comparable codes the median is not worth reading. Three was too few:
#: a three-glyph subset of a script face was "corrected" into Greek on noise alone.
MIN_SAMPLE = 5

#: The runner-up's error must be at least this many times the winner's, on every
#: reference. Accepting a verdict that only one reference found convincing let two wrong
#: corrections through on the corpus.
MIN_MARGIN = 2.0

#: The winning reading has to explain the widths, not merely explain them least badly.
#: A bracket-building symbol face scored 0.15 for both readings and was neither.
MAX_WINNER_ERROR = 0.08

#: And the declared reading has to actually fail somewhere. A face whose own encoding
#: already fits has nothing to correct, however well an alternative also fits.
MIN_DECLARED_ERROR = 0.12

_FIRST_CHAR = re.compile(r"/FirstChar\s+(\d+)")
_WIDTHS = re.compile(r"/Widths\s*\[([^\]]*)\]")


@dataclass(frozen=True)
class FontVerdict:
    """What a font turned out to be, and how strongly."""

    font: str
    reading: str = DECLARED
    errors: dict[str, dict[str, float]] = field(default_factory=dict)
    overrides: dict[int, str] = field(default_factory=dict)
    unexplained: frozenset[int] = frozenset()

    @property
    def corrected(self) -> bool:
        return bool(self.overrides)


def declared_widths(doc: pymupdf.Document, xref: int) -> dict[int, float]:
    """The /Widths array as a code -> advance map, zero entries dropped."""
    obj = doc.xref_object(xref, compressed=True)
    first, widths = _FIRST_CHAR.search(obj), _WIDTHS.search(obj)
    if not (first and widths):
        return {}
    start = int(first.group(1))
    return {
        start + i: w
        for i, w in enumerate(float(v) for v in widths.group(1).split())
        if w
    }


def _advance(font: pymupdf.Font, char: str) -> float:
    """The reference advance for `char`, per 1000 units of em, or 0 when absent."""
    if not font.has_glyph(ord(char)):
        return 0.0
    return font.glyph_advance(ord(char)) * 1000.0


def _fit_error(pairs: list[tuple[float, float]]) -> float:
    """Median relative disagreement after the best single scale factor."""
    scale = statistics.median(declared / ref for declared, ref in pairs)
    return statistics.median(
        abs(declared - scale * ref) / (scale * ref) for declared, ref in pairs
    )


def _score(widths: dict[int, float], font: pymupdf.Font) -> dict[str, float]:
    """Per-reading median error, all readings measured on the same codes."""
    candidates = {code: readings(code) for code in widths}
    names = set().union(*candidates.values()) if candidates else set()
    if len(names) < 2:
        return {}

    common = [
        code
        for code, options in candidates.items()
        if len(options) == len(names) and all(_advance(font, c) for c in options.values())
    ]
    if len(common) < MIN_SAMPLE:
        return {}
    return {
        name: _fit_error([(widths[c], _advance(font, candidates[c][name])) for c in common])
        for name in names
    }


def decide(font_name: str, widths: dict[int, float]) -> FontVerdict:
    """Weigh every reading of `widths` and return the one the evidence supports."""
    errors = {}
    winners = set()
    declared_failed = False
    for reference in REFERENCE_FONTS:
        scored = _score(widths, pymupdf.Font(reference))
        if not scored:
            winners.add(None)
            continue
        errors[reference] = scored
        best, runner_up = sorted(scored, key=scored.get)[:2]
        margin = scored[runner_up] / max(scored[best], 1e-9)
        winners.add(
            best
            if margin >= MIN_MARGIN and scored[best] <= MAX_WINNER_ERROR
            else None
        )
        declared_failed |= scored.get(DECLARED, 0.0) >= MIN_DECLARED_ERROR

    # Every reference has to reach the same verdict on its own, the winner has to fit in
    # absolute terms, and the declared reading has to have failed somewhere. Each of the
    # three gates caught a different wrong correction when the corpus was measured, and
    # a missed correction only leaves text as bad as it already was, while a wrong one
    # silently rewrites text that was right.
    won = winners.pop() if len(winners) == 1 else None
    if won in (None, DECLARED) or not declared_failed:
        return FontVerdict(font_name, DECLARED, errors, {}, _unexplained(widths, DECLARED))

    overrides = {
        code: char
        for code in widths
        if (char := readings(code).get(won)) and char != chr(code)
    }
    return FontVerdict(font_name, won, errors, overrides, _unexplained(widths, won))


def _private(code: int) -> bool:
    """Whether a code point can only be a private arrangement, never text.

    A C0 control and a Private Use Area code point are both cases where the font has
    stopped claiming to say anything in Unicode at all — bracket halves, radical parts,
    stacked-fraction pieces. The test is per code and not per font: a Times face in the
    corpus uses sixteen such codes among eighty-three, and condemning the whole font for
    them would crop twenty thousand characters of ordinary body text.
    """
    return code < 0x20 or 0xE000 <= code <= 0xF8FF


def _unexplained(widths: dict[int, float], reading: str) -> frozenset[int]:
    """Codes the winning reading leaves without a believable character.

    Two kinds end up here: a private arrangement, which no encoding makes into text, and
    a code the winning reading does not cover in a font the evidence says was lying.
    Neither needs identifying to be handled — a fragment containing one is reproduced as
    a picture rather than transcribed.

    What this cannot catch is a legitimate code point drawn as something else: the same
    corpus has faces where '1/4' is an equals sign and 'thorn' a plus. Those are ordinary
    Unicode characters with ordinary widths, so no evidence inside the font contradicts
    them. Only the shape or the surrounding formula can, and neither is available here.
    """
    return frozenset(
        code
        for code in widths
        if _private(code) or (reading != DECLARED and reading not in readings(code))
    )


def used_codes(doc: pymupdf.Document) -> dict[str, set[int]]:
    """Codes actually drawn per font, so unused /Widths entries do not dilute a fit."""
    out: dict[str, set[int]] = {}
    for page in doc:
        for block in page.get_text("rawdict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    name = span["font"].split("+")[-1]
                    out.setdefault(name, set()).update(
                        ord(c["c"]) for c in span["chars"] if c["c"].strip()
                    )
    return out


def decide_fonts(doc: pymupdf.Document) -> dict[str, FontVerdict]:
    """Weigh every font in `doc`, keyed by its name without the subset prefix.

    Every font is tested, not a hand-listed family: a name pattern only recognises the
    publishers already seen, while the widths answer for any of them.
    """
    drawn = used_codes(doc)
    verdicts: dict[str, FontVerdict] = {}
    for page in doc:
        for xref, _ext, _type, base, _name, _enc in page.get_fonts():
            font_name = base.split("+")[-1]
            if font_name in verdicts:
                continue
            widths = {
                code: w
                for code, w in declared_widths(doc, xref).items()
                if code in drawn.get(font_name, ())
            }
            if widths:
                verdicts[font_name] = decide(font_name, widths)
    return verdicts
