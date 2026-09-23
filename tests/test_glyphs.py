import pymupdf
import pytest

from translatex.glyphs import DECLARED
from translatex.glyphs import GREEK
from translatex.glyphs import decide
from translatex.glyphs import greek_letter
from translatex.glyphs import readings


def advance(font_name: str, char: str) -> float:
    return pymupdf.Font(font_name).glyph_advance(ord(char)) * 1000.0


def widths_for(pairs: str, font_name: str = "tiro", scale: float = 1.0) -> dict[int, float]:
    """A /Widths map as declared by a font that codes `latin` and draws `drawn`.

    `pairs` is written as space-separated two-character groups, "aα eε", so the test reads
    as the substitution it is describing.
    """
    return {
        ord(latin): advance(font_name, drawn) * scale
        for latin, drawn in (group for group in pairs.split())
    }


class TestGreekIndex:
    def test_alphabet_starts_at_alpha(self):
        assert greek_letter(1) == "α"
        assert greek_letter(1, upper=True) == "Α"

    def test_final_sigma_is_skipped(self):
        # Rho is the seventeenth letter, sigma the eighteenth; U+03C2 between them is
        # final sigma, which is a form and not a letter of the alphabet.
        assert greek_letter(17) == "ρ"
        assert greek_letter(18) == "σ"
        assert greek_letter(18, upper=True) == "Σ"

    def test_alphabet_ends_at_omega(self):
        assert greek_letter(24) == "ω"
        with pytest.raises(ValueError):
            greek_letter(25)


class TestReadings:
    def test_declared_is_always_offered(self):
        assert readings(ord("5"))[DECLARED] == "5"

    @pytest.mark.parametrize(
        ("latin", "greek"),
        [("a", "α"), ("e", "ε"), ("g", "η"), ("p", "π"), ("r", "σ"), ("w", "ψ"), ("x", "ω")],
    )
    def test_positional_greek_matches_the_observed_subsets(self, latin, greek):
        assert readings(ord(latin))[GREEK] == greek

    def test_letters_past_the_alphabet_have_no_greek_reading(self):
        assert GREEK not in readings(ord("y"))
        assert GREEK not in readings(ord("/"))


def coded(widths: dict[str, float], scale: float = 1.0) -> dict[int, float]:
    return {ord(char): w * scale for char, w in widths.items()}


# Real /Widths taken from the corpus, so the thresholds are tested against the evidence
# that set them rather than against numbers invented to clear them.

#: The face that started this: Latin glyph names over Greek shapes.
ADVPSMP10 = {"/": 666, "a": 500, "e": 385, "g": 500, "p": 552, "r": 552, "w": 666, "x": 718}

#: Ralph Smith's Formal Script — script capitals whose declared reading already fits.
#: An earlier rule turned N, P, R into Xi, Pi, Sigma on three glyphs of noise.
RSFS10 = {"N": 902, "P": 1013, "R": 850}

#: Computer Modern Math Italic — f, h, i, s, t really are italic Latin letters here.
CMMI7 = {"f": 557, "h": 669, "i": 404, "s": 539, "t": 432}


class TestDecide:
    def test_the_greek_face_is_caught(self):
        verdict = decide("AdvPSMP10", coded(ADVPSMP10))
        assert verdict.reading == GREEK
        assert verdict.overrides[ord("x")] == "ω"
        assert verdict.overrides[ord("r")] == "σ"

    def test_the_verdict_does_not_depend_on_the_font_size(self):
        # One free scale factor is fitted, so a face cut at another size reads the same.
        assert decide("AdvPSMP10", coded(ADVPSMP10, 0.71)).reading == GREEK

    def test_a_script_face_is_left_alone(self):
        verdict = decide("rsfs10", coded(RSFS10))
        assert verdict.reading == DECLARED
        assert not verdict.overrides

    def test_a_maths_italic_face_is_left_alone(self):
        verdict = decide("CMMI7", coded(CMMI7))
        assert verdict.reading == DECLARED
        assert not verdict.overrides

    def test_an_honest_latin_face_is_left_alone(self):
        verdict = decide("fake", widths_for("aa ee gg pp rr ww xx"))
        assert verdict.reading == DECLARED
        assert not verdict.overrides

    def test_too_few_codes_decide_nothing(self):
        verdict = decide("fake", widths_for("aα eε gη"))
        assert verdict.reading == DECLARED

    def test_control_codes_are_always_flagged_for_cropping(self):
        verdict = decide("fake", {0x01: 500.0, 0x07: 500.0, ord("a"): 444.0})
        assert verdict.unexplained == frozenset({0x01, 0x07})

    def test_a_corrected_font_flags_what_its_reading_cannot_explain(self):
        # Slash is in the subset and has no Greek reading, so it is cropped, not guessed.
        verdict = decide("AdvPSMP10", coded(ADVPSMP10))
        assert verdict.reading == GREEK
        assert ord("/") in verdict.unexplained
