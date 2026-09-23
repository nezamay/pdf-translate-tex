"""Writing the translated paper back out as LaTeX.

The page is built again rather than patched, which is the whole reason for the detour
through LaTeX: there are no fixed boxes to overflow, so the spacing around an equation is
computed by TeX and is the same everywhere. What is lost is the page-for-page
correspondence with the original, which no amount of care would have preserved anyway
once the text changed length.

Three things are shown from the original rather than rewritten, because the text layer
does not contain them: a figure, a display equation whose rules are drawn strokes, and a
glyph nobody could identify. The first two are shown in place with `trim`; the third is a
small picture, for reasons measured in `translatex.pdfin.crops`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field

from translatex.mask import Masked
from translatex.pdfin.crops import Crop
from translatex.pdfin.roles import Role

#: TeX reads these as instructions unless they are spelled out.
ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

#: How deep a heading sits, by what its number looks like: "II." is a section, "B." a
#: subsection, "3)" the level below that. The journals in the corpus all number this way.
DEPTHS = (
    (re.compile(r"^[IVXLC]+\."), 0),
    (re.compile(r"^[A-Z]\."), 1),
    (re.compile(r"^\d+\)"), 2),
    (re.compile(r"^\d+(\.\d+)+"), 1),
)

SECTIONS = ("section", "subsection", "subsubsection")

#: An equation number set on its own, which the publisher puts in a block of its own.
LONE_NUMBER = re.compile(r"^\(\d+[a-z]?\)$")


def escape(text: str) -> str:
    """The same text with every character TeX would act on spelled out.

    Control characters are dropped rather than escaped. TeX cannot set them at all — it
    stops with "Text line contains an invalid character" — and they only ever arrive
    here from a symbol font's private arrangement, which is reproduced as a picture
    somewhere else or not at all.
    """
    return "".join(ESCAPES.get(char, char) for char in text if char >= " " or char == "\n")


@dataclass
class Assets:
    """The pictures a document needs, gathered as it is written."""

    source: str
    glyphs: dict[str, Crop] = field(default_factory=dict)

    def glyph(self, crop: Crop) -> str:
        self.glyphs[crop.name] = crop
        return crop.name


def preamble(*, page: tuple[float, float], columns: int, body_size: float,
             language: str = "russian") -> str:
    """A preamble that puts the text back on a page the size of the original one.

    The measure is copied and the type size is copied; the line breaks are not, and
    cannot be. Liberation Serif is Times-metric and carries Cyrillic, so the page looks
    like the journal's rather than like Computer Modern's idea of a journal.
    """
    width, height = page
    return "\n".join([
        r"\documentclass[%gpt]{article}" % round(body_size),
        r"\usepackage[paperwidth=%.1fbp,paperheight=%.1fbp,margin=42bp]{geometry}"
        % (width, height),
        r"\usepackage{fontspec}",
        r"\usepackage{polyglossia}",
        r"\setmainlanguage{%s}" % language,
        r"\setotherlanguage{english}",
        r"\setmainfont{Liberation Serif}",
        r"\setsansfont{Liberation Sans}",
        r"\usepackage{graphicx}",
        r"\usepackage{amsmath}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{multicol}" if columns > 1 else "",
        r"\setlength{\parskip}{0pt}",
        r"\setlength{\emergencystretch}{3em}",
        r"\pagestyle{plain}",
    ])


def _heading(raw: str, rendered: str) -> str:
    """A heading at the depth its own numbering implies, keeping that numbering.

    Every level is starred, so LaTeX adds none of its own. The paper numbers its own
    sections and its own text refers to them — "as shown in Section III" has to keep
    pointing at the section the author called III, not at whatever LaTeX counts to.
    """
    for pattern, depth in DEPTHS:
        if pattern.match(raw):
            return "\\%s*{%s}" % (SECTIONS[depth], rendered)
    return "\\section*{%s}" % rendered


def _picture(crop: Crop, trim: tuple[float, float, float, float], *,
             source: str, width: str) -> str:
    left, bottom, right, top = trim
    return (
        r"\includegraphics[page=%d,trim=%.2fbp %.2fbp %.2fbp %.2fbp,clip,%s]{%s}"
        % (crop.page + 1, left, bottom, right, top, width, source)
    )


def _fitted(crop: Crop, trim: tuple[float, float, float, float], source: str) -> str:
    """A picture at its own size, shrunk only if it would not fit the measure.

    A display equation is usually narrower than the column and blowing it up to the full
    width would set it at a size nothing else on the page is. The few that overrun — a
    long derivation, a wide matrix — are brought back in.
    """
    return (
        r"\resizebox{\ifdim\width>\linewidth\linewidth\else\width\fi}{!}{%s}"
        % _picture(crop, trim, source=source, width="height=%.2fbp" % crop.height)
    )


def render_maths(masked: Masked, translated: str, assets: Assets,
                 glyphs: dict[tuple[str, str], Crop], trim_of) -> str:
    """The translated sentence with each expression put back as something TeX can set.

    An expression whose characters were all identified goes back as italic text rather
    than as real mathematics. That is a deliberate first cut: these fragments are already
    a linear run of symbols, and `$...$` would need a maths font covering every Greek
    letter and operator the publisher used. What cannot be identified goes back as the
    picture of itself, sized to its own ink so it sits on the line at the height it had.

    Escaping happens here, before the expressions go in: done the other way round, the
    commands that set them would be escaped too. The markers are escaped along with
    everything else, so it is their escaped form that gets replaced.
    """
    out = escape(translated)
    for piece in masked.pieces:
        out = out.replace(escape(piece.marker), _expression(piece, assets, glyphs, trim_of))
    return out


def _expression(piece, assets: Assets, glyphs: dict[tuple[str, str], Crop], trim_of) -> str:
    parts: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            parts.append(r"\textit{%s}" % escape("".join(run)))
            run.clear()

    for char in piece.chars:
        if char.readable:
            run.append(char.text)
            continue
        flush()
        crop = glyphs.get((char.font, char.text))
        if crop is None:
            continue
        parts.append(
            r"\raisebox{-0.2ex}{\includegraphics[height=%.2fbp]{%s.png}}"
            % (crop.height, assets.glyph(crop))
        )
    flush()
    return "".join(parts)


def document(
    paragraphs: list,
    roles: list[Role],
    rendered: dict[int, str],
    figures: dict[int, Crop],
    equations: dict[int, Crop],
    *,
    source: str,
    page: tuple[float, float],
    columns: int,
    body_size: float,
    trim_of,
    assets: Assets | None = None,
    babel: str = "russian",
    skip: set[int] | None = None,
) -> str:
    """The whole paper as one LaTeX source.

    `rendered` holds finished LaTeX for the paragraphs that went through translation,
    keyed by index — finished because escaping has to happen before the expressions are
    put back, or the commands that set them would be escaped too. Anything absent is
    escaped here and emitted as it stood, which is what becomes of a byline, a reference
    and an equation.
    """
    assets = assets or Assets(source)
    skip = skip or set()
    body: list[str] = []

    for index, (paragraph, role) in enumerate(zip(paragraphs, roles, strict=True)):
        # Swallowed by the equation above it: a display equation is laid out as a row of
        # separate blocks and only the first of them carries the region.
        if index in skip:
            continue
        raw = paragraph.text.strip()
        text = rendered.get(index) or escape(raw)
        if not raw:
            continue

        if role is Role.RUNNING or role is Role.FRONTMATTER:
            continue
        if role is Role.TITLE:
            body.append(r"\begin{center}{\LARGE %s}\end{center}" % text)
        elif role is Role.AUTHORS:
            body.append(r"\begin{center}%s\end{center}" % text)
        elif role is Role.ABSTRACT:
            body.append(r"\noindent\textbf{%s}" % text)
        elif role is Role.HEADING:
            body.append(_heading(raw, text))
        elif role is Role.CAPTION:
            crop = figures.get(index)
            if crop is None:
                body.append(r"\noindent\textit{%s}" % text)
            else:
                # Not a float. multicol drops a `figure` silently — the picture simply
                # never appears — and there is nothing to float towards anyway: the page
                # is being rebuilt, so where the figure falls in the text is where the
                # author put it.
                body.append(
                    "\\begin{center}\n%s\n\\par\\smallskip\n\\textit{%s}\n\\end{center}"
                    % (_fitted(crop, trim_of(crop), source), text)
                )
        elif role is Role.EQUATION:
            # A display equation is shown, not transcribed: its fraction bars and matrix
            # rules are drawn strokes that the text layer does not contain, so whatever
            # the characters say, they do not say what is on the page.
            if LONE_NUMBER.match(raw):
                continue
            crop = equations.get(index)
            if crop is None:
                body.append(r"\begin{center}%s\end{center}" % text)
            else:
                body.append(
                    "\\begin{center}\n%s\n\\end{center}" % _fitted(crop, trim_of(crop), source)
                )
        elif role is Role.REFERENCE:
            body.append(r"\noindent %s\par" % text)
        else:
            body.append(text)

    inner = "\n\n".join(part for part in body if part)
    if columns > 1:
        inner = "\\begin{multicols}{%d}\n%s\n\\end{multicols}" % (columns, inner)
    return "%s\n\\begin{document}\n%s\n\\end{document}\n" % (
        preamble(page=page, columns=columns, body_size=body_size, language=babel),
        inner,
    )
