"""
Insights storage and retrieval for litrev-mcp.

Stores AI-generated summaries, synthesis notes, and reading notes as
searchable markdown files with YAML frontmatter.

Storage location: Literature/{PROJECT}/_notes/{date}_{source}_{topic}.md
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import yaml

from litrev_mcp.config import config_manager
from litrev_mcp.tools.context import get_context_text


def extract_dois_from_content(content: str) -> list[str]:
    """Extract DOIs from text content (e.g., Consensus output)."""
    # Match DOI patterns:
    # - https://doi.org/10.xxxx/yyyy
    # - doi.org/10.xxxx/yyyy
    # - 10.xxxx/yyyy (bare DOI)
    doi_pattern = r'(?:https?://)?(?:doi\.org/|dx\.doi\.org/)?(10\.\d{4,}/[^\s\)\]\"\'>,]+)'

    matches = re.findall(doi_pattern, content, re.IGNORECASE)

    # Clean up DOIs (remove trailing punctuation)
    cleaned = []
    for doi in matches:
        # Remove trailing punctuation that might have been captured
        doi = re.sub(r'[.,;:\)\]]+$', '', doi)
        if doi not in cleaned:
            cleaned.append(doi)

    return cleaned


async def fetch_crossref_metadata(doi: str) -> Optional[dict[str, Any]]:
    """
    Fetch metadata from CrossRef API for a DOI.

    Returns dict with title, authors, year, journal or None if not found.
    """
    import httpx

    url = f"https://api.crossref.org/works/{doi}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "litrev-mcp/0.1.0 (mailto:litrev@example.com)"}
            )

            if response.status_code != 200:
                return None

            data = response.json()
            work = data.get("message", {})

            # Extract title
            titles = work.get("title", [])
            title = titles[0] if titles else None

            # Extract authors
            authors_list = work.get("author", [])
            if authors_list:
                author_names = []
                for author in authors_list[:3]:  # First 3 authors
                    if author.get("family"):
                        author_names.append(author["family"])
                    elif author.get("name"):
                        author_names.append(author["name"])

                if len(authors_list) > 3:
                    authors = ", ".join(author_names) + " et al."
                else:
                    authors = ", ".join(author_names)
            else:
                authors = None

            # Extract year
            date_parts = work.get("published-print", work.get("published-online", {}))
            date_list = date_parts.get("date-parts", [[]])
            year = date_list[0][0] if date_list and date_list[0] else None

            # Extract journal
            container = work.get("container-title", [])
            journal = container[0] if container else None

            return {
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
            }

    except Exception:
        return None


def sanitize_filename(text: str) -> str:
    """Convert text to safe filename component."""
    # Remove special characters, keep alphanumeric, dash, underscore
    text = re.sub(r'[^\w\s-]', '', text)
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    # Convert to lowercase
    text = text.lower()
    # Limit length
    return text[:50]


def get_notes_path(project: str) -> Optional[Path]:
    """Get the _notes directory path for a project."""
    lit_path = config_manager.literature_path
    if not lit_path:
        return None

    notes_path = lit_path / project / "_notes"
    return notes_path


def parse_insight_file(filepath: Path) -> dict:
    """Parse an insight markdown file with YAML frontmatter."""
    try:
        content = filepath.read_text(encoding='utf-8')

        # Split frontmatter and body
        if content.startswith('---\n'):
            parts = content.split('---\n', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                body = parts[2].strip()
            else:
                frontmatter = {}
                body = content
        else:
            frontmatter = {}
            body = content

        return {
            'filepath': str(filepath),
            'filename': filepath.name,
            'frontmatter': frontmatter,
            'content': body,
        }
    except Exception:
        return None


async def save_insight(
    project: str,
    source: str,
    topic: str,
    content: str,
    query: Optional[str] = None,
    papers_referenced: Optional[list[str]] = None,
    add_references_to_zotero: bool = False,
) -> dict[str, Any]:
    """
    Save a Consensus summary, NotebookLM answer, or synthesis note.

    Args:
        project: Project code (e.g., "MEAS-ERR")
        source: One of "consensus", "notebooklm", "synthesis", "reading_notes"
        topic: Brief descriptor (becomes part of filename)
        content: The actual content to save
        query: Original question that prompted this (optional)
        papers_referenced: List of citation keys mentioned (optional)
        add_references_to_zotero: If True, extract DOIs and add to Zotero (default False)

    Returns:
        Dictionary with filepath and success status.
    """
    try:
        config = config_manager.load()

        # Validate project
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found in config",
                }
            }

        # Validate source
        valid_sources = ['consensus', 'notebooklm', 'synthesis', 'reading_notes']
        if source not in valid_sources:
            return {
                'success': False,
                'error': {
                    'code': 'INVALID_SOURCE',
                    'message': f"Source must be one of: {', '.join(valid_sources)}",
                }
            }

        # Get notes directory
        notes_path = get_notes_path(project)
        if not notes_path:
            return {
                'success': False,
                'error': {
                    'code': 'DRIVE_PATH_NOT_FOUND',
                    'message': "Google Drive path not detected",
                }
            }

        # Create directory if needed
        notes_path.mkdir(parents=True, exist_ok=True)

        # Generate filename
        date_str = datetime.now().strftime('%Y-%m-%d')
        topic_safe = sanitize_filename(topic)
        filename = f"{date_str}_{source}_{topic_safe}.md"
        filepath = notes_path / filename

        # Build frontmatter
        frontmatter = {
            'date': date_str,
            'source': source,
            'topic': topic,
        }

        if query:
            frontmatter['query'] = query

        if papers_referenced:
            frontmatter['papers_referenced'] = papers_referenced

        # Write file
        file_content = "---\n"
        file_content += yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        file_content += "---\n\n"
        file_content += content

        filepath.write_text(file_content, encoding='utf-8')

        result = {
            'success': True,
            'filepath': str(filepath),
            'message': f"Saved insight to {project} notes",
        }

        # Optionally add references to Zotero
        if add_references_to_zotero:
            zotero_result = await _add_references_to_zotero(content, project, config)
            result['zotero_import'] = zotero_result

        return result

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SAVE_ERROR',
                'message': str(e),
            }
        }


async def _add_references_to_zotero(content: str, project: str, config) -> dict[str, Any]:
    """
    Extract DOIs from content, fetch metadata from CrossRef, and add new ones to Zotero.

    Returns summary of what was added/skipped.
    """
    from litrev_mcp.tools.zotero import get_zotero_client, zotero_add_paper

    # Extract DOIs from content
    dois = extract_dois_from_content(content)

    if not dois:
        return {
            'dois_found': 0,
            'added': [],
            'skipped': [],
            'errors': [],
        }

    # Get Zotero client and existing items in collection
    zot = get_zotero_client()
    proj_config = config.projects[project]
    collection_key = proj_config.zotero_collection_key

    if not collection_key:
        return {
            'dois_found': len(dois),
            'added': [],
            'skipped': [],
            'errors': [{'doi': 'all', 'error': 'No Zotero collection configured for project'}],
        }

    # Get existing DOIs in collection
    existing_items = zot.collection_items(collection_key, itemType='-attachment')
    existing_dois = set()
    for item in existing_items:
        item_doi = item.get('data', {}).get('DOI', '')
        if item_doi:
            # Normalize DOI (lowercase, strip whitespace)
            existing_dois.add(item_doi.lower().strip())

    added = []
    skipped = []
    errors = []

    for doi in dois:
        doi_normalized = doi.lower().strip()

        # Check if already exists
        if doi_normalized in existing_dois:
            skipped.append({'doi': doi, 'reason': 'Already in Zotero'})
            continue

        # Fetch metadata from CrossRef
        metadata = await fetch_crossref_metadata(doi)

        # Add to Zotero with metadata
        try:
            if metadata and metadata.get('title'):
                # Use CrossRef metadata
                add_result = await zotero_add_paper(
                    project=project,
                    doi=doi,
                    title=metadata.get('title'),
                    authors=metadata.get('authors'),
                    year=metadata.get('year'),
                    source='Consensus',
                )
            else:
                # Fallback to DOI-only if CrossRef fails
                add_result = await zotero_add_paper(
                    project=project,
                    doi=doi,
                    source='Consensus',
                )

            if add_result.get('success'):
                added.append({
                    'doi': doi,
                    'item_key': add_result.get('item_key'),
                    'title': add_result.get('title'),
                    'authors': metadata.get('authors') if metadata else None,
                    'year': metadata.get('year') if metadata else None,
                })
                # Add to existing set to avoid duplicates within same batch
                existing_dois.add(doi_normalized)
            else:
                errors.append({
                    'doi': doi,
                    'error': add_result.get('error', {}).get('message', 'Unknown error'),
                })
        except Exception as e:
            errors.append({'doi': doi, 'error': str(e)})

    return {
        'dois_found': len(dois),
        'added': added,
        'skipped': skipped,
        'errors': errors,
    }


async def search_insights(
    query: str,
    project: Optional[str] = None,
    source: Optional[str] = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search saved insights and return content for synthesis.

    Args:
        query: Search query or question
        project: Limit to specific project (optional)
        source: Filter by source type (optional)
        max_results: Maximum results to return (default 10)

    Returns:
        Dictionary with matching insights.
    """
    try:
        config = config_manager.load()
        lit_path = config_manager.literature_path

        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'DRIVE_PATH_NOT_FOUND',
                    'message': "Google Drive path not detected",
                }
            }

        # Determine which projects to search
        projects_to_search = []
        if project:
            if project not in config.projects:
                return {
                    'success': False,
                    'error': {
                        'code': 'PROJECT_NOT_FOUND',
                        'message': f"Project '{project}' not found",
                    }
                }
            projects_to_search = [project]
        else:
            projects_to_search = list(config.projects.keys())

        # Search through insights
        matches = []
        query_lower = query.lower()

        for proj in projects_to_search:
            notes_path = get_notes_path(proj)
            if not notes_path or not notes_path.exists():
                continue

            for filepath in notes_path.glob('*.md'):
                insight = parse_insight_file(filepath)
                if not insight:
                    continue

                # Filter by source if specified
                if source:
                    fm_source = insight['frontmatter'].get('source', '')
                    if fm_source != source:
                        continue

                # Search in content and frontmatter
                content_lower = insight['content'].lower()
                topic_lower = insight['frontmatter'].get('topic', '').lower()
                query_fm = insight['frontmatter'].get('query', '').lower()

                if query_lower in content_lower or query_lower in topic_lower or query_lower in query_fm:
                    # Extract relevance snippet
                    snippet_match = re.search(
                        f'.{{0,100}}{re.escape(query_lower)}.{{0,100}}',
                        content_lower,
                        re.IGNORECASE
                    )
                    snippet = snippet_match.group(0) if snippet_match else content_lower[:200]

                    matches.append({
                        'filepath': insight['filepath'],
                        'project': proj,
                        'source': insight['frontmatter'].get('source'),
                        'date': insight['frontmatter'].get('date'),
                        'topic': insight['frontmatter'].get('topic'),
                        'original_query': insight['frontmatter'].get('query'),
                        'content': insight['content'],
                        'papers_referenced': insight['frontmatter'].get('papers_referenced', []),
                        'relevance_snippet': snippet,
                    })

        # Limit results
        matches = matches[:max_results]

        # Get context if project specified
        context_text = get_context_text(project) if project else None

        return {
            'success': True,
            'query': query,
            'context': context_text,
            'total_matches': len(matches),
            'matches': matches,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SEARCH_ERROR',
                'message': str(e),
            }
        }


async def analyze_insights(
    question: str,
    project: Optional[str] = None,
    mode: str = "answer",
) -> dict[str, Any]:
    """
    Analyze insights to answer a question, compare sources, or detect tensions.

    Args:
        question: The question to answer or analyze
        project: Limit to specific project (optional)
        mode: "answer" (default), "compare", or "tensions"

    Returns:
        Dictionary with synthesis and analysis.
    """
    try:
        # First, search for relevant insights
        search_result = await search_insights(query=question, project=project, max_results=20)

        if not search_result['success']:
            return search_result

        matches = search_result['matches']

        if not matches:
            return {
                'success': True,
                'question': question,
                'mode': mode,
                'insights_analyzed': 0,
                'synthesis': "No relevant insights found for this question.",
                'sources_used': [],
                'tensions_detected': [],
                'gaps_identified': [],
            }

        # Build synthesis based on mode
        sources_used = []
        for match in matches:
            sources_used.append({
                'filepath': match['filepath'],
                'source': match['source'],
                'date': match['date'],
                'topic': match['topic'],
            })

        # For now, return the raw matches for the agent to synthesize
        # In a full implementation, this could use an LLM to synthesize
        synthesis_parts = []

        # Add project context if available
        if project:
            project_context = get_context_text(project)
            if project_context:
                synthesis_parts.append(f"## Project Context\n{project_context}\n\n---\n")

        if mode == "answer":
            synthesis_parts.append(f"Based on {len(matches)} saved insights:\n")
            for i, match in enumerate(matches[:5], 1):
                synthesis_parts.append(f"\n{i}. From {match['source']} ({match['date']}):")
                synthesis_parts.append(f"   Topic: {match['topic']}")
                if match.get('original_query'):
                    synthesis_parts.append(f"   Original query: {match['original_query']}")
                synthesis_parts.append(f"   Snippet: {match['relevance_snippet'][:200]}...")

        elif mode == "compare":
            synthesis_parts.append(f"Comparing insights from {len(matches)} sources:\n")
            by_source = {}
            for match in matches:
                src = match['source']
                if src not in by_source:
                    by_source[src] = []
                by_source[src].append(match)

            for src, items in by_source.items():
                synthesis_parts.append(f"\n{src.upper()} ({len(items)} notes):")
                for item in items[:3]:
                    synthesis_parts.append(f"  - {item['topic']} ({item['date']})")

        elif mode == "tensions":
            synthesis_parts.append("Analyzing for potential tensions/contradictions:\n")
            synthesis_parts.append("(Manual review of content needed to detect contradictions)")

        synthesis = "\n".join(synthesis_parts)

        return {
            'success': True,
            'question': question,
            'mode': mode,
            'insights_analyzed': len(matches),
            'sources_used': sources_used,
            'synthesis': synthesis,
            'tensions_detected': [],  # Would require LLM analysis
            'gaps_identified': [],  # Would require LLM analysis
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'ANALYZE_ERROR',
                'message': str(e),
            }
        }


async def list_insights(
    project: str,
    source: Optional[str] = None,
) -> dict[str, Any]:
    """
    List all saved insights for a project.

    Args:
        project: Project code
        source: Filter by source type (optional)

    Returns:
        Dictionary with insights list.
    """
    try:
        config = config_manager.load()

        # Validate project
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found",
                }
            }

        notes_path = get_notes_path(project)
        if not notes_path or not notes_path.exists():
            return {
                'success': True,
                'project': project,
                'total_insights': 0,
                'insights': [],
                'by_source': {},
            }

        # Collect all insights
        insights = []
        by_source = {}

        for filepath in notes_path.glob('*.md'):
            insight = parse_insight_file(filepath)
            if not insight:
                continue

            fm_source = insight['frontmatter'].get('source', 'unknown')

            # Filter by source if specified
            if source and fm_source != source:
                continue

            insights.append({
                'filepath': insight['filepath'],
                'filename': insight['filename'],
                'source': fm_source,
                'date': insight['frontmatter'].get('date'),
                'topic': insight['frontmatter'].get('topic'),
                'papers_referenced': insight['frontmatter'].get('papers_referenced', []),
            })

            # Count by source
            by_source[fm_source] = by_source.get(fm_source, 0) + 1

        # Sort by date (newest first)
        insights.sort(key=lambda x: x['date'], reverse=True)

        return {
            'success': True,
            'project': project,
            'context': get_context_text(project),
            'total_insights': len(insights),
            'insights': insights,
            'by_source': by_source,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'LIST_ERROR',
                'message': str(e),
            }
        }
