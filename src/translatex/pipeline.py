"""The whole run: a publisher's PDF in, a translated PDF out.

Everything the run learned is written to the working tree beside the result, because the
one thing that made the earlier effort debuggable was a record of what went to the
translator and what came back. A formula that arrives broken is worth nothing without
knowing whether it was broken before it was sent.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import pymupdf

from translatex.emit import Assets
from translatex.emit import document
from translatex.emit import render_maths
from translatex.mask import mask
from translatex.pdfin import Paragraph
from translatex.pdfin import paragraphs
from translatex.pdfin import read_chars
from translatex.pdfin import read_lines
from translatex.pdfin.crops import glyph_crops
from translatex.pdfin.crops import save_glyph
from translatex.pdfin.crops import trim
from translatex.pdfin.regions import columns
from translatex.pdfin.regions import equation_regions
from translatex.pdfin.regions import figure_regions
from translatex.pdfin.roles import Layout
from translatex.pdfin.roles import Role
from translatex.pdfin.roles import classify
from translatex.pdfin.roles import merge
from translatex.translate import Translator
from translatex.workdir import ensure_paper_dir
from translatex.workdir import work_dir

progress = logging.getLogger("run")


def report(line: str) -> None:
    """One line of progress, on stdout, flushed.

    Not through logging: logging goes to stderr, where a shell pipeline is free to sit on
    it, and the whole point is that it arrives while the run is still going.
    """
    print(line, flush=True)

#: What a language code means to the translator, to polyglossia and to the file name.
#: The translator is told the name, not the code: "translate into ru" is not an
#: instruction anyone follows well.
LANGUAGES = {
    "ru": ("Russian", "russian"),
    "en": ("English", "english"),
    "de": ("German", "german"),
    "fr": ("French", "french"),
    "es": ("Spanish", "spanish"),
}


def language_of(code: str) -> tuple[str, str, str]:
    """(name for the translator, name for polyglossia, suffix for the file)."""
    lowered = code.strip().lower()
    for suffix, (name, babel) in LANGUAGES.items():
        if lowered in (suffix, name.lower(), babel):
            return name, babel, suffix
    return code, lowered, lowered[:2]


@dataclass
class Result:
    paper: Path
    tex: Path
    pdf: Path | None
    pages: int = 0
    translated: int = 0
    untranslated: int = 0
    figures: int = 0
    equations: int = 0
    glyphs: int = 0
    seconds: float = 0.0
    tectonic: int = 0
    missing_characters: list[str] = field(default_factory=list)


def parse_pages(spec: str | None) -> set[int] | None:
    """Which pages to work on, counted from one: "1", "1-3", "1,4-5", or None for all."""
    if not spec:
        return None
    wanted: set[int] = set()
    for part in spec.split(","):
        piece = part.strip()
        if "-" in piece:
            first, last = piece.split("-", 1)
            wanted.update(range(int(first) - 1, int(last)))
        elif piece:
            wanted.add(int(piece) - 1)
    return wanted


def run(source: Path, *, language: str = "ru", claude: str = "claude",
        model: str = "sonnet", limit: int | None = None, build: bool = True,
        pages: set[int] | None = None) -> Result:
    """Translate one paper and typeset it again.

    `pages` narrows the work to part of the paper, which is how a change is checked: a
    whole paper takes half an hour and shows a hundred things at once, one page takes a
    minute and shows whether the thing that was wrong is still wrong.
    """
    started = time.time()
    name, babel, suffix = language_of(language)
    paper = ensure_paper_dir(source)
    pdf = paper / source.name
    work = work_dir(paper)

    doc = pymupdf.open(pdf)
    lines = read_lines(doc)
    pieces = paragraphs(lines)
    layout = Layout.measure(lines)
    pieces, roles = merge(pieces, classify(pieces, layout))

    if pages is not None:
        keep = [i for i, x in enumerate(pieces) if x.lines[0].page in pages]
        pieces = [pieces[i] for i in keep]
        roles = [roles[i] for i in keep]
        lines = [line for line in lines if line.page in pages]

    figures = figure_regions(doc, lines, pieces, roles)
    equations, absorbed = equation_regions(doc, lines, pieces, roles)
    glyphs = glyph_crops(read_chars(doc))
    page_size = (doc[0].rect.width, doc[0].rect.height)
    widest = max((line.page for line in lines), default=0)
    column_count = max(
        1,
        max(
            (len(columns([x for x in lines if x.page == p], page_size[0]))
             for p in range(min(widest + 1, 3))),
            default=1,
        ),
    )

    assets = Assets(pdf.name)
    translator = Translator(language=name, model=model, claude=claude)
    rendered: dict[int, str] = {}
    record: list[dict] = []
    sent = 0

    wanted = [
        index
        for index, (paragraph, role) in enumerate(zip(pieces, roles, strict=True))
        if role.translatable and paragraph.text.strip()
    ]
    if limit is not None:
        wanted = wanted[:limit]

    for index in wanted:
        paragraph, role = pieces[index], roles[index]
        masked = mask(paragraph, layout.body_fonts)
        # Printed before the call, not after: a call takes seconds, and a tool that says
        # nothing for seconds looks like a tool that has stopped. One terse line per
        # paragraph — page, position, session, blocks into that session — so a watcher
        # can see both that it is moving and where it has got to.
        report(
            f"p{paragraph.lines[0].page + 1} {sent + 1}/{len(wanted)} "
            f"s{translator.session_index} {translator.session_blocks}/{translator.max_blocks} "
            f"{role.value}"
        )
        answer = translator.translate(masked)
        sent += 1
        rendered[index] = render_maths(
            masked, answer, assets, glyphs, lambda crop: trim(doc, crop)
        )
        record.append({
            "index": index,
            "role": role.value,
            "source": paragraph.text,
            "masked": masked.text,
            "translated": answer,
            "pieces": [piece.text for piece in masked.pieces],
        })

    tex = document(
        pieces, roles, rendered, figures, equations,
        source=pdf.name, page=page_size, columns=column_count,
        body_size=layout.body_size, trim_of=lambda crop: trim(doc, crop), assets=assets,
        babel=babel, skip=absorbed,
    )

    tex_path = work / "main.tex"
    tex_path.write_text(tex, encoding="utf-8")
    (work / "tracking.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for crop in assets.glyphs.values():
        save_glyph(doc, crop, work)
    if not (work / pdf.name).exists():
        shutil.copy(pdf, work / pdf.name)

    result = Result(
        paper=paper, tex=tex_path, pdf=None,
        translated=sent,
        untranslated=sum(1 for r in roles if r.translatable) - sent,
        figures=len(figures), equations=len(equations), glyphs=len(assets.glyphs),
    )

    if build:
        _typeset(work, result, paper, source.stem, suffix)
    result.seconds = time.time() - started
    doc.close()
    return result


def _typeset(work: Path, result: Result, paper: Path, stem: str, suffix: str) -> None:
    """Run tectonic and put the finished paper beside the original."""
    log = work / "tectonic.log"
    finished = subprocess.run(
        ["tectonic", "-X", "compile", "--keep-logs", "main.tex"],
        cwd=work, capture_output=True, text=True,
    )
    log.write_text(finished.stderr or "", encoding="utf-8")
    result.tectonic = finished.returncode
    result.missing_characters = [
        line for line in (finished.stderr or "").splitlines() if "Missing character" in line
    ]

    built = work / "main.pdf"
    if finished.returncode == 0 and built.exists():
        out = paper / f"{stem}_{suffix}.pdf"
        shutil.copy(built, out)
        result.pdf = out
        with pymupdf.open(out) as done:
            result.pages = len(done)
