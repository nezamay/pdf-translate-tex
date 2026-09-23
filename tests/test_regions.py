import pymupdf
import pytest

from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import Paragraph
from translatex.pdfin.regions import columns
from translatex.pdfin.regions import figure_regions
from translatex.pdfin.roles import Role

PAGE_WIDTH = 600.0
LEFT = (50.0, 280.0)
RIGHT = (320.0, 550.0)


def line(x0: float, x1: float, *, y: float = 100.0, page: int = 0, block: int = 0,
         index: int = 0, text: str = "") -> Line:
    body = text or "x" * max(1, int((x1 - x0) / 5))
    step = (x1 - x0) / len(body)
    chars = tuple(
        Char(text=ch, bbox=(x0 + i * step, y, x0 + (i + 1) * step, y + 10.0),
             page=page, font="Text", size=10.0)
        for i, ch in enumerate(body)
    )
    return Line(chars, page, block, index)


def two_column_page(rows: int = 30) -> list[Line]:
    out = []
    for i in range(rows):
        out.append(line(*LEFT, y=100.0 + 12 * i, index=i))
        out.append(line(*RIGHT, y=100.0 + 12 * i, index=i))
    return out


class TestColumns:
    def test_two_columns_are_found_as_two_bands(self):
        found = columns(two_column_page(), PAGE_WIDTH)
        assert len(found) == 2
        assert found[0][0] == pytest.approx(LEFT[0], abs=2)
        assert found[1][1] == pytest.approx(RIGHT[1], abs=2)

    def test_one_full_width_line_does_not_merge_the_columns(self):
        # A spanning caption or a wide equation crosses the gutter. Cutting wherever
        # coverage reaches zero would then report a single column across the page.
        lines = [*two_column_page(), line(LEFT[0], RIGHT[1], y=500.0)]
        assert len(columns(lines, PAGE_WIDTH)) == 2

    def test_a_sliver_is_not_a_column(self):
        # Rotated download stamps and side rules leave narrow bands of their own.
        lines = [*two_column_page(), line(2.0, 12.0, y=300.0)]
        assert len(columns(lines, PAGE_WIDTH)) == 2

    def test_a_page_without_text_has_no_columns(self):
        assert columns([], PAGE_WIDTH) == []


@pytest.fixture
def page_with_a_drawing(tmp_path):
    """Two columns of text with a black block above the left column's caption."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_WIDTH, height=800)
    page.draw_rect(pymupdf.Rect(60, 200, 270, 320), color=(0, 0, 0), fill=(0, 0, 0))
    path = tmp_path / "page.pdf"
    doc.save(path)
    doc.close()
    return pymupdf.open(path)


def caption_at(y: float, text: str = "Fig. 1. A diagram.") -> Paragraph:
    return Paragraph((line(LEFT[0], LEFT[1] - 60, y=y, text=text),))


class TestFigureRegions:
    def test_the_band_above_a_caption_becomes_the_figure(self, page_with_a_drawing):
        above = line(*LEFT, y=150.0, index=0)
        caption = caption_at(340.0)
        lines = [above, *caption.lines, line(*RIGHT, y=150.0, index=0)]
        found = figure_regions(page_with_a_drawing, lines, [caption], [Role.CAPTION])

        assert list(found) == [0]
        crop = found[0]
        # The region shrinks to the drawing, not to the empty band it was looked for in.
        assert crop.rect[1] == pytest.approx(200.0, abs=3)
        assert crop.rect[3] == pytest.approx(320.0, abs=3)

    def test_a_caption_with_nothing_above_it_yields_no_figure(self, page_with_a_drawing):
        # Some captions belong to an algorithm or a listing set as text.
        caption = caption_at(700.0)
        above = line(*LEFT, y=650.0, index=0)
        found = figure_regions(page_with_a_drawing, [above, *caption.lines],
                               [caption], [Role.CAPTION])
        assert found == {}

    def test_only_captions_are_looked_at(self, page_with_a_drawing):
        body = caption_at(340.0, "This is ordinary running text about the diagram.")
        found = figure_regions(page_with_a_drawing, list(body.lines), [body], [Role.BODY])
        assert found == {}
