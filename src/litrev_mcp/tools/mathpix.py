"""
Mathpix PDF conversion module.

Provides PDF-to-markdown conversion using the Mathpix API (mpxpy SDK),
with file-based caching and adaptive batching for large PDFs.
"""

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from PyPDF2 import PdfReader

from litrev_mcp.config import config_manager

logger = logging.getLogger(__name__)


class MathpixError(Exception):
    """Error during Mathpix conversion."""
    pass


def get_mathpix_client():
    """Get configured Mathpix client from environment variables.

    Requires MATHPIX_APP_ID and MATHPIX_APP_KEY to be set.

    Returns:
        MathpixClient instance
    """
    app_id = os.environ.get("MATHPIX_APP_ID")
    app_key = os.environ.get("MATHPIX_APP_KEY")

    if not app_id or not app_key:
        raise MathpixError(
            "MATHPIX_APP_ID and MATHPIX_APP_KEY environment variables must be set. "
            "Get credentials from https://accounts.mathpix.com/"
        )

    try:
        from mpxpy.mathpix_client import MathpixClient
    except ImportError:
        raise MathpixError(
            "mpxpy package not installed. Run: pip install mpxpy"
        )

    return MathpixClient(app_id=app_id, app_key=app_key)


def _get_cache_dir() -> Path:
    """Get the Mathpix cache directory, creating it if needed."""
    lit_path = config_manager.literature_path
    if not lit_path:
        raise MathpixError("Literature path not configured")

    cache_dir = lit_path / ".litrev" / "mathpix_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_cache_key(filepath: Path) -> str:
    """Get a cache key based on SHA256 hash of file contents."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _get_cached(cache_key: str) -> Optional[str]:
    """Check if a cached conversion exists and return its contents."""
    try:
        cache_dir = _get_cache_dir()
        cache_file = cache_dir / f"{cache_key}.md"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
    except Exception:
        pass
    return None


def _save_cache(cache_key: str, markdown: str) -> None:
    """Save converted markdown to cache."""
    try:
        cache_dir = _get_cache_dir()
        cache_file = cache_dir / f"{cache_key}.md"
        cache_file.write_text(markdown, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to save Mathpix cache: {e}")


def _get_pdf_info(filepath: Path) -> tuple[int, int]:
    """Get PDF file size and page count.

    Returns:
        (file_size_bytes, page_count)
    """
    file_size = filepath.stat().st_size
    try:
        reader = PdfReader(str(filepath))
        page_count = len(reader.pages)
    except Exception:
        page_count = 0
    return file_size, page_count


def _calculate_batches(file_size: int, page_count: int) -> list[str]:
    """Calculate page range batches for Mathpix conversion.

    Mathpix has a file size limit per request. For files under 1.5MB,
    we send the entire document. For larger files, we batch by pages.

    Args:
        file_size: File size in bytes
        page_count: Total number of pages

    Returns:
        List of page range strings like ["1-10", "11-20"]
    """
    if page_count <= 0:
        return [""]  # Let Mathpix handle it

    # Under 1.5MB: single batch
    if file_size < 1_500_000:
        return [f"1-{page_count}"]

    # Calculate average page size and determine pages per batch
    avg_page_size = file_size / page_count
    # Target ~1.2MB per batch (conservative, under 1.5MB limit)
    target_batch_size = 1_200_000
    pages_per_batch = max(1, int(target_batch_size / avg_page_size))
    # Cap at 10 pages per batch
    pages_per_batch = min(pages_per_batch, 10)

    batches = []
    start = 1
    while start <= page_count:
        end = min(start + pages_per_batch - 1, page_count)
        batches.append(f"{start}-{end}")
        start = end + 1

    return batches


async def convert_pdf_to_markdown(
    filepath: Path,
    use_cache: bool = True,
    page_ranges: Optional[str] = None,
) -> dict:
    """Convert a PDF to markdown using Mathpix.

    Handles caching and adaptive batching for large PDFs.

    Args:
        filepath: Path to the PDF file
        use_cache: Whether to use file-based caching (default True)
        page_ranges: Optional explicit page ranges (e.g., "1-10,15-20")

    Returns:
        {
            success: bool,
            markdown: str,
            metadata: {
                pages: int,
                batches: int,
                cache_hit: bool,
                conversion_time: float
            }
        }
    """
    if not filepath.exists():
        raise MathpixError(f"PDF file not found: {filepath}")

    start_time = time.time()

    # Check cache
    cache_key = _get_cache_key(filepath)
    if use_cache:
        cached = _get_cached(cache_key)
        if cached is not None:
            file_size, page_count = _get_pdf_info(filepath)
            return {
                "success": True,
                "markdown": cached,
                "metadata": {
                    "pages": page_count,
                    "batches": 0,
                    "cache_hit": True,
                    "conversion_time": time.time() - start_time,
                },
            }

    # Get PDF info for batching
    file_size, page_count = _get_pdf_info(filepath)

    # Determine batches
    if page_ranges:
        batches = [page_ranges]
    else:
        batches = _calculate_batches(file_size, page_count)

    # Get client
    client = get_mathpix_client()

    # Process each batch
    markdown_parts = []
    for batch_range in batches:
        md_text = await _convert_batch(client, filepath, batch_range)
        markdown_parts.append(md_text)

    # Merge results
    merged_markdown = "\n\n".join(markdown_parts)

    # Cache the result
    if use_cache:
        _save_cache(cache_key, merged_markdown)

    return {
        "success": True,
        "markdown": merged_markdown,
        "metadata": {
            "pages": page_count,
            "batches": len(batches),
            "cache_hit": False,
            "conversion_time": time.time() - start_time,
        },
    }


async def _convert_batch(
    client,
    filepath: Path,
    page_range: str,
    max_retries: int = 3,
) -> str:
    """Convert a single batch of pages via Mathpix with retry logic.

    Args:
        client: MathpixClient instance
        filepath: Path to the PDF
        page_range: Page range string (e.g., "1-10") or empty for all
        max_retries: Maximum retry attempts

    Returns:
        Markdown text for this batch
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            kwargs = {
                "file_path": str(filepath),
                "convert_to_md": True,
            }
            if page_range:
                kwargs["page_ranges"] = page_range

            # Run the synchronous Mathpix API call in a thread
            def _do_convert(kw=kwargs):
                pdf_obj = client.pdf_new(**kw)
                pdf_obj.wait_until_complete(timeout=120)
                return pdf_obj.to_md_text()

            md_text = await asyncio.to_thread(_do_convert)

            return md_text

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    f"Mathpix batch {page_range} attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)

    raise MathpixError(
        f"Failed to convert pages {page_range} after {max_retries} attempts: {last_error}"
    )


def extract_pdf_text_with_pages_mathpix(filepath: Path) -> tuple[str, list[int]]:
    """Extract PDF text using Mathpix, returning format compatible with pdfplumber.

    This is a drop-in replacement for extract_pdf_text_with_pages() from rag_embed.
    Converts the PDF to markdown via Mathpix, then parses page break positions
    from the markdown output.

    Args:
        filepath: Path to PDF file

    Returns:
        Tuple of (full_text, page_break_positions) matching pdfplumber's format
    """
    # Run async conversion synchronously
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context - create a new thread to run it
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run, convert_pdf_to_markdown(filepath)
            )
            result = future.result()
    else:
        result = asyncio.run(convert_pdf_to_markdown(filepath))

    if not result["success"]:
        raise MathpixError("Mathpix conversion failed")

    markdown = result["markdown"]

    # Parse page breaks from Mathpix markdown
    # Mathpix uses patterns like "\\newpage" or page markers
    page_breaks = [0]  # First page starts at 0
    page_markers = list(re.finditer(r'\\newpage|---\s*\n', markdown))
    for marker in page_markers:
        page_breaks.append(marker.start())

    return markdown, page_breaks
