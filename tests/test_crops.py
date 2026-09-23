import pymupdf
import pytest

from translatex.pdfin import Char
from translatex.pdfin.crops import Crop
from translatex.pdfin.crops import bounds
from translatex.pdfin.crops import glyph_crops
from translatex.pdfin.crops import tighten
from translatex.pdfin.crops import trim


def char(text="?", *, x0=100.0, y0=200.0, width=6.0, height=11.0, readable=False,
         font="Sym", page=0) -> Char:
    return Char(text=text, bbox=(x0, y0, x0 + width, y0 + height), page=page,
                font=font, size=10.0, readable=readable)


@pytest.fixture
def page_with_a_mark(tmp_path):
    """A one-page PDF with a single small mark, so ink can be looked for."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=400)
    page.draw_rect(pymupdf.Rect(150, 200, 156, 206), color=(0, 0, 0), fill=(0, 0, 0))
    path = tmp_path / "page.pdf"
    doc.save(path)
    doc.close()
    return pymupdf.open(path)


class TestBounds:
    def test_the_box_holds_every_character_given(self):
        assert bounds([char(x0=100.0), char(x0=120.0)], pad=0.0) == (100.0, 200.0, 126.0, 211.0)

    def test_padding_grows_the_box_on_every_side(self):
        assert bounds([char(x0=100.0)], pad=2.0) == (98.0, 198.0, 108.0, 213.0)


class TestGlyphCrops:
    def test_readable_characters_are_not_cropped(self):
        assert glyph_crops([char(readable=True), char(readable=True)]) == {}

    def test_a_glyph_is_cropped_once_however_often_it_appears(self):
        # Across the corpus 2322 occurrences are 124 distinct glyphs; cropping each
        # occurrence would be nineteen times the work for the same pictures.
        crops = glyph_crops([char("\x01", x0=100.0), char("\x01", x0=200.0), char("\x01", x0=300.0)])
        assert len(crops) == 1

    def test_the_same_code_in_two_fonts_is_two_glyphs(self):
        crops = glyph_crops([char("\x01", font="A"), char("\x01", font="B")])
        assert len(crops) == 2

    def test_the_widest_occurrence_wins(self):
        # A glyph clipped by a column edge would otherwise become the one copy in use.
        crops = glyph_crops([char("\x01", x0=100.0, width=2.0), char("\x01", x0=200.0, width=9.0)])
        assert next(iter(crops.values())).width == pytest.approx(9.0 + 2 * 0.3)

    def test_the_name_survives_being_a_control_character(self):
        crop = next(iter(glyph_crops([char("\x01", font="AdvP4C4E46")]).values()))
        assert crop.name == "glyph_AdvP4C4E46_0001"


class TestTrim:
    def test_the_y_axis_is_flipped_for_graphicx(self, page_with_a_mark):
        # pymupdf measures down from the top of the page, graphicx up from the bottom.
        crop = Crop("x", 0, (10.0, 20.0, 40.0, 60.0))
        assert trim(page_with_a_mark, crop) == pytest.approx((10.0, 340.0, 260.0, 20.0))


class TestTighten:
    def test_a_box_shrinks_to_the_ink_it_contains(self, page_with_a_mark):
        loose = Crop("x", 0, (140.0, 190.0, 170.0, 220.0))
        tight = tighten(page_with_a_mark, loose, pad=0.0)
        assert tight.width < loose.width and tight.height < loose.height
        assert tight.rect[0] == pytest.approx(150.0, abs=1.0)
        assert tight.rect[3] == pytest.approx(206.0, abs=1.0)

    def test_a_box_with_no_ink_is_left_alone(self, page_with_a_mark):
        blank = Crop("x", 0, (10.0, 10.0, 60.0, 60.0))
        assert tighten(page_with_a_mark, blank) == blank

    def test_an_empty_box_is_left_alone(self, page_with_a_mark):
        outside = Crop("x", 0, (1000.0, 1000.0, 1010.0, 1010.0))
        assert tighten(page_with_a_mark, outside) == outside
