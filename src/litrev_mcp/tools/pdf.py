"""
PDF processing tools for litrev-mcp.

Implements tools for processing PDFs in project inbox:
- process_pdf_inbox: Match PDFs to Zotero entries and organize them
- migrate_zotero_attachments: Download server-stored PDFs, move to Drive, add links
"""

import shutil
from pathlib import Path
from typing import Any, Optional

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


def _try_add_drive_link(
    zot: Any,
    item_key: str,
    filename: str,
    project: str,
    max_retries: int = 3,
    initial_delay: float = 3.0,
) -> Optional[str]:
    """
    Try to add a Google Drive link to a Zotero item.

    Includes retry logic to handle Google Drive sync delays after file moves.

    Args:
        zot: Pyzotero client
        item_key: Zotero item key
        filename: PDF filename
        project: Project code
        max_retries: Number of retry attempts (default 3)
        initial_delay: Initial delay in seconds before first attempt (default 3.0)

    Returns the Drive URL if successful, None if Drive integration unavailable.
    """
    import time

    try:
        from litrev_mcp.tools.gdrive import (
            get_drive_link_for_pdf,
            add_link_attachment_to_zotero,
            get_credentials_path,
        )

        # Check if credentials are configured
        if not get_credentials_path():
            return None

        # Initial delay to allow Google Drive to sync the moved file
        time.sleep(initial_delay)

        # Retry logic for Drive link retrieval
        drive_url = None
        for attempt in range(max_retries):
            drive_url = get_drive_link_for_pdf(filename, project)
            if drive_url:
                break
            # Exponential backoff: 2s, 4s, 8s...
            if attempt < max_retries - 1:
                delay = 2 ** (attempt + 1)
                time.sleep(delay)

        if not drive_url:
            return None

        # Add as linked URL attachment to Zotero
        import asyncio
        # Run async function synchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context, just await directly won't work
            # So we'll use a simple sync approach
            from litrev_mcp.tools.gdrive import add_link_attachment_to_zotero
            result = _sync_add_link(zot, item_key, drive_url, f"PDF - Google Drive")
        else:
            result = loop.run_until_complete(
                add_link_attachment_to_zotero(zot, item_key, drive_url, f"PDF - Google Drive")
            )

        if result.get('success'):
            return drive_url
        return None

    except ImportError:
        # PyDrive2 not installed
        return None
    except Exception:
        # Drive integration failed but shouldn't stop processing
        return None


def _sync_add_link(zot: Any, item_key: str, url: str, title: str) -> dict:
    """Synchronously add a linked URL attachment to Zotero."""
    try:
        attachment = {
            'itemType': 'attachment',
            'parentItem': item_key,
            'linkMode': 'linked_url',
            'title': title,
            'url': url,
            'contentType': 'application/pdf',
            'tags': [],
            'relations': {},
        }
        result = zot.create_items([attachment])
        return {'success': bool(result.get('successful'))}
    except Exception as e:
        return {'success': False, 'error': str(e)}


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
                    project_code=project,
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
    project_code: str,
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

        # Try to add Google Drive link
        drive_url = _try_add_drive_link(zot, best_match['item_key'], new_filename, project_code)

        return {
            'status': 'processed',
            'filename': pdf_path.name,
            'matched_to': best_match['title'],
            'match_score': round(best_score, 2),
            'new_name': new_filename,
            'item_key': best_match['item_key'],
            'drive_url': drive_url,
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


async def migrate_zotero_attachments(project: str) -> dict[str, Any]:
    """
    Migrate Zotero server-stored PDF attachments to Google Drive.

    For each item in the project collection that has a PDF stored on Zotero's servers:
    1. Download the PDF
    2. Save to Google Drive folder with citation key naming
    3. Add Google Drive link as attachment in Zotero
    4. Delete the original server-stored attachment
    5. Update status tag to needs_notebooklm

    Args:
        project: Project code (e.g., "TEST")

    Returns:
        Dictionary with migration results:
        {
            success: bool,
            project: str,
            migrated: [{item_key, title, filename, drive_url}],
            skipped: [{item_key, title, reason}],
            errors: [{item_key, title, error}]
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

        # Check Google Drive credentials
        try:
            from litrev_mcp.tools.gdrive import get_credentials_path
            if not get_credentials_path():
                return {
                    'success': False,
                    'error': {
                        'code': 'GDRIVE_NOT_CONFIGURED',
                        'message': "Google Drive credentials not found. Place credentials.json in .litrev folder.",
                    }
                }
        except ImportError:
            return {
                'success': False,
                'error': {
                    'code': 'PYDRIVE_NOT_INSTALLED',
                    'message': "PyDrive2 is not installed. Run: pip install PyDrive2",
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

        # Ensure project folder exists
        project_path.mkdir(parents=True, exist_ok=True)

        # Get Zotero client and items
        zot = get_zotero_client()
        items = zot.collection_items(collection_key, itemType='-attachment')

        migrated = []
        skipped = []
        errors = []

        for item in items:
            item_data = item.get('data', {})
            item_key = item_data.get('key')
            title = item_data.get('title', 'Untitled')

            try:
                result = await _migrate_single_item(
                    zot=zot,
                    item=item,
                    project_path=project_path,
                    project_code=project,
                    config=config,
                )

                if result['status'] == 'migrated':
                    migrated.append(result)
                elif result['status'] == 'skipped':
                    skipped.append(result)

            except Exception as e:
                errors.append({
                    'item_key': item_key,
                    'title': title,
                    'error': str(e),
                })

        return {
            'success': True,
            'project': project,
            'migrated': migrated,
            'skipped': skipped,
            'errors': errors,
            'summary': f"Migrated {len(migrated)}, skipped {len(skipped)}, errors {len(errors)}",
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'MIGRATION_ERROR', 'message': str(e)}}


async def _migrate_single_item(
    zot: Any,
    item: dict,
    project_path: Path,
    project_code: str,
    config: Any,
) -> dict[str, Any]:
    """
    Migrate a single Zotero item's server-stored PDF to Google Drive.

    Returns dict with status 'migrated' or 'skipped'.
    """
    import time
    from litrev_mcp.tools.gdrive import (
        get_drive_link_for_pdf,
        get_credentials_path,
    )

    item_data = item.get('data', {})
    item_key = item_data.get('key')
    title = item_data.get('title', 'Untitled')

    # Get children (attachments) for this item
    children = zot.children(item_key)

    # Find server-stored PDF attachments (linkMode: "imported_file" or "imported_url")
    pdf_attachments = []
    has_drive_link = False

    for child in children:
        child_data = child.get('data', {})
        link_mode = child_data.get('linkMode', '')
        content_type = child_data.get('contentType', '')

        # Check if already has a Google Drive link
        if link_mode == 'linked_url' and 'drive.google.com' in child_data.get('url', ''):
            has_drive_link = True

        # Find imported PDF attachments
        if link_mode in ('imported_file', 'imported_url') and 'pdf' in content_type.lower():
            pdf_attachments.append(child)

    # Skip if no server-stored PDFs
    if not pdf_attachments:
        return {
            'status': 'skipped',
            'item_key': item_key,
            'title': title,
            'reason': 'No server-stored PDF attachments found',
        }

    # Skip if already has Drive link (avoid duplicates)
    if has_drive_link:
        return {
            'status': 'skipped',
            'item_key': item_key,
            'title': title,
            'reason': 'Already has Google Drive link attachment',
        }

    # Get citation key for filename
    citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
    if not citation_key:
        citation_key = generate_citation_key(
            title,
            format_authors(item_data.get('creators', [])),
            item_data.get('date', '')[:4] if item_data.get('date') else '',
        )

    # Process first PDF attachment (usually there's only one)
    attachment = pdf_attachments[0]
    attachment_data = attachment.get('data', {})
    attachment_key = attachment_data.get('key')

    # Download the PDF content
    pdf_content = zot.file(attachment_key)

    # Save to project folder
    filename = f"{citation_key}.pdf"
    file_path = project_path / filename
    file_path.write_bytes(pdf_content)

    # Wait for Google Drive sync and get link
    # Note: Google Drive sync can take 30+ seconds for new files
    drive_url = None
    initial_delay = 5.0
    max_retries = 5

    time.sleep(initial_delay)

    for attempt in range(max_retries):
        drive_url = get_drive_link_for_pdf(filename, project_code)
        if drive_url:
            break
        if attempt < max_retries - 1:
            delay = 3 * (attempt + 1)  # 3s, 6s, 9s, 12s
            time.sleep(delay)

    if not drive_url:
        return {
            'status': 'skipped',
            'item_key': item_key,
            'title': title,
            'reason': f'PDF saved to {filename} but could not get Google Drive link (sync delay?)',
            'filename': filename,
        }

    # Add Drive link as attachment
    link_result = _sync_add_link(zot, item_key, drive_url, "PDF - Google Drive")

    if not link_result.get('success'):
        return {
            'status': 'skipped',
            'item_key': item_key,
            'title': title,
            'reason': f'Failed to add Drive link: {link_result.get("error")}',
            'filename': filename,
            'drive_url': drive_url,
        }

    # Delete the original server-stored attachment
    try:
        zot.delete_item(attachment_data)
    except Exception as e:
        # Non-critical - link was added, just couldn't delete original
        pass

    # Update status tag to needs_notebooklm
    try:
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
        'status': 'migrated',
        'item_key': item_key,
        'title': title,
        'filename': filename,
        'drive_url': drive_url,
    }
