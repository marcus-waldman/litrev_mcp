"""
RAG (Retrieval Augmented Generation) tools for literature search.

Provides semantic search over indexed PDF content using OpenAI embeddings
and DuckDB vector similarity search.
"""

import os
from pathlib import Path
from typing import Any, Optional

from litrev_mcp.config import config_manager
from litrev_mcp.tools.zotero import get_zotero_client, get_citation_key_from_extra, format_authors
from litrev_mcp.tools.pdf_utils import generate_citation_key, extract_year_from_date, match_pdf_by_metadata
from litrev_mcp.tools.rag_db import (
    get_connection,
    paper_exists,
    delete_paper,
    insert_paper,
    insert_chunks_batch,
    search_similar,
    get_indexed_papers,
    get_stats,
)
from litrev_mcp.tools.rag_embed import (
    extract_pdf_text_with_pages,
    extract_pdf_text,
    extract_document_text,
    chunk_text,
    EmbeddingError,
)
from litrev_mcp.tools.formats import find_document_by_key
from litrev_mcp.tools.raw_http import async_embed_texts_raw, async_embed_query_raw
from litrev_mcp.tools.context import get_context_text


async def index_papers(
    project: str,
    force_reindex: bool = False,
    use_mathpix: bool = False,
) -> dict[str, Any]:
    """
    Index PDFs from a project for semantic search.

    Extracts text from PDFs in the project folder, chunks it,
    generates embeddings via OpenAI, and stores in DuckDB.

    Note: For large collections, use generate_index_script() to create a
    standalone Python script that runs without MCP timeout constraints.

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

        # Process papers sequentially (parallelism provides no benefit - DB writes serialize)
        results = await _index_papers_sequential(
            items=items,
            project_path=project_path,
            project=project,
            force_reindex=force_reindex,
            use_mathpix=use_mathpix,
        )

        total_chunks = sum(p['chunks'] for p in results['indexed'])
        summary = f"Indexed {len(results['indexed'])} papers ({total_chunks} chunks), skipped {len(results['skipped'])}, errors {len(results['errors'])}"

        result = {
            'success': True,
            'project': project,
            **results,
            'summary': summary,
        }

        # Add workflow guidance
        if config.workflow.show_guidance:
            result['guidance'] = {
                'next_steps': [
                    f'{len(results["indexed"])} papers indexed - ready for semantic search',
                    'Use ask_papers to answer questions from your literature',
                    'Review _gaps.md to see which questions you can now answer',
                    'Document findings with save_insight as you discover them'
                ],
                'best_practice': 'Use ask_papers for synthesis, not just keyword search'
            }

        return result

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


async def _index_papers_sequential(
    items: list,
    project_path: Path,
    project: str,
    force_reindex: bool,
    use_mathpix: bool = False,
) -> dict:
    """Process papers sequentially (simpler, just as fast since DB writes serialize)."""
    indexed = []
    skipped = []
    errors = []

    for item in items:
        item_data = item.get('data', {})
        item_key = item_data.get('key')
        citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
        title = item_data.get('title', 'Untitled')

        try:
            # Check if already indexed
            if not force_reindex and paper_exists(item_key):
                skipped.append({'item_key': item_key, 'citation_key': citation_key, 'reason': 'Already indexed'})
                continue

            # Find document (PDF or EPUB)
            doc_path = _find_document(item_data, project_path, citation_key)
            if not doc_path:
                skipped.append({'item_key': item_key, 'citation_key': citation_key, 'reason': 'No document found'})
                continue

            # Delete existing if reindexing
            if force_reindex and paper_exists(item_key):
                delete_paper(item_key)

            # Extract, chunk, embed, save
            text, page_breaks = extract_document_text(doc_path, use_mathpix=use_mathpix)
            if not text.strip():
                skipped.append({'item_key': item_key, 'citation_key': citation_key, 'reason': 'No extractable text'})
                continue

            chunks = chunk_text(text, page_breaks=page_breaks)
            if not chunks:
                skipped.append({'item_key': item_key, 'citation_key': citation_key, 'reason': 'No chunks generated'})
                continue

            chunk_texts = [c['text'] for c in chunks]
            embeddings = await async_embed_texts_raw(chunk_texts)

            # Save to database
            authors = format_authors(item_data.get('creators', []))
            year = _extract_year(item_data.get('date', ''))

            insert_paper(
                item_key=item_key,
                citation_key=citation_key,
                title=title,
                authors=authors,
                year=year,
                project=project,
                pdf_path=str(doc_path),
                total_chunks=len(chunks),
            )
            insert_chunks_batch(item_key=item_key, chunks=chunks, embeddings=embeddings)

            indexed.append({
                'item_key': item_key,
                'citation_key': citation_key,
                'title': title,
                'chunks': len(chunks),
            })

        except Exception as e:
            errors.append({
                'item_key': item_key,
                'citation_key': citation_key,
                'error': str(e),
            })

    return {'indexed': indexed, 'skipped': skipped, 'errors': errors}


def _find_document(item_data: dict, project_path: Path, citation_key: Optional[str]) -> Optional[Path]:
    """Find a document file (PDF or EPUB) for a paper."""
    # Try citation key from Extra field
    if citation_key:
        found = find_document_by_key(project_path, citation_key)
        if found:
            return found

    # Try generating citation key from metadata
    title = item_data.get('title', '')
    authors = format_authors(item_data.get('creators', []))
    year = extract_year_from_date(item_data.get('date', '')) or ''

    if title and authors and year:
        generated_key = generate_citation_key(title, authors, year)
        found = find_document_by_key(project_path, generated_key)
        if found:
            return found

    # Fallback: scan directory for best metadata match
    if title and authors:
        matched = match_pdf_by_metadata(project_path, title, authors, year)
        if matched:
            return matched

    return None


def _extract_year(date_str: str) -> Optional[int]:
    """Extract year from date string (handles '2019', '05/2019', '2019-05-01', etc.)."""
    if not date_str:
        return None
    import re
    match = re.search(r'\b(19\d{2}|20\d{2})\b', date_str)
    if match:
        return int(match.group(1))
    return None


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

        # Generate query embedding using raw HTTP to avoid OpenAI client
        # deadlock in the MCP event loop (both sync and async httpx clients
        # conflict with the MCP server's event loop)
        query_embedding = await async_embed_query_raw(query)

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
    max_passages: int = 10,
) -> dict[str, Any]:
    """
    Ask a question about your literature.

    Searches indexed papers and returns relevant passages with coverage
    metadata and synthesis instructions. Claude Code synthesizes the answer,
    with guidance to honestly assess whether the literature adequately
    addresses the question.

    Args:
        question: Natural language question about your papers
        project: Limit to specific project (optional)
        max_passages: Number of relevant passages to include (default 10, max 20)

    Returns:
        {
            success: bool,
            question: str,
            context: str,  # Formatted passages with synthesis instructions
            coverage: {passages_found, unique_papers, scores: {min, max, mean}},
            sources: [{citation_key, title, authors, year, page, score}]
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
                'context': "No relevant passages found in your indexed papers. Make sure papers are indexed using index_papers first.",
                'coverage': {'passages_found': 0, 'unique_papers': 0, 'scores': None},
                'sources': [],
            }

        # Calculate coverage metadata
        unique_papers = len(set(r['citation_key'] for r in results))
        scores = [r['score'] for r in results]
        coverage = {
            'passages_found': len(results),
            'unique_papers': unique_papers,
            'scores': {
                'min': round(min(scores), 4),
                'max': round(max(scores), 4),
                'mean': round(sum(scores) / len(scores), 4),
            }
        }

        # Build context with passages and synthesis instructions
        context_parts = []

        # Add project context if available
        if project:
            project_context = get_context_text(project)
            if project_context:
                context_parts.append(f"## Project Context\n{project_context}\n\n---\n")

        # Question
        context_parts.append(f"## Question\n{question}\n\n")

        # Coverage summary (helps model reason about adequacy)
        context_parts.append(
            f"## Literature Coverage\n"
            f"Found {coverage['passages_found']} passages from {coverage['unique_papers']} papers. "
            f"Similarity scores: {coverage['scores']['min']:.2f} to {coverage['scores']['max']:.2f} "
            f"(mean: {coverage['scores']['mean']:.2f}).\n\n"
        )

        # Passages
        context_parts.append("## Relevant Passages\n")
        for i, r in enumerate(results, 1):
            citation = r['citation_key']
            if r['page_number']:
                citation += f", p.{r['page_number']}"

            context_parts.append(
                f"\n[{i}] {r['title']} ({citation}):\n"
                f'"{r["text"]}"\n'
            )

        # Synthesis instructions
        context_parts.append("""
---

## Synthesis Instructions

Based on these passages, provide a thoughtful response to the question.

**Important:** Before synthesizing, consider whether this literature actually addresses the question well:
- Do these passages directly address the question, or are they tangentially related?
- Is the topic well-covered (multiple papers, different perspectives) or thinly covered?
- Are there aspects of the question that none of the passages address?

If coverage is limited or incomplete:
- Be honest about what the passages do and don't address
- Provide the best answer from what's available, but note limitations naturally
- Suggest specific follow-up searches (search terms, databases like PubMed/Semantic Scholar/Consensus)

If coverage is good:
- Synthesize across sources, noting agreements and any tensions
- Cite sources using the citation keys

Write in a natural, reasoning tone. Avoid formulaic language - reason authentically about the coverage and answer.
""")

        # Add project context reminder if present
        if project and get_context_text(project):
            context_parts.append(
                "\nTailor your response to the project's goal, audience, and style.\n"
            )

        # Build sources list
        sources = [
            {
                'citation_key': r['citation_key'],
                'title': r['title'],
                'authors': r['authors'],
                'year': r['year'],
                'page': r['page_number'],
                'score': r['score'],
            }
            for r in results
        ]

        result = {
            'success': True,
            'question': question,
            'context': ''.join(context_parts),
            'coverage': coverage,
            'sources': sources,
        }

        # Add workflow guidance
        from litrev_mcp.config import config_manager
        config = config_manager.load()
        if config.workflow.show_guidance:
            result['guidance'] = {
                'next_steps': [
                    'Save this synthesis with save_insight if valuable',
                    'Update _synthesis_notes.md with how this connects to manuscript',
                    'If this answers a gap, update _gaps.md',
                    'If this changes understanding, document with save_pivot'
                ],
                'best_practice': 'Link RAG findings to manuscript sections for easy retrieval'
            }

        return result

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


async def generate_index_script(
    project: str,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """
    Generate a standalone Python script for indexing papers.

    Creates a script at Literature/{PROJECT}/index_papers.py that can be run
    directly without MCP timeout constraints. Recommended for large collections.

    Args:
        project: Project code (e.g., 'MI-IC')
        force_reindex: If True, script will reindex all papers

    Returns:
        {success, filepath, instructions}
    """
    try:
        config = config_manager.load()

        if project not in config.projects:
            return {
                'success': False,
                'error': {'code': 'PROJECT_NOT_FOUND', 'message': f"Project '{project}' not found"}
            }

        proj_config = config.projects[project]
        if not proj_config.zotero_collection_key:
            return {
                'success': False,
                'error': {'code': 'COLLECTION_NOT_CONFIGURED', 'message': 'No Zotero collection configured'}
            }

        # Generate script content
        script_content = _generate_script_content(project, proj_config.zotero_collection_key, force_reindex)

        # Write to project folder
        lit_path = config_manager.literature_path
        script_path = lit_path / project / "index_papers.py"
        script_path.write_text(script_content, encoding='utf-8')

        return {
            'success': True,
            'filepath': str(script_path),
            'instructions': [
                f'cd "{lit_path / project}"',
                'python index_papers.py',
            ],
            'message': f'Script generated at {script_path}. Run it directly to index papers.',
        }
    except Exception as e:
        return {'success': False, 'error': {'code': 'SCRIPT_ERROR', 'message': str(e)}}


def _generate_script_content(project: str, collection_key: str, force_reindex: bool) -> str:
    """Generate the standalone indexing script content."""
    return f'''#!/usr/bin/env python3
"""
Standalone indexing script for project: {project}
Generated by litrev-mcp

Run: python index_papers.py
"""

import os
import sys
from pathlib import Path

def main():
    # Ensure environment variables are set
    required_vars = ['ZOTERO_API_KEY', 'ZOTERO_USER_ID', 'OPENAI_API_KEY', 'MOTHERDUCK_TOKEN']
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variables: {{', '.join(missing)}}")
        print("Set these as system environment variables before running.")
        sys.exit(1)

    # Import litrev modules
    try:
        from litrev_mcp.config import config_manager
        from litrev_mcp.tools.zotero import get_zotero_client, get_citation_key_from_extra, format_authors
        from litrev_mcp.tools.rag_db import get_connection, paper_exists, delete_paper, insert_paper, insert_chunks_batch
        from litrev_mcp.tools.rag_embed import extract_document_text, chunk_text, embed_texts
        from litrev_mcp.tools.pdf_utils import generate_citation_key, extract_year_from_date, match_pdf_by_metadata
        from litrev_mcp.tools.formats import find_document_by_key
    except ImportError as e:
        print(f"ERROR: Could not import litrev_mcp: {{e}}")
        print("Make sure litrev-mcp is installed: pip install litrev-mcp")
        sys.exit(1)

    project = "{project}"
    collection_key = "{collection_key}"
    force_reindex = {force_reindex}

    print(f"Indexing project: {{project}}")
    print(f"Force reindex: {{force_reindex}}")
    print()

    # Load config and get paths
    config = config_manager.load()
    project_path = config_manager.literature_path / project

    print(f"Project path: {{project_path}}")

    # Connect to Zotero
    print("Connecting to Zotero...")
    zot = get_zotero_client()
    items = zot.collection_items(collection_key, itemType='-attachment')
    print(f"Found {{len(items)}} items in Zotero collection")

    # Connect to database
    print("Connecting to database...")
    get_connection()

    # Process papers
    print()
    indexed = 0
    skipped = 0
    errors = 0

    for i, item in enumerate(items):
        item_data = item.get('data', {{}})
        item_key = item_data.get('key')
        citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
        title = item_data.get('title', 'Untitled')[:50]

        print(f"[{{i+1}}/{{len(items)}}] {{citation_key or item_key}}: {{title}}...")

        # Check if already indexed
        if not force_reindex and paper_exists(item_key):
            print("  SKIP: Already indexed")
            skipped += 1
            continue

        # Delete existing if reindexing
        if force_reindex and paper_exists(item_key):
            delete_paper(item_key)

        # Find document (PDF or EPUB)
        doc_path = None
        if citation_key:
            doc_path = find_document_by_key(project_path, citation_key)

        if not doc_path:
            # Try generating key from metadata
            authors = format_authors(item_data.get('creators', []))
            year = extract_year_from_date(item_data.get('date', '')) or ''
            if item_data.get('title') and authors and year:
                gen_key = generate_citation_key(item_data['title'], authors, year)
                found = find_document_by_key(project_path, gen_key)
                if found:
                    citation_key = gen_key
                    doc_path = found

        if not doc_path:
            # Fallback: scan directory for best metadata match
            authors = format_authors(item_data.get('creators', []))
            year = extract_year_from_date(item_data.get('date', '')) or ''
            matched = match_pdf_by_metadata(project_path, item_data.get('title', ''), authors, year)
            if matched:
                doc_path = matched
                print(f"  Matched by metadata scan: {{matched.name}}")

        if not doc_path:
            print("  SKIP: No document found")
            skipped += 1
            continue

        try:
            # Extract text
            text, page_breaks = extract_document_text(doc_path, use_mathpix=True)
            if not text.strip():
                print("  SKIP: No extractable text")
                skipped += 1
                continue

            # Chunk and embed
            chunks = chunk_text(text, page_breaks=page_breaks)
            print(f"  {{len(chunks)}} chunks, embedding...")

            chunk_texts = [c['text'] for c in chunks]
            embeddings = embed_texts(chunk_texts)

            # Save to database
            authors = format_authors(item_data.get('creators', []))
            year_str = extract_year_from_date(item_data.get('date', ''))
            year = int(year_str) if year_str else None

            insert_paper(
                item_key=item_key,
                citation_key=citation_key,
                title=item_data.get('title', 'Untitled'),
                authors=authors,
                year=year,
                project=project,
                pdf_path=str(doc_path),
                total_chunks=len(chunks),
            )
            insert_chunks_batch(item_key=item_key, chunks=chunks, embeddings=embeddings)

            print("  OK")
            indexed += 1

        except Exception as e:
            print(f"  ERROR: {{e}}")
            errors += 1

    print()
    print("=" * 50)
    print(f"Done! Indexed: {{indexed}}, Skipped: {{skipped}}, Errors: {{errors}}")


if __name__ == "__main__":
    main()
'''
