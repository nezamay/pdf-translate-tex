"""Command line entry point."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from translatex.workdir import ensure_paper_dir
from translatex.workdir import work_dir

# 2301.01234 and 2301.01234v2, plus the pre-2007 form math.GT/0309136.
ARXIV_ID = re.compile(r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7})$")


def classify_source(source: str) -> str:
    """Which of the two input paths `source` names."""
    if ARXIV_ID.match(source) or "arxiv.org" in source:
        return "arxiv"
    return "pdf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="translatex",
        description="Translate a paper by rebuilding it in LaTeX.",
    )
    parser.add_argument("source", help="a PDF path, an arXiv id, or an arXiv URL")
    parser.add_argument("--lang", default="ru", help="target language (default: ru)")
    parser.add_argument(
        "--source-kind",
        choices=("auto", "pdf", "arxiv"),
        default="auto",
        help="override the guess made from SOURCE",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kind = args.source_kind if args.source_kind != "auto" else classify_source(args.source)

    if kind == "arxiv":
        print(f"arxiv path is not implemented yet: {args.source}", file=sys.stderr)
        return 2

    paper = ensure_paper_dir(Path(args.source))
    print(f"paper: {paper}")
    print(f"work:  {work_dir(paper)}")
    print("pdf path is not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
