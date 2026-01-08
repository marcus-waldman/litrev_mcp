"""
RAG (Retrieval Augmented Generation) tools for literature search.

Provides semantic search over indexed PDF content using OpenAI embeddings
and DuckDB vector similarity search.
"""

from pathlib import Path
from typing import Any, Optional

from litrev_mcp.config import config_manager
from litrev_mcp.tools.zotero import get_zotero_client, get_citation_key_from_extra, format_authors
from litrev_mcp.tools.pdf_utils import generate_citation_key
from litrev_mcp.tools.rag_db import (
    get_connection,
    paper_exists,
    delete_paper,
    insert_paper,
    insert_chunk,
    search_similar,
    get_indexed_papers,
    get_stats,
)
from litrev_mcp.tools.rag_embed import (
    extract_pdf_text_with_pages,
    chunk_text,
    embed_texts,
    embed_query,
    EmbeddingError,
)


async def index_papers(
    project: str,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """
    Index PDFs from a project for semantic search.

    Extracts text from PDFs in the project folder, chunks it,
    generates embeddings via OpenAI, and stores in DuckDB.

    Args:
        project: Project code (e.g., 'MI-IC')
        force_reindex: If True, reindex papers even if already indexed

    Returns:
        {
            success: bool,
            project: str,
            indexed: [{item_key, citation_key, title, chunks}],
            skipped: [{item_key, citation_key, reason}],
            errors: [{item_key, error}],
            summary: str
        }
    """
    try:
        config = config_manager.load()

        # Validate project
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found in config"
                }
            }

        proj_config = config.projects[project]
        collection_key = proj_config.zotero_collection_key

        if not collection_key:
            return {
                'success': False,
                'error': {
                    'code': 'COLLECTION_NOT_CONFIGURED',
                    'message': f"No Zotero collection configured for project '{project}'"
                }
            }

        # Get project folder path
        lit_path = config_manager.literature_path
        project_path = lit_path / project

        if not project_path.exists():
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_FOLDER_NOT_FOUND',
                    'message': f"Project folder not found: {project_path}"
                }
            }

        # Get Zotero items for metadata
        zot = get_zotero_client()
        items = zot.collection_items(collection_key, itemType='-attachment')

        # Initialize database connection
        get_connection()

        indexed = []
        skipped = []
        errors = []

        for item in items:
            item_data = item.get('data', {})
            item_key = item_data.get('key')
            citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
            title = item_data.get('title', 'Untitled')

            try:
                result = await _index_single_paper(
                    item_data=item_data,
                    project_path=project_path,
                    project=project,
                    force_reindex=force_reindex,
                )

                if result['status'] == 'indexed':
                    indexed.append({
                        'item_key': item_key,
                        'citation_key': citation_key,
                        'title': title,
                        'chunks': result['chunks'],
                    })
                elif result['status'] == 'skipped':
                    skipped.append({
                        'item_key': item_key,
                        'citation_key': citation_key,
                        'reason': result['reason'],
                    })

            except Exception as e:
                errors.append({
                    'item_key': item_key,
                    'citation_key': citation_key,
                    'error': str(e),
                })

        summary = f"Indexed {len(indexed)} papers ({sum(p['chunks'] for p in indexed)} chunks), skipped {len(skipped)}, errors {len(errors)}"

        return {
            'success': True,
            'project': project,
            'indexed': indexed,
            'skipped': skipped,
            'errors': errors,
            'summary': summary,
        }

    except EmbeddingError as e:
        return {
            'success': False,
            'error': {
                'code': 'EMBEDDING_ERROR',
                'message': str(e)
            }
        }
    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'INDEX_ERROR',
                'message': str(e)
            }
        }


async def _index_single_paper(
    item_data: dict,
    project_path: Path,
    project: str,
    force_reindex: bool,
) -> dict:
    """Index a single paper."""
    item_key = item_data.get('key')
    citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
    title = item_data.get('title', 'Untitled')

    # Check if already indexed
    if not force_reindex and paper_exists(item_key):
        return {'status': 'skipped', 'reason': 'Already indexed'}

    # Find PDF file
    pdf_path = None
    if citation_key:
        candidate = project_path / f"{citation_key}.pdf"
        if candidate.exists():
            pdf_path = candidate

    # If no citation key in Extra, try to generate one from metadata
    if not pdf_path:
        authors = format_authors(item_data.get('creators', []))
        year = item_data.get('date', '')[:4] if item_data.get('date') else ''
        if title and authors and year:
            generated_key = generate_citation_key(title, authors, year)
            candidate = project_path / f"{generated_key}.pdf"
            if candidate.exists():
                citation_key = generated_key
                pdf_path = candidate

    if not pdf_path:
        return {'status': 'skipped', 'reason': 'No PDF found'}

    # Extract text with page breaks
    try:
        full_text, page_breaks = extract_pdf_text_with_pages(pdf_path)
    except Exception as e:
        return {'status': 'skipped', 'reason': f'PDF extraction failed: {e}'}

    if not full_text.strip():
        return {'status': 'skipped', 'reason': 'PDF has no extractable text'}

    # Chunk the text
    chunks = chunk_text(full_text, page_breaks=page_breaks)

    if not chunks:
        return {'status': 'skipped', 'reason': 'No chunks generated'}

    # Generate embeddings (batch for efficiency)
    chunk_texts = [c['text'] for c in chunks]
    embeddings = embed_texts(chunk_texts)

    # Delete existing data if reindexing
    if force_reindex:
        delete_paper(item_key)

    # Insert paper metadata
    authors = format_authors(item_data.get('creators', []))
    year = None
    date_str = item_data.get('date', '')
    if date_str and len(date_str) >= 4:
        try:
            year = int(date_str[:4])
        except ValueError:
            pass

    insert_paper(
        item_key=item_key,
        citation_key=citation_key,
        title=title,
        authors=authors,
        year=year,
        project=project,
        pdf_path=str(pdf_path),
        total_chunks=len(chunks),
    )

    # Insert chunks with embeddings
    for chunk, embedding in zip(chunks, embeddings):
        insert_chunk(
            item_key=item_key,
            chunk_index=chunk['chunk_index'],
            page_number=chunk['page_number'],
            text=chunk['text'],
            embedding=embedding,
        )

    return {'status': 'indexed', 'chunks': len(chunks)}


async def search_papers(
    query: str,
    project: Optional[str] = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Semantic search across indexed paper PDFs.

    Uses OpenAI embeddings and DuckDB vector similarity search
    to find relevant passages.

    Args:
        query: Natural language search query
        project: Limit to specific project (optional)
        max_results: Maximum results to return (default 10, max 50)

    Returns:
        {
            success: bool,
            query: str,
            results: [{citation_key, title, authors, year, page_number, text, score}]
        }
    """
    try:
        # Validate max_results
        max_results = min(max(1, max_results), 50)

        # Validate project if provided
        if project:
            config = config_manager.load()
            if project not in config.projects:
                return {
                    'success': False,
                    'error': {
                        'code': 'PROJECT_NOT_FOUND',
                        'message': f"Project '{project}' not found"
                    }
                }

        # Initialize connection
        get_connection()

        # Generate query embedding
        query_embedding = embed_query(query)

        # Search for similar chunks
        results = search_similar(
            query_embedding=query_embedding,
            project=project,
            max_results=max_results,
        )

        return {
            'success': True,
            'query': query,
            'count': len(results),
            'results': results,
        }

    except EmbeddingError as e:
        return {
            'success': False,
            'error': {
                'code': 'EMBEDDING_ERROR',
                'message': str(e)
            }
        }
    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SEARCH_ERROR',
                'message': str(e)
            }
        }


async def ask_papers(
    question: str,
    project: Optional[str] = None,
    max_passages: int = 5,
) -> dict[str, Any]:
    """
    Ask a question about your literature.

    Searches indexed papers and returns relevant passages formatted
    with citations for Claude to synthesize an answer.

    Args:
        question: Natural language question about your papers
        project: Limit to specific project (optional)
        max_passages: Number of relevant passages to include (default 5, max 20)

    Returns:
        {
            success: bool,
            question: str,
            context: str,  # Formatted passages with citations
            sources: [{citation_key, title, page, score}]
        }
    """
    try:
        # Validate max_passages
        max_passages = min(max(1, max_passages), 20)

        # Use search_papers to get relevant passages
        search_result = await search_papers(
            query=question,
            project=project,
            max_results=max_passages,
        )

        if not search_result['success']:
            return search_result

        results = search_result.get('results', [])

        if not results:
            return {
                'success': True,
                'question': question,
                'context': "No relevant passages found in the indexed papers. Make sure papers are indexed using index_papers first.",
                'sources': [],
            }

        # Format passages for Claude
        context_parts = [
            f"Question: {question}\n\n"
            f"Relevant passages from your literature ({len(results)} found):\n"
        ]

        sources = []
        for i, r in enumerate(results, 1):
            # Build citation string
            if r['page_number']:
                citation = f"{r['citation_key']}, p.{r['page_number']}"
            else:
                citation = r['citation_key']

            # Add passage with citation
            context_parts.append(
                f"\n[{i}] {r['title']} ({citation}):\n"
                f'"{r["text"]}"\n'
            )

            sources.append({
                'citation_key': r['citation_key'],
                'title': r['title'],
                'authors': r['authors'],
                'year': r['year'],
                'page': r['page_number'],
                'score': r['score'],
            })

        context_parts.append(
            "\nBased on these passages from your literature, synthesize an answer to the question. "
            "Cite sources using the citation keys provided."
        )

        return {
            'success': True,
            'question': question,
            'context': ''.join(context_parts),
            'sources': sources,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'ASK_ERROR',
                'message': str(e)
            }
        }


async def rag_status(project: Optional[str] = None) -> dict[str, Any]:
    """
    Get RAG index status and statistics.

    Args:
        project: Limit to specific project (optional)

    Returns:
        {
            success: bool,
            stats: {total_papers, total_chunks, papers_by_project},
            indexed_papers: [{item_key, citation_key, title, total_chunks, indexed_at}]
        }
    """
    try:
        get_connection()

        stats = get_stats()
        papers = get_indexed_papers(project=project)

        return {
            'success': True,
            'stats': stats,
            'indexed_papers': papers,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'STATUS_ERROR',
                'message': str(e)
            }
        }
