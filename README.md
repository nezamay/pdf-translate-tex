# pdf-translate-tex

Translate a scientific paper into another language by **rebuilding the page in LaTeX**,
rather than fitting the translation back into the original PDF's coordinates.

## Why not reflow the original

The usual tools (pdf2zh / BabelDOC and friends) keep every block where the publisher put
it and swap the text inside. Russian runs longer than English, so the lines grow while
the formula blocks stay pinned: a display equation ends up with a gap above it and the
following paragraph printed over it. That is not a bug in those tools, it is what fitting
new text into fixed boxes must do.

Typesetting the paper again removes the cause. There are no fixed boxes — one vertical
flow, with the spacing around display maths computed by TeX and identical throughout.
The price is that the result no longer matches the original page for page.

## Two ways in

| Input | What we do |
|---|---|
| arXiv e-print | Translate the `.tex` directly. No layout to recover. |
| Publisher PDF (Elsevier, IEEE) | Recover the structure: characters and boxes from pymupdf, display formulas and figures cropped out as images, inline maths decoded through a per-font glyph table. |

The second path exists because publisher PDFs of this kind carry no `ToUnicode` map and
draw Greek letters with Latin character codes, so the text layer alone is not readable.

## Layout

    src/translatex/
      cli.py          command line entry point
      workdir.py      where a paper's files live
      arxiv/          e-print download, .tex parsing
      pdfin/          characters, boxes, words, fonts, crops
      glyphs/         code -> symbol tables for subset maths fonts
      mask.py         maths <-> placeholders, shared by both paths
      translate.py    the translation backend
      emit/           structure -> .tex, plus the preamble
      build.py        tectonic, and what its log says went wrong
      check.py        acceptance counters

A paper keeps everything in one directory named after it:

    Some_Paper_Title/
      Some_Paper_Title.pdf        the original
      Some_Paper_Title_ru.pdf     the result
      .translatex/
        main.tex
        figures/
        blocks.json               structure as extracted, before translation
        tracking.json             input, output and placeholders per paragraph
        tectonic.log

`tracking.json` is not bookkeeping. The equivalent file in BabelDOC is what proved that
every mangled formula in an earlier effort was already mangled *before* the translator
saw it — correct in the PDF, broken in the input, faithfully reproduced on output.
Without that record the debugging is blind.

## Status

Early. Nothing translates yet; see the plan in the tracking issue.

## Install

    pip install -e .

The layout model is optional and off by default:

    pip install -e '.[layout]'

`tectonic` is expected on `PATH` (a static LaTeX engine, no TeX Live needed).
