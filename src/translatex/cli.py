"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import pymupdf

from translatex.glyphs import decide_fonts
from translatex.pdfin import read_chars
from translatex.pdfin import unreadable_runs
from translatex.check import check
from translatex.pipeline import parse_pages
from translatex.pipeline import run
from translatex.workdir import ensure_paper_dir
from translatex.workdir import work_dir

# 2301.01234 and 2301.01234v2, plus the pre-2007 form math.GT/0309136.
ARXIV_ID = re.compile(r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7})$")

GREEK = re.compile(r"[Ͱ-Ͽ]")


def classify_source(source: str) -> str:
    """Which of the two input paths `source` names."""
    if ARXIV_ID.match(source) or "arxiv.org" in source:
        return "arxiv"
    return "pdf"


def report_fonts(path: Path) -> int:
    """Print what the glyph pass made of a PDF, so a paper can be judged before use."""
    doc = pymupdf.open(path)
    verdicts = decide_fonts(doc)
    chars = read_chars(doc, verdicts)

    corrected = [v for v in verdicts.values() if v.corrected]
    print(f"{path.name}\n{len(doc)} pages, {len(chars)} characters, {len(verdicts)} fonts")

    if corrected:
        print("\ncorrected fonts")
        for verdict in corrected:
            pairs = " ".join(f"{chr(c)}->{ch}" for c, ch in sorted(verdict.overrides.items()))
            print(f"  {verdict.font} read as {verdict.reading}: {pairs}")
            for reference, errors in verdict.errors.items():
                scored = " ".join(f"{name}={err:.3f}" for name, err in errors.items())
                print(f"      vs {reference}: {scored}")
    else:
        print("\nno font needed correcting")

    greek = Counter(c.text for c in chars if GREEK.match(c.text))
    if greek:
        total = sum(greek.values())
        print(f"\ngreek letters: {total} in {len(greek)} kinds — "
              + " ".join(f"{ch}x{n}" for ch, n in greek.most_common()))

    runs = unreadable_runs(chars)
    unreadable = sum(len(r) for r in runs)
    share = 100.0 * unreadable / max(len(chars), 1)
    print(f"\nto be cropped: {unreadable} characters ({share:.2f}%) in {len(runs)} runs")
    by_font = Counter(r[0].font for r in runs)
    for font, n in by_font.most_common(8):
        print(f"  {font}: {n} runs")
    doc.close()
    return 0


def translate(args: argparse.Namespace) -> int:
    kind = args.source_kind if args.source_kind != "auto" else classify_source(args.source)
    if kind == "arxiv":
        print(f"arxiv path is not implemented yet: {args.source}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    result = run(
        Path(args.source),
        language=args.lang,
        claude=shutil.which("claude") or "claude",
        model=args.model,
        limit=args.limit,
        build=not args.no_build,
        pages=parse_pages(args.pages),
    )

    print(f"paper:     {result.paper}")
    print(f"tex:       {result.tex}")
    print(f"translated {result.translated} paragraphs, held {result.untranslated}")
    print(f"figures {result.figures}, equations {result.equations}, glyphs {result.glyphs}")
    if result.pdf:
        print(f"pdf:       {result.pdf}  ({result.pages} pages)")
    else:
        print(f"tectonic exited {result.tectonic}; see {result.tex.parent / 'tectonic.log'}")
    if result.missing_characters:
        print(f"missing characters: {len(result.missing_characters)}")
    print(f"took {result.seconds:.0f}s")
    return 0 if result.pdf else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translatex",
        description="Translate a paper by rebuilding it in LaTeX.",
    )
    commands = parser.add_subparsers(dest="command")

    run = commands.add_parser("translate", help="translate a paper (default)")
    run.add_argument("source", help="a PDF path, an arXiv id, or an arXiv URL")
    run.add_argument("--lang", default="ru", help="target language (default: ru)")
    run.add_argument("--model", default="sonnet", help="translator model (default: sonnet)")
    run.add_argument("--limit", type=int, help="stop after this many paragraphs")
    run.add_argument("--no-build", action="store_true", help="write the .tex and stop")
    run.add_argument("--pages", help="only these pages, counted from one: 1, 1-3, 1,4-5")
    run.add_argument(
        "--source-kind",
        choices=("auto", "pdf", "arxiv"),
        default="auto",
        help="override the guess made from SOURCE",
    )

    judge = commands.add_parser(
        "check",
        help="say whether a finished translation holds together",
    )
    judge.add_argument("paper", type=Path, help="the paper's directory")

    fonts = commands.add_parser(
        "fonts",
        help="report what the glyph pass makes of a PDF, without translating it",
    )
    fonts.add_argument("pdf", type=Path)
    return parser


COMMANDS = ("translate", "fonts", "check")


def with_default_command(argv: list[str]) -> list[str]:
    """`translatex paper.pdf` keeps meaning what it used to.

    A first argument that names no command is the thing to translate, which is the case
    the tool is reached for most often.
    """
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        return ["translate", *argv]
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = with_default_command(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(argv)
    if args.command == "fonts":
        return report_fonts(args.pdf)
    if args.command == "check":
        report = check(args.paper)
        print("\n".join(report.lines()))
        return 0 if report.ok else 1
    if args.command == "translate":
        return translate(args)
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
