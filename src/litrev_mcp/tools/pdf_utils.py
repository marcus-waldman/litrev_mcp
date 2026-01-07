"""
PDF utility functions for litrev-mcp.

Provides PDF metadata extraction and fuzzy matching capabilities.
"""

import re
from pathlib import Path
from typing import Any, Optional

import pdfplumber
from PyPDF2 import PdfReader


def extract_pdf_metadata(filepath: Path) -> dict[str, Any]:
    """
    Extract metadata from a PDF file.

    Uses PyPDF2 for document metadata and pdfplumber for text extraction.

    Args:
        filepath: Path to the PDF file

    Returns:
        Dictionary with extracted metadata:
        {
            'title': str or None,
            'authors': str or None,
            'year': str or None,
            'doi': str or None,
            'first_page_text': str,
            'source_file': str
        }
    """
    result = {
        'title': None,
        'authors': None,
        'year': None,
        'doi': None,
        'first_page_text': '',
        'source_file': filepath.name,
    }

    # Try PyPDF2 for document metadata
    try:
        reader = PdfReader(str(filepath))
        metadata = reader.metadata
        if metadata:
            if metadata.title:
                result['title'] = str(metadata.title).strip()
            if metadata.author:
                result['authors'] = str(metadata.author).strip()
    except Exception:
        pass  # Continue with text extraction

    # Use pdfplumber for text extraction
    try:
        with pdfplumber.open(str(filepath)) as pdf:
            if pdf.pages:
                first_page = pdf.pages[0]
                text = first_page.extract_text() or ''
                result['first_page_text'] = text[:2000]  # Limit size

                # Try to extract DOI from text
                doi = extract_doi_from_text(text)
                if doi:
                    result['doi'] = doi

                # Try to extract year if not in metadata
                if not result['year']:
                    year = extract_year_from_text(text)
                    if year:
                        result['year'] = year

                # Try to get title from first lines if not in metadata
                if not result['title']:
                    title = extract_title_from_text(text)
                    if title:
                        result['title'] = title
    except Exception:
        pass

    return result


def extract_doi_from_text(text: str) -> Optional[str]:
    """Extract DOI from text using regex patterns."""
    # Common DOI patterns
    patterns = [
        r'doi[:\s]*([10]\.\d{4,}/[^\s]+)',
        r'https?://doi\.org/([10]\.\d{4,}/[^\s]+)',
        r'([10]\.\d{4,}/[^\s]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            doi = match.group(1).strip()
            # Clean up common trailing characters
            doi = re.sub(r'[.,;)\]]+$', '', doi)
            return doi

    return None


def extract_year_from_text(text: str) -> Optional[str]:
    """Extract publication year from text."""
    # Look for 4-digit years between 1900-2030
    matches = re.findall(r'\b(19\d{2}|20[0-2]\d)\b', text[:500])
    if matches:
        # Return the first reasonable year found
        return matches[0]
    return None


def extract_title_from_text(text: str) -> Optional[str]:
    """Extract likely title from first lines of text."""
    lines = text.split('\n')
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        # Title is usually a longer line without common header patterns
        if len(line) > 20 and len(line) < 300:
            # Skip lines that look like headers/footers
            if not re.match(r'^(volume|issue|page|doi|http|www|copyright)', line, re.I):
                return line
    return None


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ''
    # Lowercase, remove extra whitespace, remove punctuation
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def simple_similarity(s1: str, s2: str) -> float:
    """
    Calculate simple similarity between two strings.

    Uses word overlap ratio as a simple but effective measure.
    """
    if not s1 or not s2:
        return 0.0

    words1 = set(normalize_text(s1).split())
    words2 = set(normalize_text(s2).split())

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)


def fuzzy_match_score(extracted: dict[str, Any], zotero_item: dict[str, Any]) -> float:
    """
    Calculate match score between extracted PDF metadata and a Zotero item.

    Args:
        extracted: Metadata extracted from PDF
        zotero_item: Item from Zotero library

    Returns:
        Score from 0.0 to 1.0 (higher is better match)
    """
    score = 0.0
    weights_used = 0.0

    # DOI match (highest confidence)
    if extracted.get('doi') and zotero_item.get('doi'):
        extracted_doi = extracted['doi'].lower().strip()
        zotero_doi = zotero_item['doi'].lower().strip()
        if extracted_doi == zotero_doi:
            return 1.0  # Perfect match
        # Partial DOI match
        if extracted_doi in zotero_doi or zotero_doi in extracted_doi:
            score += 0.9
            weights_used += 1.0

    # Title similarity (weight: 0.5)
    if extracted.get('title') and zotero_item.get('title'):
        title_sim = simple_similarity(extracted['title'], zotero_item['title'])
        score += title_sim * 0.5
        weights_used += 0.5

    # Author similarity (weight: 0.3)
    if extracted.get('authors') and zotero_item.get('authors'):
        author_sim = simple_similarity(extracted['authors'], zotero_item['authors'])
        score += author_sim * 0.3
        weights_used += 0.3

    # Year match (weight: 0.2)
    if extracted.get('year') and zotero_item.get('year'):
        if str(extracted['year']) == str(zotero_item['year'])[:4]:
            score += 0.2
        weights_used += 0.2

    # Normalize by weights used
    if weights_used > 0:
        return score / weights_used

    return 0.0


def generate_citation_key(title: str, authors: str, year: str) -> str:
    """
    Generate a citation key in the format: author_shorttitle_year.

    Args:
        title: Paper title
        authors: Author string
        year: Publication year

    Returns:
        Citation key string (e.g., "smith_machine_learning_2023")
    """
    # Extract first author's last name
    author_part = "unknown"
    if authors:
        # Try to get first author's last name
        first_author = authors.split(',')[0].split(' and ')[0].strip()
        # Filter out "et al." and initials (1-2 uppercase letters)
        words = [w for w in first_author.split()
                 if w.lower() not in ('et', 'al', 'al.')
                 and not (len(w) <= 2 and w.isupper())]
        if words:
            # Take first remaining word (usually the last name in "LastName FirstName" format)
            author_part = words[0].lower()
            # Remove non-alphanumeric
            author_part = re.sub(r'[^a-z]', '', author_part)

    # Extract short title (first 2-3 meaningful words)
    title_part = "untitled"
    if title:
        # Remove common words
        stop_words = {'the', 'a', 'an', 'of', 'in', 'on', 'for', 'and', 'to', 'with'}
        words = [w.lower() for w in re.findall(r'\w+', title)]
        words = [w for w in words if w not in stop_words and len(w) > 2][:3]
        if words:
            title_part = '_'.join(words)

    # Year
    year_part = str(year)[:4] if year else "0000"

    return f"{author_part}_{title_part}_{year_part}"
