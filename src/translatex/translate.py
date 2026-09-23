"""Sending masked paragraphs to the translator and getting them back intact.

One `claude -p` session is resumed across paragraphs rather than started afresh for each,
which keeps the prompt cache warm and saves the fixed startup cost every time. The session
accumulates everything translated so far, so it is rolled over before it can fill the
context window: without that a long paper ends up re-reading a six-figure token count on
every call and eventually hits the window outright.

A session id that has gone bad poisons every later paragraph, so it is dropped on any
failure rather than retried. And a translation that came back missing one of its markers
is a lost formula, silently — so it is checked, retried, and failing that the paragraph
is left in its original language, which is obvious to a reader in a way a missing formula
is not.

One paragraph per call, not several. Batching looks like the obvious saving and is not —
measured on ten paragraphs carrying twenty-nine expressions, the same model in the same
conditions:

    one paragraph per call     42.9 s   10 calls   all returned, all expressions intact
    five per call as JSON      91.8 s    2 calls   all returned, all expressions intact

Twice as slow, because the cost is in generating the translation and a batch generates
five of them in one serial call while sending a fresh payload each time instead of
building on a warm session. The quality was worse too: the batched run left "Fig. 2"
in English where the single call wrote "Рис. 2". Fewer calls also means a wider blast
radius — one failure loses five paragraphs instead of one.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field

from translatex.mask import MARKER
from translatex.mask import Masked

logger = logging.getLogger(__name__)

#: Progress goes through a deliberately tiny logger name. A console handler prints
#: "LEVEL:<logger>:<message>" into a column about thirty characters wide and wraps the
#: rest, and this module's own name alone fills it — every marker would be cut mid-word.
progress = logging.getLogger("tx")

PROMPT = """Translate the text below into {language}. Reply with the translation and nothing else.

Every {{vN}} marker stands for a mathematical expression that has been taken out of the
sentence. Reproduce each one exactly as it appears, in the same order, and do not
translate, renumber, reword or drop any of them.

Leave citation numbers in brackets, figure and equation references, and units as they are.
Keep the register of a scientific paper.

---
{text}"""

DISALLOWED = (
    "Task Bash Glob Grep LS exit_plan_mode Read Edit MultiEdit Write "
    "NotebookRead NotebookEdit TodoRead TodoWrite"
)


class CallFailed(Exception):
    """One call failed; another on a fresh session may still work."""


@dataclass
class Translator:
    """A resumed `claude -p` session, with the bookkeeping that keeps it alive."""

    language: str = "Russian"
    model: str = "sonnet"
    claude: str = "claude"
    max_blocks: int = 40
    timeout: int = 120
    attempts: int = 3

    session: str | None = field(default=None, init=False)
    session_index: int = field(default=1, init=False)
    session_blocks: int = field(default=0, init=False)
    total_blocks: int = field(default=0, init=False)

    def translate(self, masked: Masked) -> str:
        """The paragraph in the target language, with its expressions back in place.

        Returns the original text when the translator will not return the markers. A
        paragraph left in English is visible; a paragraph that quietly lost an equation
        is not.
        """
        if not masked.text.strip():
            return masked.text

        for attempt in range(1, self.attempts + 1):
            try:
                answer = self._call(PROMPT.format(language=self.language, text=masked.text))
            except (CallFailed, subprocess.TimeoutExpired, OSError) as exc:
                self._drop(f"{type(exc).__name__}")
                if attempt == self.attempts:
                    progress.warning("giving up after %d attempts", attempt)
                    return masked.restore(masked.text)
                time.sleep(min(2 ** attempt, 15))
                continue

            if _markers_of(answer) == _markers_of(masked.text):
                return masked.restore(answer)

            progress.warning(
                "markers changed (%s -> %s), retrying",
                ",".join(_markers_of(masked.text)) or "none",
                ",".join(_markers_of(answer)) or "none",
            )
            self._drop("markers changed")

        return masked.restore(masked.text)

    def _drop(self, why: str) -> None:
        if self.session:
            progress.warning("drop session %d: %s", self.session_index, why)
        self.session = None
        self.session_blocks = 0
        self.session_index += 1

    def _command(self) -> list[str]:
        command = [
            self.claude, "-p",
            "--model", self.model,
            "--max-turns", "1",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--disallowedTools", DISALLOWED,
        ]
        if self.session:
            command += ["-r", self.session]
        return command

    def _call(self, prompt: str) -> str:
        if self.session_blocks >= self.max_blocks:
            progress.info("session %d rollover", self.session_index)
            self.session = None
            self.session_blocks = 0
            self.session_index += 1

        payload = json.dumps(
            {"type": "user", "message": {"role": "user", "content": prompt}}
        )
        environment = os.environ.copy()
        environment.pop("ANTHROPIC_API_KEY", None)

        process = None
        try:
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            out, err = process.communicate(input=payload, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                # Reap it, but do not hang here if it will not die: the call has already
                # failed and the caller is about to start another.
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            raise

        text, session, error = _parse(out)
        if process.returncode != 0:
            raise CallFailed(f"claude exited {process.returncode}: {err.strip()[:200]}")
        if error:
            raise CallFailed(f"claude reported an error: {error[:200]}")
        if not text:
            raise CallFailed("no text in response")

        if session:
            self.session = session
        self.session_blocks += 1
        self.total_blocks += 1
        progress.info(
            "block %d s%d %d/%d",
            self.total_blocks, self.session_index, self.session_blocks, self.max_blocks,
        )
        return text.strip()


def _markers_of(text: str) -> list[str]:
    return MARKER.findall(text)


def _parse(output: str) -> tuple[str, str | None, str | None]:
    """The answer, the session to resume, and the error the run reported, if any.

    A failed resume can come back as a clean exit carrying an error in the result chunk,
    so the exit status is not enough on its own.
    """
    pieces: list[str] = []
    session: str | None = None
    error: str | None = None

    for line in output.strip().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        if chunk.get("session_id"):
            session = chunk["session_id"]
        if chunk.get("type") == "result" and chunk.get("is_error"):
            error = str(chunk.get("result") or chunk.get("subtype") or "error")
        if chunk.get("type") == "assistant" and "message" in chunk:
            for content in chunk["message"].get("content", []):
                if content.get("type") == "text":
                    pieces.append(content.get("text", ""))
        elif chunk.get("type") == "text":
            pieces.append(chunk.get("text", ""))

    return "".join(pieces).strip(), session, error
