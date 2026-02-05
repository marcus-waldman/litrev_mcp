"""
Embedding and text processing module for RAG.

Handles PDF text extraction with page tracking, text chunking,
and OpenAI embedding generation.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

import pdfplumber
from openai import OpenAI

from litrev_mcp.config import config_manager

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Error during embedding generation."""
    pass


def get_openai_client() -> OpenAI:
    """Get OpenAI client from environment variable."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingError(
            "OPENAI_API_KEY environment variable not set. "
            "Add to your shell config: export OPENAI_API_KEY='your-key'"
        )
    return OpenAI(api_key=api_key)


def get_embedding_dimensions() -> int:
    """Get configured embedding dimensions."""
    return config_manager.config.rag.embedding_dimensions


def embed_texts(texts: list[str], dimensions: Optional[int] = None) -> list[list[float]]:
    """
    Generate embeddings for a list of texts using OpenAI.

    Uses text-embedding-3-small model with configurable dimensions.
    Automatically splits large inputs into token-aware batches to stay
    within OpenAI's per-request token limit (~300K tokens).
    Cost: ~$0.02 per 1M tokens.

    Args:
        texts: List of text strings to embed
        dimensions: Override dimensions (default: use config value)

    Returns:
        List of embedding vectors with configured dimensions
    """
    if not texts:
        return []

    client = get_openai_client()
    dims = dimensions if dimensions is not None else get_embedding_dimensions()

    # Split into token-aware batches.
    # Our word_count * 1.3 heuristic underestimates actual BPE tokens by ~20-25%
    # for scientific text, so we use 200K to stay safely under OpenAI's 300K limit.
    max_tokens_per_batch = 200_000
    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_tokens = 0

    for text in texts:
        text_tokens = _estimate_tokens(text)
        if current_batch and current_tokens + text_tokens > max_tokens_per_batch:
            batches.append(current_batch)
            current_batch = [text]
            current_tokens = text_tokens
        else:
            current_batch.append(text)
            current_tokens += text_tokens
    if current_batch:
        batches.append(current_batch)

    try:
        all_embeddings: list[list[float]] = []
        for batch in batches:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=batch,
                dimensions=dims
            )
            all_embeddings.extend([item.embedding for item in response.data])
        return all_embeddings
    except Exception as e:
        raise EmbeddingError(f"Failed to generate embeddings: {e}")


def embed_query(query: str) -> list[float]:
    """Generate embedding for a single query."""
    return embed_texts([query])[0]


def extract_pdf_text_with_pages(filepath: Path) -> tuple[str, list[int]]:
    """
    Extract full text from PDF with page break positions.

    Args:
        filepath: Path to PDF file

    Returns:
        Tuple of (full_text, page_break_positions)
        page_break_positions is list of character indices where each page starts
    """
    full_text = ""
    page_breaks = []

    try:
        with pdfplumber.open(str(filepath)) as pdf:
            for page in pdf.pages:
                page_breaks.append(len(full_text))
                page_text = page.extract_text() or ""
                # Clean up text
                page_text = _clean_text(page_text)
                full_text += page_text + "\n\n"
    except Exception as e:
        raise ValueError(f"Failed to extract text from PDF: {e}")

    return full_text.strip(), page_breaks


def extract_pdf_text(filepath: Path, use_mathpix: bool = False) -> tuple[str, list[int]]:
    """Extract text from a PDF, optionally using Mathpix with pdfplumber fallback.

    Args:
        filepath: Path to PDF file
        use_mathpix: If True, try Mathpix first, fall back to pdfplumber on error

    Returns:
        Tuple of (full_text, page_break_positions)
    """
    if use_mathpix:
        try:
            from litrev_mcp.tools.mathpix import (
                extract_pdf_text_with_pages_mathpix,
                MathpixError,
            )
            return extract_pdf_text_with_pages_mathpix(filepath)
        except Exception as e:
            logger.warning(f"Mathpix extraction failed, falling back to pdfplumber: {e}")
    return extract_pdf_text_with_pages(filepath)


def _clean_text(text: str) -> str:
    """Clean extracted PDF text."""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove page numbers that appear alone
    text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text.strip()


def chunk_text(
    text: str,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
    page_breaks: Optional[list[int]] = None,
) -> list[dict]:
    """
    Split text into overlapping chunks optimized for semantic search.

    Strategy:
    1. Split text into paragraphs (double newline or sentence boundaries)
    2. Accumulate paragraphs until target_tokens reached
    3. Include overlap from previous chunk for context continuity
    4. Track page numbers using page_breaks positions

    Args:
        text: Full text to chunk
        target_tokens: Target tokens per chunk (~500 optimal for search)
        overlap_tokens: Overlap tokens between chunks
        page_breaks: Character positions where pages start (from extract_pdf_text_with_pages)

    Returns:
        List of chunk dicts with: text, chunk_index, page_number, char_start, char_end
    """
    if not text.strip():
        return []

    # Split into paragraphs
    paragraphs = _split_into_paragraphs(text)

    chunks = []
    current_chunk_text = ""
    current_chunk_start = 0
    char_position = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        # If adding this paragraph exceeds target, finalize current chunk
        current_tokens = _estimate_tokens(current_chunk_text)
        if current_tokens > 0 and current_tokens + para_tokens > target_tokens:
            # Finalize current chunk
            chunk_end = char_position
            page_num = _get_page_number(current_chunk_start, page_breaks)

            chunks.append({
                'text': current_chunk_text.strip(),
                'chunk_index': len(chunks),
                'page_number': page_num,
                'char_start': current_chunk_start,
                'char_end': chunk_end,
            })

            # Start new chunk with overlap
            overlap_text = _get_overlap_text(current_chunk_text, overlap_tokens)
            current_chunk_text = overlap_text + " " + para if overlap_text else para
            current_chunk_start = char_position - len(overlap_text) if overlap_text else char_position
        else:
            # Add paragraph to current chunk
            if current_chunk_text:
                current_chunk_text += " " + para
            else:
                current_chunk_text = para
                current_chunk_start = char_position

        char_position += len(para) + 2  # +2 for paragraph separator

    # Don't forget the last chunk
    if current_chunk_text.strip():
        page_num = _get_page_number(current_chunk_start, page_breaks)
        chunks.append({
            'text': current_chunk_text.strip(),
            'chunk_index': len(chunks),
            'page_number': page_num,
            'char_start': current_chunk_start,
            'char_end': len(text),
        })

    return chunks


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    # Split on double newlines or sentence-ending punctuation followed by space
    paragraphs = re.split(r'\n\n+', text)

    # Filter empty paragraphs and normalize
    result = []
    for para in paragraphs:
        para = para.strip()
        if para and len(para) > 10:  # Skip very short fragments
            result.append(para)

    return result


def _estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Uses simple word count * 1.3 approximation to avoid tokenizer dependency.
    """
    if not text:
        return 0
    word_count = len(text.split())
    return int(word_count * 1.3)


def _get_page_number(char_position: int, page_breaks: Optional[list[int]]) -> Optional[int]:
    """
    Determine page number for a character position.

    Returns 1-indexed page number.
    """
    if not page_breaks:
        return None

    page_num = 1
    for i, break_pos in enumerate(page_breaks):
        if char_position >= break_pos:
            page_num = i + 1
        else:
            break

    return page_num


def _get_overlap_text(text: str, overlap_tokens: int) -> str:
    """Get the last N tokens worth of text for overlap."""
    if not text or overlap_tokens <= 0:
        return ""

    words = text.split()
    # Convert token estimate to word count
    overlap_words = int(overlap_tokens / 1.3)

    if len(words) <= overlap_words:
        return text

    return " ".join(words[-overlap_words:])
