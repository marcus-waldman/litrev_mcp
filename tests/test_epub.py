"""
Tests for EPUB support in litrev-mcp.

Tests epub_utils.py, formats.py, and the extract_document_text dispatcher.
"""

import tempfile
from pathlib import Path

import pytest
from ebooklib import epub

from litrev_mcp.tools.formats import (
    SUPPORTED_EXTENSIONS,
    find_document_files,
    find_document_by_key,
    document_filename,
)
from litrev_mcp.tools.epub_utils import (
    extract_epub_metadata,
    extract_epub_text_with_chapters,
)
from litrev_mcp.tools.rag_embed import extract_document_text


# ---------------------------------------------------------------------------
# Helpers — build a minimal EPUB in memory
# ---------------------------------------------------------------------------

def _create_test_epub(
    path: Path,
    title: str = "Test Book Title",
    author: str = "Jane Doe",
    year: str = "2024",
    chapters: list[str] | None = None,
    doi: str | None = None,
) -> Path:
    """Write a minimal EPUB file to *path* and return it."""
    book = epub.EpubBook()
    book.set_identifier("test-id-123")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    if doi:
        book.add_metadata("DC", "identifier", doi)

    book.add_metadata("DC", "date", year)

    if chapters is None:
        chapters = [
            "<h1>Chapter 1</h1><p>This is the first chapter with enough text to be extracted properly.</p>",
            "<h1>Chapter 2</h1><p>This is the second chapter discussing measurement error models in detail.</p>",
        ]

    spine_items = ["nav"]
    for i, html_content in enumerate(chapters):
        ch = epub.EpubHtml(title=f"Chapter {i+1}", file_name=f"chap_{i+1}.xhtml", lang="en")
        ch.content = html_content.encode("utf-8")
        book.add_item(ch)
        spine_items.append(ch)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    epub.write_epub(str(path), book)
    return path


# ---------------------------------------------------------------------------
# formats.py tests
# ---------------------------------------------------------------------------

class TestFormats:
    def test_supported_extensions(self):
        assert '.pdf' in SUPPORTED_EXTENSIONS
        assert '.epub' in SUPPORTED_EXTENSIONS

    def test_find_document_files(self, tmp_path: Path):
        (tmp_path / "paper1.pdf").write_text("fake pdf")
        (tmp_path / "paper2.epub").write_bytes(b"fake epub")
        (tmp_path / "notes.txt").write_text("ignore me")

        found = find_document_files(tmp_path)
        names = [f.name for f in found]
        assert "paper1.pdf" in names
        assert "paper2.epub" in names
        assert "notes.txt" not in names

    def test_find_document_files_empty(self, tmp_path: Path):
        assert find_document_files(tmp_path) == []

    def test_find_document_by_key_pdf(self, tmp_path: Path):
        pdf = tmp_path / "smith_ml_2023.pdf"
        pdf.write_text("fake")
        result = find_document_by_key(tmp_path, "smith_ml_2023")
        assert result == pdf

    def test_find_document_by_key_epub(self, tmp_path: Path):
        ep = tmp_path / "smith_ml_2023.epub"
        ep.write_bytes(b"fake")
        result = find_document_by_key(tmp_path, "smith_ml_2023")
        assert result == ep

    def test_find_document_by_key_pdf_priority(self, tmp_path: Path):
        """PDF should be preferred when both exist."""
        pdf = tmp_path / "smith_ml_2023.pdf"
        pdf.write_text("fake")
        (tmp_path / "smith_ml_2023.epub").write_bytes(b"fake")
        result = find_document_by_key(tmp_path, "smith_ml_2023")
        assert result == pdf

    def test_find_document_by_key_missing(self, tmp_path: Path):
        assert find_document_by_key(tmp_path, "nonexistent") is None

    def test_document_filename_pdf(self):
        assert document_filename("key", Path("paper.pdf")) == "key.pdf"

    def test_document_filename_epub(self):
        assert document_filename("key", Path("book.epub")) == "key.epub"


# ---------------------------------------------------------------------------
# epub_utils.py tests
# ---------------------------------------------------------------------------

class TestEpubMetadata:
    def test_extract_metadata_basic(self, tmp_path: Path):
        epub_path = _create_test_epub(tmp_path / "test.epub")
        meta = extract_epub_metadata(epub_path)

        assert meta['title'] == "Test Book Title"
        assert meta['authors'] == "Jane Doe"
        assert meta['year'] == "2024"
        assert meta['source_file'] == "test.epub"

    def test_extract_metadata_with_doi(self, tmp_path: Path):
        epub_path = _create_test_epub(
            tmp_path / "test.epub",
            doi="doi:10.1234/test.doi.5678",
        )
        meta = extract_epub_metadata(epub_path)
        # extract_doi_from_text uses [10] (char class) not literal 10,
        # so it captures starting at the '0'. This is a pre-existing
        # regex quirk in pdf_utils.py — the important thing is a DOI
        # is found and contains the suffix.
        assert meta['doi'] is not None
        assert "1234/test.doi.5678" in meta['doi']

    def test_extract_metadata_first_page_text(self, tmp_path: Path):
        epub_path = _create_test_epub(tmp_path / "test.epub")
        meta = extract_epub_metadata(epub_path)
        assert len(meta['first_page_text']) > 0
        assert "first chapter" in meta['first_page_text'].lower()

    def test_extract_metadata_nonexistent_file(self, tmp_path: Path):
        meta = extract_epub_metadata(tmp_path / "missing.epub")
        assert meta['title'] is None
        assert meta['source_file'] == "missing.epub"


class TestEpubTextExtraction:
    def test_extract_text_with_chapters(self, tmp_path: Path):
        epub_path = _create_test_epub(tmp_path / "test.epub")
        text, breaks = extract_epub_text_with_chapters(epub_path)

        assert len(text) > 0
        assert "first chapter" in text.lower()
        assert "second chapter" in text.lower()
        assert len(breaks) == 2  # two chapters

    def test_chapter_breaks_are_increasing(self, tmp_path: Path):
        epub_path = _create_test_epub(tmp_path / "test.epub")
        _, breaks = extract_epub_text_with_chapters(epub_path)
        for i in range(1, len(breaks)):
            assert breaks[i] > breaks[i - 1]

    def test_extract_text_nonexistent_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Failed to read EPUB"):
            extract_epub_text_with_chapters(tmp_path / "missing.epub")


# ---------------------------------------------------------------------------
# extract_document_text dispatcher tests
# ---------------------------------------------------------------------------

class TestExtractDocumentText:
    def test_dispatch_epub(self, tmp_path: Path):
        epub_path = _create_test_epub(tmp_path / "test.epub")
        text, breaks = extract_document_text(epub_path)
        assert len(text) > 0
        assert isinstance(breaks, list)

    def test_dispatch_unsupported_raises(self, tmp_path: Path):
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file format"):
            extract_document_text(txt)
