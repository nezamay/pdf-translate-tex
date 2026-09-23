"""Candidate meanings for a code whose font will not explain it.

A subset font states an /Encoding and carries an embedded charset, and both can be wrong.
The Advent maths faces used by several journals name their glyphs after Latin letters and
draw Greek ones: the charset of one such subset reads `slash, a, e, g, p, r, w, x` while
the page shows phi, alpha, epsilon, eta, pi, sigma, psi, omega. Nothing inside the font
tells the two apart, so a reading has to be proposed and then tested against evidence the
subsetter could not forge — see `translatex.glyphs.widths`.

The Greek reading here is positional: the n-th letter of the Latin alphabet stands for the
n-th letter of the Greek one. That is not a guess about one font, it is what the subsets
show — seven of seven glyphs in the sample, confirmed independently by their widths.
"""

from __future__ import annotations

GREEK_LOWER_FIRST = 0x3B1
GREEK_UPPER_FIRST = 0x391

# Final sigma sits between rho and sigma in the Unicode block without being a letter of
# the alphabet, so everything from the eighteenth letter on is one code point further
# along than its index suggests.
FINAL_SIGMA_INDEX = 18

GREEK_LETTERS = 24

#: The reading a PDF's own /Encoding asserts, and the one a caller falls back to.
DECLARED = "declared"
GREEK = "greek"


def greek_letter(index: int, upper: bool = False) -> str:
    """The `index`-th letter of the Greek alphabet, counting alpha as 1."""
    if not 1 <= index <= GREEK_LETTERS:
        raise ValueError(f"no Greek letter at index {index}")
    base = GREEK_UPPER_FIRST if upper else GREEK_LOWER_FIRST
    return chr(base + index - 1 + (index >= FINAL_SIGMA_INDEX))


def readings(code: int) -> dict[str, str]:
    """Every character `code` might stand for, keyed by the reading that claims it.

    `DECLARED` is always present. Readings that have nothing to say about this code are
    simply absent, which is what lets the caller score them on a common set of codes.
    """
    char = chr(code)
    out = {DECLARED: char}
    if "a" <= char <= "x":
        out[GREEK] = greek_letter(code - ord("a") + 1)
    elif "A" <= char <= "X":
        out[GREEK] = greek_letter(code - ord("A") + 1, upper=True)
    return out
