import pytest

from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import paragraphs
from translatex.pdfin import split_words
from translatex.pdfin.words import join_hyphenated
from translatex.pdfin.words import vocabulary


def line(text: str, *, x0: float = 50.0, y: float = 100.0, size: float = 10.0,
         page: int = 0, block: int = 0, index: int = 0) -> Line:
    """A line laid out left to right, each character half the body size wide."""
    step = size / 2
    chars = tuple(
        Char(text=ch, bbox=(x0 + i * step, y, x0 + (i + 1) * step, y + size),
             page=page, font="f", size=size)
        for i, ch in enumerate(text)
    )
    return Line(chars, page, block, index)


class TestSplitWords:
    def test_words_are_the_runs_between_spaces(self):
        assert [w.text for w in split_words(line("one two three"))] == ["one", "two", "three"]

    def test_repeated_and_edge_spaces_produce_no_empty_words(self):
        assert [w.text for w in split_words(line("  a   b  "))] == ["a", "b"]

    def test_a_word_keeps_its_box(self):
        first = split_words(line("ab cd"))[0]
        assert first.bbox[0] == pytest.approx(50.0)
        assert first.bbox[2] == pytest.approx(60.0)


class TestVocabulary:
    def test_whole_words_are_collected(self):
        known = vocabulary([line("The quick brown fox")])
        assert {"the", "quick", "brown", "fox"} <= known

    def test_the_halves_of_a_broken_word_are_not_words(self):
        # Counting them would let the dictionary answer its own question: "solute"
        # becomes a word because "ab-solute" was split, and the hyphen then survives.
        known = vocabulary([line("an ab-"), line("solute value")])
        assert "solute" not in known
        assert "ab" not in known
        assert {"an", "value"} <= known


class TestJoinHyphenated:
    def test_the_fused_form_wins_when_the_document_spells_it_out(self):
        assert join_hyphenated("encom", "passing", frozenset({"encompassing"})) == "encompassing"

    def test_the_hyphen_survives_when_the_document_spells_that_out(self):
        assert join_hyphenated("image", "based", frozenset({"image-based"})) == "image-based"

    def test_a_tail_that_is_a_word_keeps_the_hyphen(self):
        assert join_hyphenated("camera", "equipped", frozenset({"equipped"})) == "camera-equipped"

    def test_an_unknown_tail_closes_the_word_up(self):
        assert join_hyphenated("contin", "uously", frozenset()) == "continuously"


class TestParagraphs:
    def test_consecutive_lines_of_a_block_are_one_paragraph(self):
        lines = [line("first line here", y=100, index=0), line("second line here", y=112, index=1)]
        result = paragraphs(lines)
        assert len(result) == 1
        assert result[0].text == "first line here second line here"

    def test_a_new_block_starts_a_paragraph(self):
        lines = [line("first", y=100, block=0), line("second", y=112, block=1)]
        assert len(paragraphs(lines)) == 2

    def test_a_wide_vertical_gap_starts_a_paragraph(self):
        lines = [line("first", y=100, index=0), line("second", y=160, index=1)]
        assert len(paragraphs(lines)) == 2

    def test_an_indent_starts_a_paragraph(self):
        lines = [line("first line", y=100, index=0), line("second line", x0=62, y=112, index=1)]
        assert len(paragraphs(lines)) == 2

    def test_a_short_line_ends_a_paragraph(self):
        # The first line stops well short of the column edge the second one reaches.
        lines = [line("short", y=100, index=0), line("a much longer line here", y=112, index=1)]
        assert len(paragraphs(lines)) == 2

    def test_a_break_inside_a_word_is_healed(self):
        lines = [line("a contin-", y=100, index=0), line("uously moving thing", y=112, index=1)]
        assert paragraphs(lines)[0].text == "a continuously moving thing"


class TestSoftHyphen:
    def test_a_soft_hyphen_is_believed_without_asking_the_document(self):
        # U+00AD is the typesetter's own break mark. No corpus PDF carries one, but a
        # publisher that does deserves to be taken at its word rather than guessed at.
        known = frozenset({"equipped"})
        assert join_hyphenated("camera", "equipped", known, mark="­") == "cameraequipped"
        assert join_hyphenated("camera", "equipped", known, mark="-") == "camera-equipped"

    def test_a_soft_hyphen_break_is_healed_in_a_paragraph(self):
        lines = [line("a camera­", y=100, index=0), line("equipped thing", y=112, index=1)]
        assert paragraphs(lines)[0].text == "a cameraequipped thing"
