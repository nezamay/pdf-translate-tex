import pytest

from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import Paragraph
from translatex.pdfin.roles import Layout
from translatex.pdfin.roles import Role
from translatex.pdfin.roles import classify
from translatex.pdfin.roles import merge

BODY = 10.0


def line(text: str, *, size: float = BODY, font: str = "Text", x0: float = 50.0,
         y: float = 200.0, page: int = 0, block: int = 0, index: int = 0) -> Line:
    step = size / 2
    chars = tuple(
        Char(text=ch, bbox=(x0 + i * step, y, x0 + (i + 1) * step, y + size),
             page=page, font=font, size=size)
        for i, ch in enumerate(text)
    )
    return Line(chars, page, block, index)


def para(text: str, **kwargs) -> Paragraph:
    return Paragraph((line(text, **kwargs),))


def layout_for(paragraphs: list[Paragraph]) -> Layout:
    return Layout.measure([ln for p in paragraphs for ln in p.lines])


def roles_of(paragraphs: list[Paragraph]) -> list[Role]:
    return classify(paragraphs, layout_for(paragraphs))


# A page of body text, spanning the column the way a real one does: the measurement
# needs enough lines to find the size, the face and the band the body occupies.
FILLER = [para("a" * 120, y=100.0 + 20 * i, index=i) for i in range(20)]


class TestLayout:
    def test_the_body_size_is_the_commonest_one(self):
        paragraphs = [*FILLER, para("Title", size=24.0, y=100.0)]
        assert layout_for(paragraphs).body_size == BODY

    def test_a_smaller_text_face_still_counts_as_text(self):
        # Captions and footnotes are text set small; treating only the body size as text
        # made every caption look like an equation.
        paragraphs = [*FILLER, *[para("caption text here", size=8.0, y=400.0 + i) for i in range(3)]]
        assert "Text" in layout_for(paragraphs).body_fonts


class TestClassify:
    @pytest.mark.parametrize(
        ("text", "role"),
        [
            ("Abstract—This paper presents a new approach to interception.", Role.ABSTRACT),
            ("Index Terms—Guidance, navigation, control.", Role.ABSTRACT),
            ("Fig. 3. Intercepting a flight target with a multicopter.", Role.CAPTION),
            ("TABLE II Simulation parameters", Role.CAPTION),
            ("Digital Object Identifier 10.1109/TIE.2025.3559951", Role.FRONTMATTER),
            ("Kun Yang is with the School of Automation, Beihang University.", Role.FRONTMATTER),
            ("Manuscript received July 31, 2015; revised December 10, 2015.", Role.FRONTMATTER),
        ],
    )
    def test_a_paragraph_that_announces_itself_is_taken_at_its_word(self, text, role):
        assert roles_of([*FILLER, para(text, y=400.0)])[-1] is role

    def test_an_equation_is_recognised_by_having_almost_no_letters(self):
        # Measured on a real paper: body paragraphs are 80% letters, display equations 0%.
        assert roles_of([*FILLER, para("= 1/2 (3.5 + 7) × 2 − 4", y=400.0)])[-1] is Role.EQUATION

    def test_running_text_full_of_numbers_is_still_prose(self):
        text = "The target was tracked for 12 s at 3 m, giving 45 samples per run."
        assert roles_of([*FILLER, para(text, y=400.0)])[-1] is Role.BODY

    def test_everything_after_the_references_heading_is_a_reference(self):
        paragraphs = [
            *FILLER,
            para("REFERENCES", y=400.0),
            para("[1] A. Author, “A title,” Journal, vol. 1, 2020.", y=420.0),
            para("[2] B. Author, “Another title,” Journal, vol. 2, 2021.", y=440.0),
        ]
        assert roles_of(paragraphs)[-3:] == [Role.HEADING, Role.REFERENCE, Role.REFERENCE]

    def test_a_citation_in_running_text_is_not_a_reference(self):
        text = "Capture methods [12], [13], [14] are effective but need contact with it."
        assert roles_of([*FILLER, para(text, y=400.0)])[-1] is Role.BODY

    def test_only_the_translatable_roles_are_offered_for_translation(self):
        assert Role.BODY.translatable and Role.CAPTION.translatable
        assert not Role.AUTHORS.translatable
        assert not Role.REFERENCE.translatable
        assert not Role.EQUATION.translatable


class TestMerge:
    def test_a_title_wrapped_onto_two_blocks_is_one_title(self):
        paragraphs = [
            para("Precise Interception of Flight Targets by", size=24.0, y=60.0, block=0),
            para("Image-Based Visual Servoing", size=24.0, y=80.0, block=1),
            *FILLER,
        ]
        merged, roles = merge(paragraphs, classify(paragraphs, layout_for(paragraphs)))
        assert roles[0] is Role.TITLE
        assert merged[0].text.startswith("Precise Interception")
        assert merged[0].text.endswith("Visual Servoing")

    def test_a_section_number_joins_the_name_beside_it(self):
        paragraphs = [*FILLER, para("II.", y=400.0, block=1), para("RELATED WORK", y=400.0, block=2)]
        merged, roles = merge(paragraphs, classify(paragraphs, layout_for(paragraphs)))
        assert roles[-1] is Role.HEADING
        assert merged[-1].text == "II. RELATED WORK"

    def test_a_caption_swallows_the_sentence_set_apart_from_it(self):
        paragraphs = [*FILLER, para("Fig. 1.", size=8.0, y=400.0, block=1),
                      para("Intercepting a flight target.", size=8.0, y=400.0, block=2)]
        merged, roles = merge(paragraphs, classify(paragraphs, layout_for(paragraphs)))
        assert roles[-1] is Role.CAPTION
        assert merged[-1].text == "Fig. 1. Intercepting a flight target."

    def test_a_drop_cap_goes_back_to_the_paragraph_it_belongs_to(self):
        # The initial is set on a line of its own, three times the heading's size, and
        # the rest of the opening word stays in small capitals — so the paragraph below
        # begins with a capital and cannot be recognised by its case.
        heading = Paragraph((line("I. INTRODUCTION", size=8.0, y=400.0, index=0),
                             line("T", size=30.0, y=412.0, index=1)))
        body = para("HE presence of noncooperative targets is a problem.", y=412.0, block=1)
        paragraphs = [*FILLER, heading, body]
        merged, roles = merge(paragraphs, classify(paragraphs, layout_for(paragraphs)))
        assert merged[-2].text == "I. INTRODUCTION"
        assert merged[-1].text.startswith("THE presence")
