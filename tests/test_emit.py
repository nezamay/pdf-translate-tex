import pytest

from translatex.emit import Assets
from translatex.emit import document
from translatex.emit import escape
from translatex.emit import render_maths
from translatex.mask import Masked
from translatex.mask import Piece
from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import Paragraph
from translatex.pdfin.crops import Crop
from translatex.pdfin.roles import Role

PAGE = (612.0, 792.0)


def line(text: str, page: int = 0) -> Line:
    chars = tuple(
        Char(text=ch, bbox=(50.0 + i * 5, 100.0, 55.0 + i * 5, 110.0), page=page,
             font="Text", size=10.0)
        for i, ch in enumerate(text)
    )
    return Line(chars, page, 0, 0)


def para(text: str, page: int = 0) -> Paragraph:
    return Paragraph((line(text, page),))


def build(paragraphs, roles, rendered=None, figures=None, equations=None):
    return document(
        paragraphs, roles, rendered or {}, figures or {}, equations or {},
        source="orig.pdf", page=PAGE, columns=1, body_size=10.0,
        trim_of=lambda crop: (1.0, 2.0, 3.0, 4.0),
    )


class TestEscape:
    @pytest.mark.parametrize(
        ("raw", "escaped"),
        [("50% of", r"50\% of"), ("a_b", r"a\_b"), ("R&D", r"R\&D"), ("$5", r"\$5"),
         ("#1", r"\#1"), ("{x}", r"\{x\}")],
    )
    def test_characters_tex_would_act_on_are_spelled_out(self, raw, escaped):
        assert escape(raw) == escaped

    def test_a_control_character_is_dropped(self):
        # TeX stops outright on one: "Text line contains an invalid character". They
        # only ever arrive from a symbol font's private arrangement.
        assert escape("a\x01b") == "ab"


class TestRenderMaths:
    def test_an_expression_comes_back_as_italic_text(self):
        masked = Masked("gain {v1} set", (Piece("{v1}", "k_a", (Char("k", (0, 0, 1, 1), 0, "M", 9),)),))
        out = render_maths(masked, "усиление {v1} задано", Assets("orig.pdf"), {}, lambda c: ())
        assert out == r"усиление \textit{k} задано"

    def test_the_marker_is_replaced_after_escaping_not_before(self):
        # Escaping last would escape the commands that set the expression.
        masked = Masked("{v1} & more", (Piece("{v1}", "x", (Char("x", (0, 0, 1, 1), 0, "M", 9),)),))
        out = render_maths(masked, "{v1} & ещё", Assets("orig.pdf"), {}, lambda c: ())
        assert out == r"\textit{x} \& ещё"

    def test_an_unidentified_glyph_becomes_its_own_picture(self):
        char = Char("\x01", (0, 0, 6, 10), 0, "Sym", 9.0, readable=False)
        masked = Masked("{v1}", (Piece("{v1}", "\x01", (char,)),))
        assets = Assets("orig.pdf")
        crop = Crop("glyph_Sym_0001", 0, (0.0, 0.0, 6.0, 10.0))
        out = render_maths(masked, "{v1}", assets, {("Sym", "\x01"): crop}, lambda c: ())
        assert "glyph_Sym_0001.png" in out
        assert assets.glyphs == {"glyph_Sym_0001": crop}


class TestDocument:
    def test_a_heading_keeps_the_paper_s_own_number(self):
        # "as shown in Section III" has to keep pointing at the section the author
        # called III, so LaTeX must not count sections of its own.
        tex = build([para("III. METHOD")], [Role.HEADING])
        assert r"\section*{III. METHOD}" in tex

    def test_a_subsection_is_recognised_by_its_letter(self):
        tex = build([para("B. Controller design")], [Role.HEADING])
        assert r"\subsection*{B. Controller design}" in tex

    def test_furniture_is_left_out_altogether(self):
        tex = build([para("IEEE TRANSACTIONS, VOL. 72"), para("Body text here.")],
                    [Role.RUNNING, Role.BODY])
        assert "IEEE TRANSACTIONS" not in tex
        assert "Body text here." in tex

    def test_a_caption_with_a_region_becomes_a_float(self):
        crop = Crop("figure_1_0", 0, (10.0, 20.0, 110.0, 120.0))
        tex = build([para("Fig. 1. A diagram.")], [Role.CAPTION], figures={0: crop})
        assert r"\begin{figure}" in tex
        assert "page=1" in tex
        assert "trim=1.00bp 2.00bp 3.00bp 4.00bp" in tex

    def test_a_caption_with_no_region_is_still_printed(self):
        tex = build([para("Fig. 1. A diagram.")], [Role.CAPTION])
        assert "Fig. 1. A diagram." in tex
        assert r"\begin{figure}" not in tex

    def test_a_display_equation_is_shown_not_transcribed(self):
        # Its rules are drawn strokes the text layer does not hold, so the characters
        # do not say what is on the page.
        crop = Crop("eq_0", 2, (10.0, 20.0, 210.0, 60.0))
        tex = build([para("x ¼ 2")], [Role.EQUATION], equations={0: crop})
        assert "page=3" in tex
        assert r"\resizebox" in tex

    def test_a_lone_equation_number_is_dropped(self):
        tex = build([para("(12)")], [Role.EQUATION])
        assert "(12)" not in tex

    def test_two_columns_are_set_as_two(self):
        tex = document([para("Body.")], [Role.BODY], {}, {}, {}, source="orig.pdf",
                       page=PAGE, columns=2, body_size=10.0, trim_of=lambda c: (0, 0, 0, 0))
        assert r"\begin{multicols}{2}" in tex
        assert r"\usepackage{multicol}" in tex

    def test_the_page_is_the_size_of_the_original(self):
        tex = build([para("Body.")], [Role.BODY])
        assert "paperwidth=612.0bp" in tex
        assert "paperheight=792.0bp" in tex
