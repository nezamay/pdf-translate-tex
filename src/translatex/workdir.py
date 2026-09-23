"""Where a paper's files live.

A paper owns a directory named after it, holding the original, the translation and a
working tree. The rule matters because the working tree is per-paper: crops, the
generated .tex and the tracking record all belong to one document, and a PDF left
loose in a downloads folder would scatter them next to unrelated files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

WORK_DIRNAME = ".translatex"


def ensure_paper_dir(src: Path) -> Path:
    """Return the directory owning `src`, moving the file into it when needed.

    A PDF already sitting in a directory named after it is left where it is.
    """
    src = Path(src).resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    if src.parent.name == src.stem:
        return src.parent

    target = src.parent / src.stem
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(target)
    target.mkdir(exist_ok=True)

    moved = target / src.name
    # Never overwrite: a same-named file in there is a different copy of the paper, and
    # which of the two is wanted is not ours to decide.
    if moved.exists():
        raise FileExistsError(moved)
    shutil.move(str(src), str(moved))
    return target


def work_dir(paper_dir: Path) -> Path:
    """The paper's working tree, created on first use."""
    d = Path(paper_dir) / WORK_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d
