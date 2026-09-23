import pytest

from translatex.pdfin import Char
from translatex.pdfin import Line
from translatex.pdfin import bare_name
from translatex.pdfin import family
from translatex.pdfin import stitch
from translatex.pdfin import style_from_name
from translatex.pdfin import unreadable_runs


# Font names as they appear in the corpus.
REGULAR = "NEKBOF+AdvOT3c2d9f11"
ITALIC = "NEKCIE+AdvOT907ecf5c.I"
BOLD_ITALIC = "NEKBOA+AdvOTc7c3f249.BI"
BOLD_WITH_BLOCK = "NEKBOB+AdvOT5bf56204.B+20"


class TestFontNames:
    def test_the_subset_prefix_is_dropped(self):
        assert bare_name(REGULAR) == "AdvOT3c2d9f11"

    def test_the_family_loses_both_the_cut_and_the_unicode_block(self):
        # The trailing "+20" names a Unicode block, not another part of the name, so a
        # bold face and its punctuation subset have to land on the same family.
        assert family(BOLD_WITH_BLOCK) == "AdvOT5bf56204"
        assert family(BOLD_ITALIC) == "AdvOTc7c3f249"
        assert family(REGULAR) == family(REGULAR + ".I")

    @pytest.mark.parametrize(
        ("name", "style"),
        [
            (REGULAR, (False, False)),
            (ITALIC, (False, True)),
            (BOLD_ITALIC, (True, True)),
            (BOLD_WITH_BLOCK, (True, False)),
        ],
    )
    def test_the_cut_is_read_off_the_name(self, name, style):
        assert style_from_name(name) == style

    def test_a_name_without_a_cut_claims_nothing(self):
        assert style_from_name("Times-Roman") == (False, False)
        assert style_from_name("") == (False, False)


def char(x0, *, text="?", readable=False, page=0, size=10.0):
    return Char(text=text, bbox=(x0, 0.0, x0 + 5.0, 10.0), page=page, font="f", size=size,
                readable=readable)


class TestUnreadableRuns:
    def test_readable_text_produces_no_runs(self):
        assert unreadable_runs([char(0, readable=True), char(10, readable=True)]) == []

    def test_neighbours_join_one_run(self):
        runs = unreadable_runs([char(0), char(6), char(12)])
        assert [len(r) for r in runs] == [3]

    def test_a_readable_character_ends_a_run(self):
        runs = unreadable_runs([char(0), char(6, readable=True), char(12)])
        assert [len(r) for r in runs] == [1, 1]

    def test_a_wide_gap_starts_a_new_run(self):
        # Far enough apart to be two separate broken constructions, not one.
        runs = unreadable_runs([char(0), char(200)])
        assert [len(r) for r in runs] == [1, 1]

    def test_a_page_break_starts_a_new_run(self):
        runs = unreadable_runs([char(0, page=0), char(6, page=1)])
        assert [len(r) for r in runs] == [1, 1]


class TestNamesWithoutASubsetPrefix:
    def test_a_name_with_no_prefix_survives_whole(self):
        # "AdvOT3c2d9f11+fb" carries a Unicode block but no subset prefix. Splitting on
        # the first plus left "fb", so every ligature in the document was filed under a
        # family the body never used, and read as maths.
        assert bare_name("AdvOT3c2d9f11+fb") == "AdvOT3c2d9f11+fb"
        assert family("AdvOT3c2d9f11+fb") == "AdvOT3c2d9f11"

    def test_a_six_letter_prefix_is_still_removed(self):
        assert bare_name("NEKBOG+AdvOT3c2d9f11+fb") == "AdvOT3c2d9f11+fb"

    def test_a_plus_that_is_not_a_prefix_is_kept(self):
        assert bare_name("Advent+Extra") == "Advent+Extra"


def fragment(text: str, x0: float, *, y: float = 100.0, size: float = 10.0,
             block: int = 0, index: int = 0) -> Line:
    step = size / 2
    chars = tuple(
        Char(text=ch, bbox=(x0 + i * step, y, x0 + (i + 1) * step, y + size),
             page=0, font="Text", size=size)
        for i, ch in enumerate(text)
    )
    return Line(chars, 0, block, index)


class TestStitch:
    def test_a_justified_line_cut_into_words_is_put_back(self):
        # A line stretched to fill its measure has word gaps wide enough that pymupdf
        # calls each word a line. Left alone, each one then looks like an indent and
        # becomes a paragraph of its own.
        row = [fragment("inappropriate", 41.8), fragment("guidance", 102.4),
               fragment("strategies,", 146.3), fragment("and", 194.0)]
        stitched = stitch(row, 600.0)
        assert len(stitched) == 1
        assert stitched[0].text == "inappropriate guidance strategies, and"

    def test_the_other_column_is_not_joined_on(self):
        # A gutter is several times wider than any word gap, which is what keeps the
        # two columns of a journal page apart.
        row = [fragment("left column text", 41.8), fragment("right column text", 305.0)]
        assert len(stitch(row, 600.0)) == 2

    def test_different_baselines_stay_different_lines(self):
        rows = [fragment("first", 41.8, y=100.0), fragment("second", 41.8, y=112.0)]
        assert len(stitch(rows, 600.0)) == 2

    def test_a_line_that_was_never_cut_is_returned_as_it_was(self):
        only = fragment("a whole line of text", 41.8)
        assert stitch([only], 600.0) == [only]
