import pytest

from translatex.pdfin import Char
from translatex.pdfin import bare_name
from translatex.pdfin import family
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
