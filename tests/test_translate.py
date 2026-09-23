import json
import subprocess

import pytest

from translatex.mask import Masked
from translatex.mask import Piece
from translatex.translate import CallFailed
from translatex.translate import Translator
from translatex.translate import _parse


def masked(text: str, *pieces: tuple[str, str]) -> Masked:
    return Masked(text, tuple(Piece(marker, value, ()) for marker, value in pieces))


def stream(*chunks: dict) -> str:
    return "\n".join(json.dumps(chunk) for chunk in chunks)


def assistant(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


class TestParse:
    def test_the_answer_and_the_session_come_back(self):
        out = stream(
            {"type": "system", "session_id": "abc-123"},
            assistant("перевод"),
            {"type": "result", "is_error": False},
        )
        assert _parse(out) == ("перевод", "abc-123", None)

    def test_an_error_in_the_result_is_reported(self):
        # A failed resume exits cleanly and says so only in the result chunk.
        out = stream(assistant(""), {"type": "result", "is_error": True, "result": "no session"})
        assert _parse(out)[2] == "no session"

    def test_lines_that_are_not_json_are_stepped_over(self):
        out = "starting up\n" + stream(assistant("текст")) + "\nbye"
        assert _parse(out)[0] == "текст"

    def test_an_empty_stream_yields_nothing(self):
        assert _parse("") == ("", None, None)


class Fake(Translator):
    """A translator whose calls are scripted instead of spawned."""

    def __init__(self, answers, **kwargs):
        super().__init__(**kwargs)
        self.answers = list(answers)
        self.prompts: list[str] = []

    def _call(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        self.session_blocks += 1
        self.total_blocks += 1
        return answer


class TestTranslate:
    def test_a_translation_gets_its_expressions_back(self):
        source = masked("the gain {v1} was set", ("{v1}", "k_a"))
        assert Fake(["коэффициент {v1} задан"]).translate(source) == "коэффициент k_a задан"

    def test_a_paragraph_with_no_text_is_not_sent(self):
        translator = Fake([])
        assert translator.translate(masked("   ")) == "   "
        assert translator.prompts == []

    def test_a_dropped_marker_is_retried(self):
        source = masked("gain {v1} set", ("{v1}", "k_a"))
        translator = Fake(["усиление задано", "усиление {v1} задано"])
        assert translator.translate(source) == "усиление k_a задано"
        assert len(translator.prompts) == 2

    def test_a_paragraph_whose_markers_never_return_stays_in_english(self):
        # A paragraph left untranslated is visible to a reader. One that quietly lost an
        # equation is not.
        source = masked("gain {v1} set", ("{v1}", "k_a"))
        translator = Fake(["усиление задано"] * 3)
        assert translator.translate(source) == "gain k_a set"

    def test_a_renumbered_marker_counts_as_lost(self):
        source = masked("{v1} and {v2}", ("{v1}", "a"), ("{v2}", "b"))
        translator = Fake(["{v2} и {v1}", "{v1} и {v2}"])
        assert translator.translate(source) == "a и b"

    def test_a_failed_call_drops_the_session_and_retries(self, monkeypatch):
        monkeypatch.setattr("translatex.translate.time.sleep", lambda _s: None)
        source = masked("gain {v1}", ("{v1}", "k"))
        translator = Fake([CallFailed("boom"), "усиление {v1}"])
        translator.session = "stale-session"
        assert translator.translate(source) == "усиление k"
        assert translator.session_index == 2

    def test_a_timeout_is_treated_as_a_failed_call(self, monkeypatch):
        monkeypatch.setattr("translatex.translate.time.sleep", lambda _s: None)
        source = masked("gain {v1}", ("{v1}", "k"))
        expired = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        assert Fake([expired, "усиление {v1}"]).translate(source) == "усиление k"


class TestSession:
    def test_the_session_is_resumed_while_it_lives(self):
        translator = Translator()
        translator.session = "s-1"
        command = translator._command()
        assert command[command.index("-r") + 1] == "s-1"

    def test_a_fresh_session_is_not_resumed(self):
        assert "-r" not in Translator()._command()

    def test_dropping_a_session_advances_the_count(self):
        translator = Translator()
        translator.session, translator.session_blocks = "s-1", 7
        translator._drop("because")
        assert translator.session is None
        assert translator.session_blocks == 0
        assert translator.session_index == 2


@pytest.mark.parametrize("blocks", [0, 39])
def test_a_session_under_the_limit_is_kept(blocks):
    translator = Translator(max_blocks=40)
    translator.session, translator.session_blocks = "s-1", blocks
    assert translator.session == "s-1"
