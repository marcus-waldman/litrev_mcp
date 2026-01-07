"""
PDF processing tools for litrev-mcp.

Implements tools for processing PDFs in project inbox:
- process_pdf_inbox: Match PDFs to Zotero entries and organize them
"""

import shutil
from pathlib import Path
from typing import Any

from litrev_mcp.config import config_manager
from litrev_mcp.tools.pdf_utils import (
    extract_pdf_metadata,
    fuzzy_match_score,
    generate_citation_key,
)
from litrev_mcp.tools.zotero import (
    get_zotero_client,
    get_citation_key_from_extra,
    format_authors,
    ZoteroAuthError,
)


class PDFProcessingError(Exception):
    """Base exception for PDF processing operations."""
    pass


async def process_pdf_inbox(project: str) -> dict[str, Any]:
    """
    Process all PDFs in a project's to_add/ folder.

    For each PDF:
    1. Extract metadata (title, authors, DOI)
    2. Search Zotero collection for matches
    3. If match found with high confidence: rename, move, update status
    4. If no/low match: add to "needs_review" list for interactive handling

    Args:
        project: Project code (e.g., "TEST")

    Returns:
        Dictionary with processing results:
        {
            success: bool,
            project: str,
            processed: [{filename, matched_to, new_name, item_key}],
            needs_review: [{filename, extracted_metadata, possible_matches}],
            errors: [{filename, error}]
        }
    """
    try:
        config = config_manager.load()

        # Get project config
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found in config",
                }
            }

        proj_config = config.projects[project]
        collection_key = proj_config.zotero_collection_key

        if not collection_key:
            return {
                'success': False,
                'error': {
                    'code': 'COLLECTION_NOT_CONFIGURED',
                    'message': f"Project '{project}' has no Zotero collection key configured",
                }
            }

        # Get paths
        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'LITERATURE_PATH_NOT_FOUND',
                    'message': "Literature folder not found",
                }
            }

        project_path = lit_path / project
        inbox_path = project_path / "to_add"

        # Check if inbox exists
        if not inbox_path.exists():
            return {
                'success': True,
                'project': project,
                'message': f"No to_add folder found at {inbox_path}. Create it and add PDFs to process.",
                'processed': [],
                'needs_review': [],
                'errors': [],
            }

        # Find all PDFs in inbox
        pdf_files = list(inbox_path.glob("*.pdf"))
        if not pdf_files:
            return {
                'success': True,
                'project': project,
                'message': "No PDF files found in to_add folder.",
                'processed': [],
                'needs_review': [],
                'errors': [],
            }

        # Get Zotero items for matching
        zot = get_zotero_client()
        zotero_items = zot.collection_items(collection_key, itemType='-attachment')

        # Build lookup list from Zotero items
        zotero_lookup = []
        for item in zotero_items:
            data = item.get('data', {})
            zotero_lookup.append({
                'item_key': data.get('key'),
                'title': data.get('title', ''),
                'authors': format_authors(data.get('creators', [])),
                'year': data.get('date', '')[:4] if data.get('date') else '',
                'doi': data.get('DOI', ''),
                'citation_key': get_citation_key_from_extra(data.get('extra', '')),
                'tags': data.get('tags', []),
            })

        # Process each PDF
        processed = []
        needs_review = []
        errors = []

        for pdf_path in pdf_files:
            try:
                result = await _process_single_pdf(
                    pdf_path=pdf_path,
                    project_path=project_path,
                    zotero_lookup=zotero_lookup,
                    zot=zot,
                    config=config,
                )

                if result['status'] == 'processed':
                    processed.append(result)
                elif result['status'] == 'needs_review':
                    needs_review.append(result)

            except Exception as e:
                errors.append({
                    'filename': pdf_path.name,
                    'error': str(e),
                })

        return {
            'success': True,
            'project': project,
            'processed': processed,
            'needs_review': needs_review,
            'errors': errors,
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'PDF_PROCESSING_ERROR', 'message': str(e)}}


async def _process_single_pdf(
    pdf_path: Path,
    project_path: Path,
    zotero_lookup: list[dict],
    zot: Any,
    config: Any,
) -> dict[str, Any]:
    """
    Process a single PDF file.

    Returns dict with status 'processed' or 'needs_review'.
    """
    # Extract metadata from PDF
    extracted = extract_pdf_metadata(pdf_path)

    # Find best match in Zotero
    best_match = None
    best_score = 0.0
    possible_matches = []

    for zitem in zotero_lookup:
        score = fuzzy_match_score(extracted, zitem)
        if score > best_score:
            best_score = score
            best_match = zitem

        # Collect possible matches for review
        if score >= 0.3:
            possible_matches.append({
                'item_key': zitem['item_key'],
                'title': zitem['title'],
                'authors': zitem['authors'],
                'year': zitem['year'],
                'score': round(score, 2),
            })

    # Sort possible matches by score
    possible_matches.sort(key=lambda x: x['score'], reverse=True)
    possible_matches = possible_matches[:5]  # Top 5

    # High confidence match (score >= 0.7)
    if best_match and best_score >= 0.7:
        # Get or generate citation key
        citation_key = best_match.get('citation_key')
        if not citation_key:
            citation_key = generate_citation_key(
                best_match['title'],
                best_match['authors'],
                best_match['year'],
            )

        # New filename
        new_filename = f"{citation_key}.pdf"
        new_path = project_path / new_filename

        # Move and rename file
        shutil.move(str(pdf_path), str(new_path))

        # Update Zotero status tag
        try:
            item = zot.item(best_match['item_key'])
            item_data = item.get('data', {})

            # Remove old status tags, add needs_notebooklm
            status_tags = {
                config.status_tags.needs_pdf,
                config.status_tags.needs_notebooklm,
                config.status_tags.complete,
            }
            new_tags = [t for t in item_data.get('tags', []) if t.get('tag') not in status_tags]
            new_tags.append({'tag': config.status_tags.needs_notebooklm})
            item_data['tags'] = new_tags
            zot.update_item(item_data)
        except Exception:
            pass  # Non-critical if status update fails

        return {
            'status': 'processed',
            'filename': pdf_path.name,
            'matched_to': best_match['title'],
            'match_score': round(best_score, 2),
            'new_name': new_filename,
            'item_key': best_match['item_key'],
        }

    # Low confidence or no match - needs review
    return {
        'status': 'needs_review',
        'filename': pdf_path.name,
        'extracted_metadata': {
            'title': extracted.get('title'),
            'authors': extracted.get('authors'),
            'year': extracted.get('year'),
            'doi': extracted.get('doi'),
        },
        'possible_matches': possible_matches,
        'best_score': round(best_score, 2) if best_match else 0.0,
    }
