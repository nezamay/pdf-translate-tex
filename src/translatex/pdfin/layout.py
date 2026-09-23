"""Where the columns of a page are.

Low enough in the stack that both the line reader and the region finder can ask. The line
reader needs it because a gutter can be narrower than a stretched word gap — twelve points
against a threshold of thirty on one paper — so without knowing where the columns are it
joins the two of them into one line.
"""

from __future__ import annotations

#: A position carrying fewer than this share of what a column typically carries is in a
#: gutter. Measured against the median rather than the maximum: a page whose title and
#: abstract run the full measure puts several lines through the gutter, and a threshold
#: set as a fraction of the busiest position is cleared by them.
GUTTER_DEPTH = 0.5

#: A band narrower than this share of the page is a sidebar or a stamp, not a column.
MIN_COLUMN_SHARE = 0.1

#: And a gap narrower than this share of the page is a word space, not a gutter. Without
#: it, a handful of fragments with three points between them were reported as two
#: columns, and the two halves of one line were never joined.
MIN_GUTTER_SHARE = 0.015


def columns(boxes: list[tuple[float, float, float, float]],
            page_width: float) -> list[tuple[float, float]]:
    """The horizontal bands the text of one page occupies, left to right.

    Found from how MANY boxes cover each position, not from whether any does. A single
    full-width line — a spanning caption, a wide equation, a footer rule — bridges the
    gutter, and a rule that cuts wherever coverage reaches zero reports one column across
    the whole page. Counting instead, the gutter stays a valley: a hundred lines stop at
    it and one crosses.
    """
    if not boxes or page_width <= 0:
        return []

    width = int(page_width) + 1
    cover = [0] * width
    for box in boxes:
        for x in range(max(0, int(box[0])), min(width, int(box[2]) + 1)):
            cover[x] += 1

    covered = sorted(value for value in cover if value)
    if not covered:
        return []
    threshold = GUTTER_DEPTH * covered[len(covered) // 2]

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

    # Close the gaps too narrow to be gutters before judging what is a column.
    gutter = MIN_GUTTER_SHARE * page_width
    joined: list[list[float]] = []
    for left, right in bands:
        if joined and left - joined[-1][1] < gutter:
            joined[-1][1] = right
        else:
            joined.append([left, right])

    smallest = MIN_COLUMN_SHARE * page_width
    return [(left, right) for left, right in joined if right - left >= smallest]


def column_of(box: tuple[float, float, float, float],
              bands: list[tuple[float, float]]) -> tuple[float, float] | None:
    """The band a box sits in, by the largest overlap."""
    best, overlap = None, 0.0
    for band in bands:
        shared = min(box[2], band[1]) - max(box[0], band[0])
        if shared > overlap:
            best, overlap = band, shared
    return best
