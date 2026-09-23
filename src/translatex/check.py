"""Judging a finished translation without reading it.

Three things can go wrong quietly and only one of them is visible on the page. A
paragraph left in English announces itself. An expression dropped on the way through the
translator does not — the sentence closes over the gap and reads perfectly. And a glyph
the typesetter could not set leaves a blank that looks like a space.

So the counts come from the record the run kept, not from the result: what was sent, what
came back, and whether every expression that went out is in what returned.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pymupdf

from translatex.workdir import WORK_DIRNAME

GREEK = re.compile(r"[Ͱ-Ͽ]")


@dataclass
class Report:
    paper: str
    paragraphs: int = 0
    untranslated: int = 0
    expressions: int = 0
    expressions_kept: int = 0
    greek_before: int = 0
    greek_after: int = 0
    missing_characters: int = 0
    pages_before: int = 0
    pages_after: int = 0
    lost: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.expressions == self.expressions_kept
            and not self.missing_characters
            and self.pages_after > 0
        )

    def lines(self) -> list[str]:
        share = 100.0 * self.expressions_kept / max(self.expressions, 1)
        out = [
            f"{self.paper}",
            f"  paragraphs    {self.paragraphs} sent, {self.untranslated} left in English",
            f"  expressions   {self.expressions_kept}/{self.expressions} kept ({share:.1f}%)",
            f"  greek letters {self.greek_before} before, {self.greek_after} after",
            f"  missing chars {self.missing_characters}",
            f"  pages         {self.pages_before} -> {self.pages_after}",
        ]
        if self.lost:
            out.append("  lost: " + ", ".join(repr(x) for x in self.lost[:8]))
        return out


def check(paper: Path) -> Report:
    """Read what a run left behind and say whether it holds together."""
    work = paper / WORK_DIRNAME
    report = Report(paper=paper.name)

    record = json.loads((work / "tracking.json").read_text(encoding="utf-8"))
    report.paragraphs = len(record)
    for entry in record:
        if entry["translated"].strip() == entry["source"].strip():
            report.untranslated += 1
        report.greek_before += len(GREEK.findall(entry["source"]))
        report.greek_after += len(GREEK.findall(entry["translated"]))
        for piece in entry["pieces"]:
            report.expressions += 1
            # The marker is replaced by the expression itself, so a kept expression is
            # one whose text survives in the finished sentence.
            if piece.strip() and piece.strip() in entry["translated"]:
                report.expressions_kept += 1
            elif not piece.strip():
                report.expressions_kept += 1
            else:
                report.lost.append(piece.strip()[:24])

    log = work / "tectonic.log"
    if log.exists():
        report.missing_characters = sum(
            1 for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
            if "Missing character" in line
        )

    original = paper / f"{paper.name}.pdf"
    if original.exists():
        with pymupdf.open(original) as doc:
            report.pages_before = len(doc)
    for built in sorted(paper.glob(f"{paper.name}_*.pdf")):
        with pymupdf.open(built) as doc:
            report.pages_after = len(doc)
        break

    return report
