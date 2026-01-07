"""
Zotero operations for litrev-mcp.

Implements tools for interacting with Zotero library:
- zotero_list_projects: List collections with paper counts
- zotero_create_collection: Create a new Zotero collection
- zotero_add_paper: Add paper by DOI or manual entry
- zotero_update_status: Change status tags
- zotero_get_by_status: Filter papers by status
- zotero_search: Search within library
- zotero_get_citation_key: Get Better BibTeX citation key
"""

from typing import Any, Optional
from pyzotero.zotero import Zotero

from litrev_mcp.config import (
    config_manager,
    get_zotero_api_key,
    get_zotero_user_id,
)


class ZoteroError(Exception):
    """Base exception for Zotero operations."""
    pass


class ZoteroAuthError(ZoteroError):
    """Authentication failed."""
    pass


class ZoteroNotFoundError(ZoteroError):
    """Item or collection not found."""
    pass


def get_zotero_client() -> Zotero:
    """Get an authenticated Zotero client."""
    api_key = get_zotero_api_key()
    user_id = get_zotero_user_id()

    if not api_key:
        raise ZoteroAuthError("ZOTERO_API_KEY environment variable is not set")
    if not user_id:
        raise ZoteroAuthError("ZOTERO_USER_ID environment variable is not set")

    return Zotero(user_id, "user", api_key)


def get_citation_key_from_extra(extra: str) -> Optional[str]:
    """
    Extract Better BibTeX citation key from item's extra field.

    BBT stores the citation key as 'Citation Key: xxx' in the extra field.
    """
    if not extra:
        return None

    for line in extra.split('\n'):
        line = line.strip()
        if line.lower().startswith('citation key:'):
            return line.split(':', 1)[1].strip()

    return None


def get_status_from_tags(tags: list[dict], status_tags: dict) -> Optional[str]:
    """Determine paper status from its tags."""
    tag_names = {t.get('tag', '') for t in tags}

    if status_tags.get('complete') in tag_names:
        return 'complete'
    elif status_tags.get('needs_notebooklm') in tag_names:
        return 'needs_notebooklm'
    elif status_tags.get('needs_pdf') in tag_names:
        return 'needs_pdf'

    return None


def format_authors(creators: list[dict]) -> str:
    """Format creator list as author string."""
    authors = []
    for creator in creators:
        if creator.get('creatorType') == 'author':
            if creator.get('name'):
                authors.append(creator['name'])
            elif creator.get('lastName'):
                authors.append(creator['lastName'])

    if not authors:
        return "Unknown"
    elif len(authors) <= 3:
        return ", ".join(authors)
    else:
        return f"{authors[0]} et al."


def item_to_dict(item: dict, config) -> dict:
    """Convert Zotero item to standardized dict."""
    data = item.get('data', {})

    citation_key = get_citation_key_from_extra(data.get('extra', ''))
    status = get_status_from_tags(
        data.get('tags', []),
        {
            'needs_pdf': config.status_tags.needs_pdf,
            'needs_notebooklm': config.status_tags.needs_notebooklm,
            'complete': config.status_tags.complete,
        }
    )

    return {
        'item_key': data.get('key'),
        'citation_key': citation_key,
        'title': data.get('title', 'Untitled'),
        'authors': format_authors(data.get('creators', [])),
        'year': data.get('date', '')[:4] if data.get('date') else None,
        'doi': data.get('DOI'),
        'item_type': data.get('itemType'),
        'status': status,
        'pdf_filename': f"{citation_key}.pdf" if citation_key else None,
    }


# ============================================================================
# Tool Implementations
# ============================================================================

async def zotero_list_projects() -> dict[str, Any]:
    """
    List all collections (projects) with paper counts by status.

    Returns:
        Dictionary with projects list, each containing counts by status.
    """
    try:
        zot = get_zotero_client()
        config = config_manager.load()

        collections = zot.collections()

        projects = []
        for coll in collections:
            coll_data = coll.get('data', {})
            coll_key = coll_data.get('key')
            coll_name = coll_data.get('name', 'Unknown')

            # Find project code from config
            project_code = None
            for code, proj in config.projects.items():
                if proj.zotero_collection_key == coll_key:
                    project_code = code
                    break

            # Get items in collection
            items = zot.collection_items(coll_key, itemType='-attachment')

            # Count by status
            counts = {'total': 0, 'needs_pdf': 0, 'needs_notebooklm': 0, 'complete': 0, 'untagged': 0}
            for item in items:
                counts['total'] += 1
                status = get_status_from_tags(
                    item.get('data', {}).get('tags', []),
                    {
                        'needs_pdf': config.status_tags.needs_pdf,
                        'needs_notebooklm': config.status_tags.needs_notebooklm,
                        'complete': config.status_tags.complete,
                    }
                )
                if status:
                    counts[status] += 1
                else:
                    counts['untagged'] += 1

            projects.append({
                'key': coll_key,
                'name': coll_name,
                'code': project_code,
                'total_papers': counts['total'],
                'needs_pdf': counts['needs_pdf'],
                'needs_notebooklm': counts['needs_notebooklm'],
                'complete': counts['complete'],
                'untagged': counts['untagged'],
            })

        return {'success': True, 'projects': projects}

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_create_collection(
    name: str,
    parent_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a new Zotero collection.

    Args:
        name: Name for the new collection
        parent_key: Parent collection key for nested collections (optional)

    Returns:
        Dictionary with collection key and details.
    """
    try:
        zot = get_zotero_client()

        # Build collection data
        collection_data = {"name": name}
        if parent_key:
            collection_data["parentCollection"] = parent_key

        # Create the collection
        resp = zot.create_collections([collection_data])

        if resp.get('successful'):
            created = list(resp['successful'].values())[0]
            coll_key = created.get('key')
            coll_data = created.get('data', {})

            return {
                'success': True,
                'collection_key': coll_key,
                'name': coll_data.get('name', name),
                'parent_key': coll_data.get('parentCollection'),
                'message': f"Collection '{name}' created. Use this key to link to a project.",
            }
        else:
            failed = resp.get('failed', {})
            error_msg = str(failed) if failed else "Unknown error creating collection"
            return {
                'success': False,
                'error': {'code': 'ZOTERO_CREATE_FAILED', 'message': error_msg}
            }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_add_paper(
    project: str,
    doi: Optional[str] = None,
    title: Optional[str] = None,
    authors: Optional[str] = None,
    year: Optional[int] = None,
    source: Optional[str] = None,
) -> dict[str, Any]:
    """
    Add a paper to Zotero by DOI or manual metadata.

    Automatically tags with _needs-pdf.

    Args:
        project: Project code (e.g., "MEAS-ERR")
        doi: DOI - if provided, fetches metadata automatically
        title: Manual title (if no DOI)
        authors: Manual authors (if no DOI)
        year: Manual year (if no DOI)
        source: Where this was found (e.g., "PubMed", "Consensus")

    Returns:
        Dictionary with item details and citation key.
    """
    try:
        zot = get_zotero_client()
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

        # Create item template
        if doi:
            # Try to fetch metadata from DOI
            # Note: Zotero Web API doesn't have direct DOI lookup
            # We'll create a basic item and let BBT handle the citation key
            template = zot.item_template('journalArticle')
            template['DOI'] = doi
            template['title'] = title or f"[DOI: {doi}]"
            if authors:
                template['creators'] = [{'creatorType': 'author', 'name': authors}]
            if year:
                template['date'] = str(year)
        else:
            if not title:
                return {
                    'success': False,
                    'error': {
                        'code': 'MISSING_METADATA',
                        'message': "Either DOI or title is required",
                    }
                }
            template = zot.item_template('journalArticle')
            template['title'] = title
            if authors:
                template['creators'] = [{'creatorType': 'author', 'name': authors}]
            if year:
                template['date'] = str(year)

        # Add status tag
        template['tags'] = [{'tag': config.status_tags.needs_pdf}]

        # Add source note if provided
        if source:
            template['extra'] = f"Source: {source}"

        # Add to collection
        template['collections'] = [collection_key]

        # Create the item
        resp = zot.create_items([template])

        if resp.get('successful'):
            created = list(resp['successful'].values())[0]
            item_key = created.get('key')

            # Fetch the created item to get any BBT-generated citation key
            item = zot.item(item_key)
            item_data = item.get('data', {})
            citation_key = get_citation_key_from_extra(item_data.get('extra', ''))

            return {
                'success': True,
                'item_key': item_key,
                'citation_key': citation_key,
                'title': item_data.get('title'),
                'drive_filename': f"{citation_key}.pdf" if citation_key else None,
                'drive_folder': f"Literature/{project}/",
                'message': f"Added to {project}. Tagged as {config.status_tags.needs_pdf}.",
            }
        else:
            failed = resp.get('failed', {})
            error_msg = str(failed) if failed else "Unknown error creating item"
            return {
                'success': False,
                'error': {'code': 'ZOTERO_CREATE_FAILED', 'message': error_msg}
            }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_update_status(
    new_status: str,
    item_key: Optional[str] = None,
    doi: Optional[str] = None,
    title_search: Optional[str] = None,
) -> dict[str, Any]:
    """
    Update the status tag on a paper.

    Args:
        new_status: One of "needs_pdf", "needs_notebooklm", "complete"
        item_key: Zotero item key (optional)
        doi: Identify by DOI (optional)
        title_search: Search by title fragment (optional)

    Returns:
        Dictionary with update result.
    """
    try:
        zot = get_zotero_client()
        config = config_manager.load()

        # Validate status
        valid_statuses = ['needs_pdf', 'needs_notebooklm', 'complete']
        if new_status not in valid_statuses:
            return {
                'success': False,
                'error': {
                    'code': 'INVALID_STATUS',
                    'message': f"Status must be one of: {', '.join(valid_statuses)}",
                }
            }

        # Find the item
        item = None
        if item_key:
            try:
                item = zot.item(item_key)
            except Exception:
                pass

        if not item and doi:
            results = zot.items(q=doi, itemType='-attachment')
            for r in results:
                if r.get('data', {}).get('DOI') == doi:
                    item = r
                    break

        if not item and title_search:
            results = zot.items(q=title_search, itemType='-attachment', limit=10)
            if results:
                item = results[0]  # Take first match

        if not item:
            return {
                'success': False,
                'error': {
                    'code': 'ZOTERO_NOT_FOUND',
                    'message': "Could not find item with the provided identifier",
                }
            }

        item_data = item.get('data', {})

        # Get current status
        old_status = get_status_from_tags(
            item_data.get('tags', []),
            {
                'needs_pdf': config.status_tags.needs_pdf,
                'needs_notebooklm': config.status_tags.needs_notebooklm,
                'complete': config.status_tags.complete,
            }
        )

        # Remove old status tags, add new one
        status_tag_values = {
            config.status_tags.needs_pdf,
            config.status_tags.needs_notebooklm,
            config.status_tags.complete,
        }

        new_tags = [t for t in item_data.get('tags', []) if t.get('tag') not in status_tag_values]

        new_tag_value = getattr(config.status_tags, new_status)
        new_tags.append({'tag': new_tag_value})

        # Update the item
        item_data['tags'] = new_tags
        zot.update_item(item_data)

        return {
            'success': True,
            'item_key': item_data.get('key'),
            'title': item_data.get('title'),
            'old_status': old_status,
            'new_status': new_status,
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_get_by_status(
    project: str,
    status: str,
) -> dict[str, Any]:
    """
    Get papers filtered by status within a project.

    Args:
        project: Project code
        status: One of "needs_pdf", "needs_notebooklm", "complete", "all"

    Returns:
        Dictionary with matching papers.
    """
    try:
        zot = get_zotero_client()
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

        # Get items in collection
        items = zot.collection_items(collection_key, itemType='-attachment')

        # Filter by status
        papers = []
        for item in items:
            item_dict = item_to_dict(item, config)

            if status == 'all' or item_dict['status'] == status:
                papers.append(item_dict)

        return {
            'success': True,
            'project': project,
            'status': status,
            'count': len(papers),
            'papers': papers,
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_search(
    query: str,
    project: Optional[str] = None,
) -> dict[str, Any]:
    """
    Search within your Zotero library.

    Args:
        query: Search query
        project: Limit to specific project (optional)

    Returns:
        Dictionary with matching papers including citation keys.
    """
    try:
        zot = get_zotero_client()
        config = config_manager.load()

        # Search in collection if project specified
        if project:
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

            if collection_key:
                items = zot.collection_items(collection_key, q=query, itemType='-attachment')
            else:
                items = zot.items(q=query, itemType='-attachment')
        else:
            items = zot.items(q=query, itemType='-attachment')

        papers = [item_to_dict(item, config) for item in items]

        return {
            'success': True,
            'query': query,
            'project': project,
            'count': len(papers),
            'papers': papers,
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}


async def zotero_get_citation_key(
    item_key: Optional[str] = None,
    doi: Optional[str] = None,
    title_search: Optional[str] = None,
) -> dict[str, Any]:
    """
    Get Better BibTeX citation key(s) for paper(s).

    Args:
        item_key: Zotero item key (optional)
        doi: Identify by DOI (optional)
        title_search: Search by title fragment, may return multiple (optional)

    Returns:
        Dictionary with citation key results.
    """
    try:
        zot = get_zotero_client()
        config = config_manager.load()

        items = []

        if item_key:
            try:
                item = zot.item(item_key)
                items = [item]
            except Exception:
                pass

        if not items and doi:
            results = zot.items(q=doi, itemType='-attachment')
            for r in results:
                if r.get('data', {}).get('DOI') == doi:
                    items = [r]
                    break

        if not items and title_search:
            items = zot.items(q=title_search, itemType='-attachment', limit=10)

        if not items:
            return {
                'success': False,
                'error': {
                    'code': 'ZOTERO_NOT_FOUND',
                    'message': "Could not find item(s) with the provided identifier",
                }
            }

        results = []
        for item in items:
            item_data = item.get('data', {})
            citation_key = get_citation_key_from_extra(item_data.get('extra', ''))

            results.append({
                'item_key': item_data.get('key'),
                'citation_key': citation_key,
                'title': item_data.get('title'),
                'authors': format_authors(item_data.get('creators', [])),
                'year': item_data.get('date', '')[:4] if item_data.get('date') else None,
                'pdf_filename': f"{citation_key}.pdf" if citation_key else None,
            })

        return {
            'success': True,
            'results': results,
        }

    except ZoteroAuthError as e:
        return {'success': False, 'error': {'code': 'ZOTERO_AUTH_FAILED', 'message': str(e)}}
    except Exception as e:
        return {'success': False, 'error': {'code': 'ZOTERO_ERROR', 'message': str(e)}}
