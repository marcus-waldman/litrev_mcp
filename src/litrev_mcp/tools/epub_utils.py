"""
EPUB utility functions for litrev-mcp.

Provides EPUB metadata extraction and text extraction with chapter breaks,
parallel to ``pdf_utils.py`` for PDFs.
"""

import re
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any, Optional

import ebooklib
from ebooklib import epub

from litrev_mcp.tools.pdf_utils import (
    extract_doi_from_text,
    extract_year_from_text,
    extract_title_from_text,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text converter that strips tags."""

    def __init__(self):
        super().__init__()
        self._buf = StringIO()
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ('script', 'style'):
            self._skip = True
        elif tag in ('p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr'):
            self._buf.write('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style'):
            self._skip = False
        elif tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._buf.write('\n')

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buf.write(data)

    def get_text(self) -> str:
        return self._buf.getvalue()


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _clean_epub_text(text: str) -> str:
    """Normalise whitespace in extracted EPUB text."""
    # Collapse runs of whitespace within lines
    text = re.sub(r'[^\S\n]+', ' ', text)
    # Collapse runs of blank lines into at most two newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip leading/trailing whitespace on each line
    lines = [line.strip() for line in text.splitlines()]
    return '\n'.join(lines).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_epub_metadata(filepath: Path) -> dict[str, Any]:
    """Extract metadata from an EPUB file.

    Returns the same dict shape as ``extract_pdf_metadata()`` so callers can
    treat both formats uniformly.

    Keys: title, authors, year, doi, first_page_text, source_file
    """
    result: dict[str, Any] = {
        'title': None,
        'authors': None,
        'year': None,
        'doi': None,
        'first_page_text': '',
        'source_file': filepath.name,
    }

    try:
        book = epub.read_epub(str(filepath), options={'ignore_ncx': True})
    except Exception:
        return result

    # Dublin Core metadata -------------------------------------------------
    try:
        titles = book.get_metadata('DC', 'title')
        if titles:
            result['title'] = str(titles[0][0]).strip()
    except Exception:
        pass

    try:
        creators = book.get_metadata('DC', 'creator')
        if creators:
            names = [str(c[0]).strip() for c in creators]
            result['authors'] = ', '.join(names)
    except Exception:
        pass

    try:
        dates = book.get_metadata('DC', 'date')
        if dates:
            year = extract_year_from_text(str(dates[0][0]))
            if year:
                result['year'] = year
    except Exception:
        pass

    # Try identifier for DOI
    try:
        identifiers = book.get_metadata('DC', 'identifier')
        for ident in identifiers:
            val = str(ident[0]).strip()
            doi = extract_doi_from_text(val)
            if doi:
                result['doi'] = doi
                break
    except Exception:
        pass

    # Extract first chapter text for fallback metadata ---------------------
    try:
        first_text = ''
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content()
            text = _strip_html(content.decode('utf-8', errors='replace'))
            text = _clean_epub_text(text)
            if len(text) > 50:  # skip trivial items (covers, nav)
                first_text = text[:2000]
                break

        result['first_page_text'] = first_text

        if first_text:
            if not result['doi']:
                doi = extract_doi_from_text(first_text)
                if doi:
                    result['doi'] = doi

            if not result['year']:
                year = extract_year_from_text(first_text)
                if year:
                    result['year'] = year

            if not result['title']:
                title = extract_title_from_text(first_text)
                if title:
                    result['title'] = title
    except Exception:
        pass

    return result


def extract_epub_text_with_chapters(filepath: Path) -> tuple[str, list[int]]:
    """Extract full text from an EPUB with chapter-break positions.

    Returns the same ``(full_text, break_positions)`` shape as
    ``extract_pdf_text_with_pages()`` so callers can treat both formats
    uniformly.  Each chapter maps to a "page" for chunking/citation purposes.
    """
    try:
        book = epub.read_epub(str(filepath), options={'ignore_ncx': True})
    except Exception as e:
        raise ValueError(f"Failed to read EPUB: {e}")

    full_text = ''
    chapter_breaks: list[int] = []

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content()
        text = _strip_html(content.decode('utf-8', errors='replace'))
        text = _clean_epub_text(text)
        if len(text) <= 50:
            continue  # skip trivial items (covers, nav, etc.)

        chapter_breaks.append(len(full_text))
        full_text += text + '\n\n'

    if not full_text.strip():
        raise ValueError("No extractable text found in EPUB")

    return full_text.strip(), chapter_breaks
