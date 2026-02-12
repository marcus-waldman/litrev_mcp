"""
Centralized format constants and helpers for litrev-mcp.

Keeps the list of supported document extensions in one place so that adding
a new format only requires a one-line change here.
"""

from pathlib import Path
from typing import Optional


SUPPORTED_EXTENSIONS = ('.pdf', '.epub')


def find_document_files(directory: Path) -> list[Path]:
    """Glob for all supported document files in *directory* (non-recursive).

    Returns a list of Path objects sorted by name.
    """
    files: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(directory.glob(f"*{ext}"))
    files.sort(key=lambda p: p.name)
    return files


def find_document_by_key(directory: Path, citation_key: str) -> Optional[Path]:
    """Check for ``{citation_key}.pdf``, ``{citation_key}.epub``, etc.

    Returns the first match found (priority follows SUPPORTED_EXTENSIONS order),
    or ``None`` if no file exists.
    """
    for ext in SUPPORTED_EXTENSIONS:
        candidate = directory / f"{citation_key}{ext}"
        if candidate.exists():
            return candidate
    return None


def document_filename(citation_key: str, source_path: Path) -> str:
    """Build a target filename preserving the original file's extension.

    >>> document_filename("smith_ml_2023", Path("paper.epub"))
    'smith_ml_2023.epub'
    """
    return f"{citation_key}{source_path.suffix}"
