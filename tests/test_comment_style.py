"""Style guard: no comment block may run longer than two lines.

Prose that needs a third line belongs in the code itself (a named helper, a
clearer signature) or in a docstring. Only standalone ``#`` comments count --
trailing comments on a code line, docstrings, and comments separated by a
blank line are all untouched.
"""

from __future__ import annotations

import tokenize
from pathlib import Path

MAX_COMMENT_LINES = 2
REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "tests", "scripts")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for name in SCAN_DIRS:
        directory = REPO_ROOT / name
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def _standalone_comment_lines(path: Path) -> list[int]:
    """Line numbers of comments that occupy their whole line."""
    source_lines = path.read_text().splitlines()
    with path.open("rb") as handle:
        comments = [
            token
            for token in tokenize.tokenize(handle.readline)
            if token.type == tokenize.COMMENT
        ]
    return sorted(
        {
            token.start[0]
            for token in comments
            if source_lines[token.start[0] - 1].lstrip().startswith("#")
        }
    )


def _long_blocks(path: Path) -> list[tuple[int, int]]:
    """``(start_line, length)`` for every comment block over the limit."""
    blocks: list[tuple[int, int]] = []
    run: list[int] = []
    for line in _standalone_comment_lines(path) + [-1]:
        if run and line == run[-1] + 1:
            run.append(line)
            continue
        if len(run) > MAX_COMMENT_LINES:
            blocks.append((run[0], len(run)))
        run = [line]
    return blocks


def test_no_comment_block_exceeds_two_lines():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{start} ({length} lines)"
        for path in _python_files()
        for start, length in _long_blocks(path)
    ]
    assert not offenders, (
        f"Comment blocks longer than {MAX_COMMENT_LINES} lines:\n  "
        + "\n  ".join(offenders)
        + "\nRewrite the code to carry the explanation, or move it to a docstring."
    )


def test_guard_detects_a_long_block(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("# one\n# two\n# three\nx = 1\n")
    assert _long_blocks(sample) == [(1, 3)]


def test_guard_allows_two_lines_and_trailing_comments(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('# one\n# two\nx = 1  # trailing\ny = "# not a comment"\n')
    assert _long_blocks(sample) == []
