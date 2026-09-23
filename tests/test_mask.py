from translatex.mask import MAX_MATHS_LETTERS
from translatex.mask import mask
from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import Paragraph

TEXT_FONTS = frozenset({"Text"})


def chars(text: str, *, font: str = "Text", readable: bool = True, x0: float = 50.0,
          y: float = 100.0, size: float = 10.0) -> list[Char]:
    return [
        Char(text=ch, bbox=(x0 + i * 5, y, x0 + (i + 1) * 5, y + 10), page=0,
             font=font, size=size, readable=readable)
        for i, ch in enumerate(text)
    ]


def paragraph(*runs, known: frozenset[str] = frozenset()) -> Paragraph:
    """A one-line paragraph built from (text, font) or (text, font, readable) runs."""
    out: list[Char] = []
    x = 50.0
    for run in runs:
        text, font = run[0], run[1]
        readable = run[2] if len(run) > 2 else True
        size = run[3] if len(run) > 3 else 10.0
        out += chars(text, font=font, readable=readable, x0=x, size=size)
        x += 5 * len(text)
    return Paragraph((Line(tuple(out), 0, 0, 0),), known)


class TestMask:
    def test_a_variable_in_another_face_becomes_a_marker(self):
        result = mask(paragraph(("the gain ", "Text"), ("ka", "Maths"), (" was set", "Text")),
                      TEXT_FONTS)
        assert result.text == "the gain {v1} was set"
        assert result.pieces[0].text == "ka"

    def test_an_unreadable_glyph_is_maths_whatever_its_face(self):
        result = mask(paragraph(("value ", "Text"), ("\x01", "Text", False), (" here", "Text")),
                      TEXT_FONTS)
        assert result.text == "value {v1} here"

    def test_an_expression_keeps_its_spaces_and_digits(self):
        # "ka = 2" is one expression written with spaces in it; cutting at the spaces
        # would hand the translator a stray 2.
        result = mask(paragraph(("set ", "Text"), ("ka", "Maths"), (" = 2", "Text"),
                                (", and", "Text")), TEXT_FONTS)
        assert result.pieces[0].text == "ka = 2"
        assert result.text == "set {v1}, and"

    def test_prose_in_an_unusual_face_is_not_an_expression(self):
        # An abstract is set in a face the body never uses. Without a length bound the
        # whole of it came back as one expression and nothing was translated.
        prose = "This paper presents a method for interception"
        assert len(prose) > MAX_MATHS_LETTERS
        result = mask(paragraph((prose, "Display")), TEXT_FONTS)
        assert result.text == prose
        assert result.pieces == ()

    def test_a_drop_cap_is_not_an_expression(self):
        # The initial is set in a display face, and the rest of the word stays in small
        # capitals, so the case of what follows says nothing.
        result = mask(paragraph(("T", "Display", True, 30.0), ("HE presence of", "Text")),
                      TEXT_FONTS)
        assert result.text == "THE presence of"
        assert result.pieces == ()

    def test_a_subscript_left_in_the_text_face_joins_its_expression(self):
        result = mask(paragraph(("frame ", "Text"), ("x", "Maths"), ("eyeze", "Text"),
                                (", the", "Text")), TEXT_FONTS)
        assert result.pieces[0].text == "xeyeze"
        assert result.text == "frame {v1}, the"

    def test_a_real_word_against_an_expression_is_left_alone(self):
        # The document spells "denotes" elsewhere, so it is a word, not a subscript.
        result = mask(
            paragraph(("n", "Maths"), ("denotes", "Text"), known=frozenset({"denotes"})),
            TEXT_FONTS,
        )
        assert result.text == "{v1}denotes"
        assert result.pieces[0].text == "n"


class TestRestore:
    def test_a_translation_gets_its_expressions_back(self):
        result = mask(paragraph(("the gain ", "Text"), ("ka", "Maths"), (" was set", "Text")),
                      TEXT_FONTS)
        assert result.restore("коэффициент {v1} задан") == "коэффициент ka задан"

    def test_restoring_the_unchanged_text_gives_the_original(self):
        source = paragraph(("gain ", "Text"), ("ka", "Maths"), (" and ", "Text"),
                           ("kd", "Maths"), (" set", "Text"))
        result = mask(source, TEXT_FONTS)
        assert result.restore(result.text) == source.text

    def test_a_marker_the_translator_dropped_is_noticed(self):
        result = mask(paragraph(("gain ", "Text"), ("ka", "Maths")), TEXT_FONTS)
        assert result.markers_kept
        lost = type(result)(result.text.replace("{v1}", ""), result.pieces)
        assert not lost.markers_kept

    def test_an_unknown_marker_in_a_translation_is_left_as_it_is(self):
        result = mask(paragraph(("gain ", "Text"), ("ka", "Maths")), TEXT_FONTS)
        assert result.restore("усиление {v1} и {v9}") == "усиление ka и {v9}"
